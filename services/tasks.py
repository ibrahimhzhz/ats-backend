import asyncio
import re
import base64
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import models
from core.celery_app import celery_app
from database import SessionLocal
from services.ai_engine import extract_candidate_facts, extract_jd_requirements
from services.ai_engine import normalize_job_requirements
from services.pdf_parser import extract_text_from_pdf
from scoring import (
    calculate_deterministic_score,
    evaluate_knockout_filters,
    generate_candidate_signals,
    assign_bucket,
    bucket_to_status,
)


def _advance_job_progress(db, job_id: int, company_id: int):
    db.query(models.Job).filter(
        models.Job.id == job_id,
        models.Job.company_id == company_id,
    ).update(
        {
            "processed_resumes": func.coalesce(models.Job.processed_resumes, 0) + 1,
            "status": "processing",
        }
    )
    db.commit()


def _build_results_payload(job: models.Job, applicants: List[models.Applicant]) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for applicant in applicants:
        candidates.append(
            {
                "id": applicant.id,
                "name": applicant.name,
                "email": applicant.email,
                "years_experience": applicant.years_experience,
                "skills": applicant.skills,
                "match_score": applicant.match_score,
                "summary": applicant.summary,
                "status": applicant.status,
                "breakdown": applicant.breakdown,
            }
        )

    candidates.sort(
        key=lambda x: (
            1 if x.get("status") == "knockout" else 0,
            -(x.get("match_score") or 0),
        )
    )

    eligible_candidates = [c for c in candidates if c.get("status") != "knockout"]
    shortlisted = []
    if eligible_candidates:
        top_10_percent = max(1, len(eligible_candidates) // 10)
        shortlisted = eligible_candidates[:top_10_percent]

    processed_resumes = int(job.processed_resumes or 0)
    total_saved = len(candidates)
    rejected_count = sum(1 for c in candidates if c.get("status") == "rejected")
    review_count = sum(1 for c in candidates if c.get("status") == "review")
    knockout_count = sum(1 for c in candidates if c.get("status") == "knockout")

    duplicates_or_skipped = max(0, processed_resumes - total_saved)

    return {
        "total_processed": total_saved,
        "duplicates_skipped": duplicates_or_skipped,
        "knocked_out": knockout_count,
        "scored": total_saved,
        "ai_evaluated": total_saved,
        "shortlisted_count": len(shortlisted),
        "review_count": review_count,
        "rejected_count": rejected_count,
        "knockout_count": knockout_count,
        "shortlisted": shortlisted,
        "all_candidates": candidates,
        "criteria": {
            "job_title": job.title,
            "min_experience": job.min_experience,
            "required_skills": job.required_skills or [],
            "job_requirements": normalize_job_requirements(job.jd_requirements),
        },
    }


@celery_app.task(name="aggregate_job_results")
def aggregate_job_results(job_id: int, company_id: int):
    """Aggregate persisted applicants into jobs.results for UI and status polling."""
    with SessionLocal() as db:
        job = db.query(models.Job).filter(
            models.Job.id == job_id,
            models.Job.company_id == company_id,
        ).first()
        if not job:
            return

        applicants = (
            db.query(models.Applicant)
            .filter(
                models.Applicant.job_id == job_id,
                models.Applicant.company_id == company_id,
            )
            .order_by(models.Applicant.match_score.desc())
            .all()
        )

        results = _build_results_payload(job, applicants)
        job.results = results

        total = int(job.total_resumes or 0)
        processed = int(job.processed_resumes or 0)
        if total > 0 and processed >= total:
            job.status = "completed"
        elif job.status != "failed":
            job.status = "processing"

        db.commit()


@celery_app.task(name="process_resume")
def process_resume(resume_b64: str, job_id: int, company_id: int):
    """Process a single resume PDF payload and persist applicant scoring results."""
    with SessionLocal() as db:
        try:
            job = db.query(models.Job).filter(
                models.Job.id == job_id,
                models.Job.company_id == company_id,
            ).first()
            if not job:
                return

            pdf_bytes = base64.b64decode(resume_b64)

            resume_text = extract_text_from_pdf(pdf_bytes)
            if not resume_text or len(resume_text.strip()) < 50:
                _advance_job_progress(db, job_id, company_id)
                return

            email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", resume_text)
            pre_scan_email = email_match.group(0).lower() if email_match else None

            if pre_scan_email:
                duplicate = (
                    db.query(models.Applicant)
                    .filter(
                        models.Applicant.job_id == job_id,
                        models.Applicant.email == pre_scan_email,
                    )
                    .first()
                )
                if duplicate:
                    _advance_job_progress(db, job_id, company_id)
                    return

            normalized_requirements = normalize_job_requirements(job.jd_requirements)
            candidate_data: Dict[str, Any] = asyncio.run(
                extract_candidate_facts(resume_text, normalized_requirements)
            )

            # ── Build job config for scoring ──────────────────────────────
            effective_min_exp = (
                normalized_requirements.get("minimum_years_experience", 0)
                if normalized_requirements.get("minimum_years_experience", 0) > 0
                else float(job.min_experience or 0)
            )
            job_config: Dict[str, Any] = {
                "title": job.title or "",
                "min_experience": effective_min_exp,
                "required_skills": normalized_requirements.get("must_have_skills") or job.required_skills or [],
                "nice_to_have_skills": job.nice_to_have_skills or [],
                "required_education": normalized_requirements.get("education_requirement") or "bachelor",
                "department": job.department,
                "require_cover_letter": job.require_cover_letter or False,
                "require_portfolio": job.require_portfolio or False,
                "require_linkedin": job.require_linkedin or False,
                "custom_questions": job.custom_questions or [],
                "work_location_type": job.work_location_type,
                "application_deadline": job.application_deadline,
                "offers_visa_sponsorship": normalized_requirements.get("offers_visa_sponsorship"),
            }

            # ── Score ─────────────────────────────────────────────────────
            total_score, score_breakdown = calculate_deterministic_score(
                candidate_data, job_config,
            )

            # ── Knockout ──────────────────────────────────────────────────
            knockout_flags = evaluate_knockout_filters(
                candidate_data, job_config,
            )
            has_hard_knockout = any(
                f["severity"] == "hard" for f in knockout_flags
            )
            if has_hard_knockout:
                total_score = 0

            # ── Signals & bucket ──────────────────────────────────────────
            candidate_signals = generate_candidate_signals(candidate_data)
            bucket = assign_bucket(total_score, has_hard_knockout)
            candidate_status = bucket_to_status(bucket, has_hard_knockout)

            # ── Summary ───────────────────────────────────────────────────
            matched = score_breakdown["skills"].get("matched_required", [])
            missing = score_breakdown["skills"].get("missing_required", [])
            candidate_summary = (
                f"Score {total_score}/100. "
                f"Experience {score_breakdown['experience']['total']}/25, "
                f"Skills {score_breakdown['skills']['total']}/35 "
                f"({len(matched)} matched, {len(missing)} missing), "
                f"Education {score_breakdown['education']['total']}/15, "
                f"Role fit {score_breakdown['role_level']['total']}/10, "
                f"Application {score_breakdown['application_quality']['total']}/15."
            )
            if has_hard_knockout:
                reasons = "; ".join(
                    f["reason"] for f in knockout_flags if f["severity"] == "hard"
                )
                candidate_summary = f"Knockout: {reasons}. {candidate_summary}"

            applicant = models.Applicant(
                job_id=job_id,
                company_id=company_id,
                name=candidate_data.get("name", "Unknown"),
                email=candidate_data.get("email", pre_scan_email or "N/A"),
                phone=candidate_data.get("phone", ""),
                resume_text=resume_text[:10000],
                resume_pdf=pdf_bytes,
                years_experience=max(0, int(round(float(candidate_data.get("total_years_experience", 0) or 0.0)))),
                skills=candidate_data.get("skills_with_years", {}),
                match_score=total_score,
                summary=candidate_summary,
                status=candidate_status,
                breakdown=score_breakdown,
                # Enriched extraction fields
                skills_detailed=candidate_data.get("skills_detailed"),
                extracted_jobs=candidate_data.get("jobs"),
                extracted_education=candidate_data.get("education"),
                has_measurable_impact=candidate_data.get("has_measurable_impact"),
                has_contact_info=candidate_data.get("has_contact_info"),
                has_clear_job_titles=candidate_data.get("has_clear_job_titles"),
                employment_gaps=candidate_data.get("employment_gaps"),
                average_tenure_years=candidate_data.get("average_tenure_years"),
                extractable_text=candidate_data.get("extractable_text", True),
                cover_letter_analysis=candidate_data.get("cover_letter_analysis"),
                custom_answer_analysis=candidate_data.get("custom_answer_analysis"),
                # Score fields
                score_breakdown=score_breakdown,
                knockout_flags=knockout_flags,
                candidate_signals=candidate_signals,
            )
            db.add(applicant)
            db.commit()

        except IntegrityError as e:
            db.rollback()
            if "uq_applicants_job_email" not in str(e) and "UNIQUE constraint failed: applicants.job_id, applicants.email" not in str(e):
                raise
        finally:
            try:
                _advance_job_progress(db, job_id, company_id)
                aggregate_job_results.delay(job_id, company_id)
            except Exception:
                db.rollback()


@celery_app.task(name="process_public_resume")
def process_public_resume(
    resume_b64: str,
    job_id: int,
    company_id: int,
    submitted_name: str,
    submitted_email: str,
    submitted_phone: str | None = None,
    linkedin_url: str | None = None,
    portfolio_url: str | None = None,
    cover_letter: str | None = None,
    custom_answers: list[dict[str, str]] | None = None,
    **extra_payload,
):
    """Process a public portal submission and increment application_count on success."""
    if cover_letter is None:
        cover_letter = extra_payload.get("cover_letter")
    if custom_answers is None:
        custom_answers = extra_payload.get("custom_answers")
    with SessionLocal() as db:
        try:
            job = db.query(models.Job).filter(
                models.Job.id == job_id,
                models.Job.company_id == company_id,
            ).first()
            if not job:
                return

            pdf_bytes = base64.b64decode(resume_b64)

            resume_text = extract_text_from_pdf(pdf_bytes)
            if not resume_text or len(resume_text.strip()) < 50:
                resume_text = "Unable to extract text from resume."

            duplicate = (
                db.query(models.Applicant)
                .filter(
                    models.Applicant.job_id == job_id,
                    models.Applicant.email == submitted_email,
                )
                .first()
            )
            if duplicate:
                return

            normalized_requirements = normalize_job_requirements(job.jd_requirements)
            candidate_data: Dict[str, Any] = asyncio.run(
                extract_candidate_facts(resume_text, normalized_requirements)
            )

            if submitted_name and submitted_name.strip():
                candidate_data["name"] = submitted_name.strip()
            candidate_data["email"] = submitted_email.strip().lower()
            if submitted_phone and submitted_phone.strip():
                candidate_data["phone"] = submitted_phone.strip()

            # Merge form-submission fields so scoring/signals can see them
            candidate_data["cover_letter"] = cover_letter
            candidate_data["portfolio_url"] = portfolio_url
            candidate_data["linkedin_url"] = linkedin_url

            # ── Build job config for scoring ──────────────────────────────
            effective_min_exp = (
                normalized_requirements.get("minimum_years_experience", 0)
                if normalized_requirements.get("minimum_years_experience", 0) > 0
                else float(job.min_experience or 0)
            )
            job_config: Dict[str, Any] = {
                "title": job.title or "",
                "min_experience": effective_min_exp,
                "required_skills": normalized_requirements.get("must_have_skills") or job.required_skills or [],
                "nice_to_have_skills": job.nice_to_have_skills or [],
                "required_education": normalized_requirements.get("education_requirement") or "bachelor",
                "department": job.department,
                "require_cover_letter": job.require_cover_letter or False,
                "require_portfolio": job.require_portfolio or False,
                "require_linkedin": job.require_linkedin or False,
                "custom_questions": job.custom_questions or [],
                "work_location_type": job.work_location_type,
                "application_deadline": job.application_deadline,
                "offers_visa_sponsorship": normalized_requirements.get("offers_visa_sponsorship"),
            }

            # ── Score ─────────────────────────────────────────────────────
            total_score, score_breakdown = calculate_deterministic_score(
                candidate_data, job_config,
            )

            # ── Knockout ──────────────────────────────────────────────────
            knockout_flags = evaluate_knockout_filters(
                candidate_data, job_config,
            )
            has_hard_knockout = any(
                f["severity"] == "hard" for f in knockout_flags
            )
            if has_hard_knockout:
                total_score = 0

            # ── Signals & bucket ──────────────────────────────────────────
            candidate_signals = generate_candidate_signals(candidate_data)
            bucket = assign_bucket(total_score, has_hard_knockout)
            candidate_status = bucket_to_status(bucket, has_hard_knockout)

            # ── Summary ───────────────────────────────────────────────────
            matched = score_breakdown["skills"].get("matched_required", [])
            missing = score_breakdown["skills"].get("missing_required", [])
            candidate_summary = (
                f"Score {total_score}/100. "
                f"Experience {score_breakdown['experience']['total']}/25, "
                f"Skills {score_breakdown['skills']['total']}/35 "
                f"({len(matched)} matched, {len(missing)} missing), "
                f"Education {score_breakdown['education']['total']}/15, "
                f"Role fit {score_breakdown['role_level']['total']}/10, "
                f"Application {score_breakdown['application_quality']['total']}/15."
            )
            if has_hard_knockout:
                reasons = "; ".join(
                    f["reason"] for f in knockout_flags if f["severity"] == "hard"
                )
                candidate_summary = f"Knockout: {reasons}. {candidate_summary}"

            applicant = models.Applicant(
                job_id=job_id,
                company_id=company_id,
                name=candidate_data.get("name", submitted_name or "Unknown"),
                email=candidate_data.get("email", submitted_email),
                phone=candidate_data.get("phone", submitted_phone or ""),
                resume_text=resume_text[:10000],
                resume_pdf=pdf_bytes,
                years_experience=max(0, int(round(float(candidate_data.get("total_years_experience", 0) or 0.0)))),
                skills=candidate_data.get("skills_with_years", {}),
                match_score=total_score,
                summary=candidate_summary,
                status=candidate_status,
                breakdown=score_breakdown,
                cover_letter=cover_letter,
                linkedin_url=linkedin_url,
                portfolio_url=portfolio_url,
                custom_answers=custom_answers,
                # Enriched extraction fields
                skills_detailed=candidate_data.get("skills_detailed"),
                extracted_jobs=candidate_data.get("jobs"),
                extracted_education=candidate_data.get("education"),
                has_measurable_impact=candidate_data.get("has_measurable_impact"),
                has_contact_info=candidate_data.get("has_contact_info"),
                has_clear_job_titles=candidate_data.get("has_clear_job_titles"),
                employment_gaps=candidate_data.get("employment_gaps"),
                average_tenure_years=candidate_data.get("average_tenure_years"),
                extractable_text=candidate_data.get("extractable_text", True),
                cover_letter_analysis=candidate_data.get("cover_letter_analysis"),
                custom_answer_analysis=candidate_data.get("custom_answer_analysis"),
                # Score fields
                score_breakdown=score_breakdown,
                knockout_flags=knockout_flags,
                candidate_signals=candidate_signals,
            )
            db.add(applicant)
            db.flush()

            db.query(models.Job).filter(
                models.Job.id == job_id,
                models.Job.company_id == company_id,
            ).update(
                {"application_count": func.coalesce(models.Job.application_count, 0) + 1}
            )

            db.commit()

        except IntegrityError as e:
            db.rollback()
            if "uq_applicants_job_email" not in str(e) and "UNIQUE constraint failed: applicants.job_id, applicants.email" not in str(e):
                raise
        finally:
            try:
                aggregate_job_results.delay(job_id, company_id)
            except Exception:
                pass


@celery_app.task(name="extract_jd_requirements_task")
def extract_jd_requirements_task(job_id: int, company_id: int, job_description: str):
    """Extract and persist JD requirements asynchronously for newly created jobs."""
    requirements = asyncio.run(extract_jd_requirements(job_description or ""))
    if not requirements:
        return

    with SessionLocal() as db:
        job = db.query(models.Job).filter(
            models.Job.id == job_id,
            models.Job.company_id == company_id,
        ).first()
        if not job:
            return
        job.jd_requirements = requirements
        db.commit()
