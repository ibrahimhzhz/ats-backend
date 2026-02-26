import asyncio
import os
import re
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import models
from core.celery_app import celery_app
from database import SessionLocal
from services.ai_engine import extract_candidate_facts, calculate_deterministic_score, extract_jd_requirements
from services.pdf_parser import extract_text_from_pdf


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

    candidates.sort(key=lambda x: x.get("match_score") or 0, reverse=True)

    if candidates:
        top_10_percent = max(1, len(candidates) // 10)
        shortlisted = candidates[:top_10_percent]
    else:
        shortlisted = []

    processed_resumes = int(job.processed_resumes or 0)
    total_saved = len(candidates)
    rejected_count = sum(1 for c in candidates if c.get("status") == "rejected")
    review_count = sum(1 for c in candidates if c.get("status") == "review")

    duplicates_or_skipped = max(0, processed_resumes - total_saved)

    return {
        "total_processed": total_saved,
        "duplicates_skipped": duplicates_or_skipped,
        "knocked_out": 0,
        "scored": total_saved,
        "ai_evaluated": total_saved,
        "shortlisted_count": len(shortlisted),
        "review_count": review_count,
        "rejected_count": rejected_count,
        "shortlisted": shortlisted,
        "all_candidates": candidates,
        "criteria": {
            "job_title": job.title,
            "min_experience": job.min_experience,
            "required_skills": job.required_skills or [],
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
def process_resume(file_path: str, job_id: int, company_id: int):
    """Process a single resume PDF from disk and persist applicant scoring results."""
    try:
        with SessionLocal() as db:
            try:
                job = db.query(models.Job).filter(
                    models.Job.id == job_id,
                    models.Job.company_id == company_id,
                ).first()
                if not job:
                    return

                with open(file_path, "rb") as f:
                    pdf_bytes = f.read()

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

                candidate_data: Dict[str, Any] = asyncio.run(
                    extract_candidate_facts(resume_text, job.jd_requirements)
                )

                result = calculate_deterministic_score(
                    candidate=candidate_data,
                    required_skills=job.required_skills or [],
                    min_experience=float(job.min_experience or 0),
                    job_title=job.title or "",
                    raw_resume_text=resume_text,
                )

                applicant = models.Applicant(
                    job_id=job_id,
                    company_id=company_id,
                    name=candidate_data.get("name", "Unknown"),
                    email=candidate_data.get("email", pre_scan_email or "N/A"),
                    phone=candidate_data.get("phone", ""),
                    resume_text=resume_text[:10000],
                    resume_pdf=pdf_bytes,
                    years_experience=int(candidate_data.get("total_years_experience", 0) or 0),
                    skills=candidate_data.get("skills_with_years", {}),
                    match_score=result["final_score"],
                    summary=result["summary"],
                    status=result["status"],
                    breakdown=result.get("breakdown"),
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
    finally:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass


@celery_app.task(name="process_public_resume")
def process_public_resume(
    file_path: str,
    job_id: int,
    company_id: int,
    submitted_name: str,
    submitted_email: str,
    submitted_phone: str | None = None,
    linkedin_url: str | None = None,
    portfolio_url: str | None = None,
    custom_answers: dict | None = None,
):
    """Process a public portal submission and increment application_count on success."""
    try:
        with SessionLocal() as db:
            try:
                job = db.query(models.Job).filter(
                    models.Job.id == job_id,
                    models.Job.company_id == company_id,
                ).first()
                if not job:
                    return

                with open(file_path, "rb") as f:
                    pdf_bytes = f.read()

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

                candidate_data: Dict[str, Any] = asyncio.run(
                    extract_candidate_facts(resume_text, job.jd_requirements)
                )

                if submitted_name and submitted_name.strip():
                    candidate_data["name"] = submitted_name.strip()
                candidate_data["email"] = submitted_email.strip().lower()
                if submitted_phone and submitted_phone.strip():
                    candidate_data["phone"] = submitted_phone.strip()

                result = calculate_deterministic_score(
                    candidate=candidate_data,
                    required_skills=job.required_skills or [],
                    min_experience=float(job.min_experience or 0),
                    job_title=job.title or "",
                    raw_resume_text=resume_text,
                )

                applicant = models.Applicant(
                    job_id=job_id,
                    company_id=company_id,
                    name=candidate_data.get("name", submitted_name or "Unknown"),
                    email=candidate_data.get("email", submitted_email),
                    phone=candidate_data.get("phone", submitted_phone or ""),
                    resume_text=resume_text[:10000],
                    resume_pdf=pdf_bytes,
                    years_experience=int(candidate_data.get("total_years_experience", 0) or 0),
                    skills=candidate_data.get("skills_with_years", {}),
                    match_score=result["final_score"],
                    summary=result["summary"],
                    status=result["status"],
                    breakdown=result.get("breakdown"),
                    linkedin_url=linkedin_url,
                    portfolio_url=portfolio_url,
                    custom_answers=custom_answers,
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
    finally:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
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
