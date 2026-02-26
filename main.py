from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base, SessionLocal, run_migrations
from routers import jobs, applicants, auth as auth_router
from routers import public as public_router  # Public careers portal
from services.pdf_parser import extract_text_from_pdf
from services.ai_engine import (
    extract_candidate_facts,
    calculate_deterministic_score,
    is_ai_available,
    get_ai_unavailable_reason,
    AIServiceUnavailableError,
)
from services.job_tracker import job_tracker, JobStatus
from services.auth import get_current_user
from middleware import SecurityLoggingMiddleware, SecurityHeadersMiddleware
import models
import zipfile
import io
import os
import asyncio
import re
import uuid
import tempfile
import shutil
from typing import Dict, Any, List
from services.tasks import process_resume

# Create Tables + run safe schema migrations
Base.metadata.create_all(bind=engine)
run_migrations()

app = FastAPI(
    title="AI Recruiter ATS",
    description="Multi-tenant ATS with AI-powered resume screening",
    version="1.0.0"
)

JOB_TRACKER_CLEANUP_INTERVAL_SECONDS = int(os.getenv("JOB_TRACKER_CLEANUP_INTERVAL_SECONDS", "1800"))
JOB_TRACKER_MAX_AGE_HOURS = int(os.getenv("JOB_TRACKER_MAX_AGE_HOURS", "24"))
_job_tracker_cleanup_task: asyncio.Task | None = None
TEMP_RESUME_DIR = os.getenv("ATS_RESUME_TMP_DIR", os.path.join(tempfile.gettempdir(), "ats_resumes"))


async def _job_tracker_cleanup_loop():
    while True:
        await asyncio.sleep(JOB_TRACKER_CLEANUP_INTERVAL_SECONDS)
        removed = job_tracker.cleanup_old_jobs(max_age_hours=JOB_TRACKER_MAX_AGE_HOURS)
        if removed:
            print(f"🧹 Job tracker cleanup removed {removed} stale jobs")


@app.on_event("startup")
async def _startup_background_tasks():
    global _job_tracker_cleanup_task
    if _job_tracker_cleanup_task is None:
        _job_tracker_cleanup_task = asyncio.create_task(_job_tracker_cleanup_loop())


@app.on_event("shutdown")
async def _shutdown_background_tasks():
    global _job_tracker_cleanup_task
    if _job_tracker_cleanup_task is not None:
        _job_tracker_cleanup_task.cancel()
        try:
            await _job_tracker_cleanup_task
        except asyncio.CancelledError:
            pass
        _job_tracker_cleanup_task = None

# Add security middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SecurityLoggingMiddleware)

# CORS configuration (adjust origins as needed for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],  # Add your frontend URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static assets and templates — all served from the single frontend/ folder
# /static/js/auth.js, /static/css/... etc. map to frontend/static/...
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
templates = Jinja2Templates(directory="frontend")

# Include Routers
app.include_router(public_router.router)  # Public careers portal (must be first, no auth)
app.include_router(auth_router.router)
app.include_router(jobs.router)
app.include_router(applicants.router)

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/apply/{job_id}", response_class=HTMLResponse)
def apply_page(request: Request, job_id: int):
    """Public careers portal application page."""
    return templates.TemplateResponse("apply.html", {"request": request, "job_id": job_id})


@app.get("/api/health")
def health():
    ai_ready = is_ai_available()
    return {
        "status": "ok",
        "ai_ready": ai_ready,
        "ai_reason": None if ai_ready else get_ai_unavailable_reason(),
    }


async def process_resumes_background(
    tracking_job_id: str,
    db_job_id: int,
    company_id: int,
    job_title: str,
    zip_content: bytes,
    job_description: str,
    min_experience: float,
    required_skills: List[str],
):
    """
    Enterprise resume screening pipeline.

    Stage 1: Fast deduplication     — regex email + DB lookup (free, no AI)
    Stage 2: Deep fact extraction   — single Gemini call, strict JSON schema
    Stage 3: Strict knockouts       — rule-based, 50% skill floor (free)
    Stage 4: Deterministic scoring  — pure Python, 100% repeatable
    Stage 5: Persist + summarise    — Python-generated summary, no LLM
    """
    db = SessionLocal()

    try:
        if not is_ai_available():
            raise AIServiceUnavailableError(
                get_ai_unavailable_reason() or "AI extraction service unavailable"
            )

        job_tracker.update_status(tracking_job_id, JobStatus.PROCESSING)

        # Load job object for JD requirements
        db_job = db.query(models.Job).filter(models.Job.id == db_job_id).first()
        if not db_job:
            raise Exception(f"Job {db_job_id} not found")

        # Mark DB job as processing
        db.query(models.Job).filter(models.Job.id == db_job_id).update(
            {"status": "processing", "processed_resumes": 0}
        )
        db.commit()

        zip_file = zipfile.ZipFile(io.BytesIO(zip_content))
        candidates: List[Dict[str, Any]] = []

        stats = {
            "total_processed": 0,
            "duplicates_skipped": 0,
            "knocked_out": 0,
            "scored": 0,
            "shortlisted": 0,
            "review": 0,
            "rejected": 0,
        }

        pdf_files = [f for f in zip_file.namelist() if f.lower().endswith(".pdf")]
        total_files = len(pdf_files)

        print(f"🚀 New Pipeline | {total_files} resumes | '{job_title}' | "
              f"{min_experience} yrs | {len(required_skills)} skills")

        for idx, filename in enumerate(pdf_files):
            try:
                pdf_bytes = zip_file.read(filename)
                resume_text = extract_text_from_pdf(pdf_bytes)

                if len(resume_text) < 50:
                    print(f"⚠️  Skipping {filename} — insufficient text")
                    continue

                # ════════════════════════════════════════════════════════
                # STAGE 1: FAST DEDUPLICATION  (before any AI call)
                # ════════════════════════════════════════════════════════
                email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", resume_text)
                pre_scan_email = email_match.group(0).lower() if email_match else None

                if pre_scan_email:
                    duplicate = (
                        db.query(models.Applicant)
                        .filter(
                            models.Applicant.job_id == db_job_id,
                            models.Applicant.email == pre_scan_email,
                        )
                        .first()
                    )
                    if duplicate:
                        print(f"⏭️  DUPLICATE: {filename} ({pre_scan_email}) — skipped")
                        stats["duplicates_skipped"] += 1
                        continue

                # ════════════════════════════════════════════════════════
                # STAGE 2: DEEP FACT EXTRACTION  (single AI call)
                # Level 2: Pass JD requirements if available for grounded verification
                # ════════════════════════════════════════════════════════
                job_jd_requirements = db_job.jd_requirements if db_job else None
                candidate_data = await extract_candidate_facts(resume_text, job_jd_requirements)

                total_years_experience: float = candidate_data["total_years_experience"]
                skills_with_years: Dict[str, float] = candidate_data["skills_with_years"]

                # ════════════════════════════════════════════════════════
                # STAGE 3: STRICT KNOCKOUTS  (rule-based, no AI)
                # ════════════════════════════════════════════════════════
                knocked_out = False
                knockout_reason = ""

                # Knockout 1 — Experience floor (0.5-year buffer)
                if total_years_experience < (min_experience - 0.5):
                    knocked_out = True
                    knockout_reason = (
                        f"Insufficient experience: {total_years_experience:.1f} yrs "
                        f"(required ≥ {min_experience - 0.5:.1f})"
                    )

                # Knockout 2 — Skill floor (must match ≥ 50% of required skills)
                if not knocked_out and required_skills:
                    candidate_skill_keys = {k.lower() for k in skills_with_years}
                    required_lower = [s.lower() for s in required_skills]
                    matched_ko = [
                        s for s in required_lower
                        if any(s in k or k in s for k in candidate_skill_keys)
                    ]
                    coverage = len(matched_ko) / len(required_lower)
                    if coverage < 0.50:
                        knocked_out = True
                        knockout_reason = (
                            f"Skill floor not met: {len(matched_ko)}/{len(required_lower)} "
                            f"required skills present ({coverage:.0%})"
                        )

                if knocked_out:
                    print(f"❌ KNOCKOUT: {filename} — {knockout_reason}")
                    final_score = 0
                    assessment_status = "rejected"
                    summary = f"Rejected at screening: {knockout_reason}"
                    stats["knocked_out"] += 1
                    stats["rejected"] += 1

                else:
                    # ════════════════════════════════════════════════════
                    # STAGE 4: DETERMINISTIC PYTHON SCORING
                    # Level 3: Anti-hallucination verification with raw resume text
                    # ════════════════════════════════════════════════════
                    result = calculate_deterministic_score(
                        candidate=candidate_data,
                        required_skills=required_skills,
                        min_experience=min_experience,
                        job_title=job_title,
                        raw_resume_text=resume_text,
                    )
                    final_score = result["final_score"]
                    assessment_status = result["status"]
                    summary = result["summary"]
                    stats["scored"] += 1
                    stats[assessment_status] += 1
                    print(
                        f"⚖️  SCORED: {filename} — {final_score}/100 "
                        f"({assessment_status.upper()}) | "
                        f"Skill:{result['breakdown']['skill_depth']:.0f} "
                        f"JD:{result['breakdown']['jd_requirements']:.0f} "
                        f"Exp:{result['breakdown']['experience']:.0f} "
                        f"Impact:{result['breakdown']['impact']:.0f}"
                    )

                # ════════════════════════════════════════════════════════
                # STAGE 5: DATABASE PERSISTENCE
                # ════════════════════════════════════════════════════════
                db_applicant = models.Applicant(
                    job_id=db_job_id,
                    company_id=company_id,
                    name=candidate_data.get("name", "Unknown"),
                    email=candidate_data.get("email", pre_scan_email or "N/A"),
                    phone=candidate_data.get("phone", ""),
                    resume_text=resume_text[:10000],
                    resume_pdf=pdf_bytes,  # Store original PDF for download
                    years_experience=int(total_years_experience),
                    skills=skills_with_years,   # dict stored as JSON
                    match_score=final_score,
                    summary=summary,
                    status=assessment_status,
                    breakdown=result["breakdown"] if not knocked_out else None,
                )
                db.add(db_applicant)
                db.commit()
                db.refresh(db_applicant)

                candidates.append({
                    "id": db_applicant.id,
                    "filename": filename,
                    "name": db_applicant.name,
                    "email": db_applicant.email,
                    "years_experience": total_years_experience,
                    "skills": skills_with_years,
                    "match_score": final_score,
                    "summary": summary,
                    "status": assessment_status,
                    "breakdown": result["breakdown"] if not knocked_out else None,
                })

                stats["total_processed"] += 1
                print(f"💾 SAVED: {idx + 1}/{total_files} — {filename}")

            except Exception as e:
                print(f"❌ Error processing {filename}: {str(e)}")
                db.rollback()   # keep the session clean after any mid-loop error
            finally:
                job_tracker.update_progress(tracking_job_id, idx + 1)
                db.query(models.Job).filter(models.Job.id == db_job_id).update(
                    {"processed_resumes": idx + 1}
                )
                db.commit()

        # Sort by score descending
        candidates.sort(key=lambda x: x["match_score"], reverse=True)
        if candidates:
            top_10_percent = max(1, len(candidates) // 10)
            shortlisted = candidates[:top_10_percent]  # EXACT TOP N
        else:
            shortlisted = []

        stats["shortlisted"] = len(shortlisted)
        stats["review"] = sum(1 for c in candidates if c["status"] == "review")
        stats["rejected"] = sum(1 for c in candidates if c["status"] == "rejected")

        results = {
            "total_processed": stats["total_processed"],
            "duplicates_skipped": stats["duplicates_skipped"],
            "knocked_out": stats["knocked_out"],
            "scored": stats["scored"],
            "shortlisted_count": stats["shortlisted"],
            "review_count": stats["review"],
            "rejected_count": stats["rejected"],
            "shortlisted": shortlisted,
            "all_candidates": candidates,
            "criteria": {
                "job_title": job_title,
                "min_experience": min_experience,
                "required_skills": required_skills,
            },
        }
        job_tracker.set_results(tracking_job_id, results)

        # Persist final results + status to DB
        db.query(models.Job).filter(models.Job.id == db_job_id).update(
            {
                "status": "completed",
                "results": results,
                "total_resumes": total_files,
                "processed_resumes": stats["total_processed"],
            }
        )
        db.commit()

        print(f"🎉 Pipeline Complete!")
        print(
            f"📊 {stats['total_processed']} processed | "
            f"{stats['duplicates_skipped']} duplicates | "
            f"{stats['knocked_out']} knocked out | "
            f"{stats['scored']} scored"
        )
        print(
            f"📊 {stats['shortlisted']} shortlisted | "
            f"{stats['review']} review | "
            f"{stats['rejected']} rejected"
        )

    except Exception as e:
        print(f"❌ Job {tracking_job_id} failed: {str(e)}")
        job_tracker.update_status(tracking_job_id, JobStatus.FAILED, error=str(e))
        try:
            db.query(models.Job).filter(models.Job.id == db_job_id).update({"status": "failed"})
            db.commit()
        except Exception:
            pass
    finally:
        db.close()



@app.post("/api/bulk-screen")
async def bulk_screen_resumes(
    resumes_zip: UploadFile = File(...),
    job_title: str = Form(default=""),
    job_description: str = Form(...),
    min_experience: float = Form(...),
    required_skills: str = Form(...),
    current_user: models.User = Depends(get_current_user),
):
    """
    Upload a ZIP of resume PDFs for bulk screening.
    Returns a tracking job_id for polling progress.
    """
    try:
        if not is_ai_available():
            raise HTTPException(
                status_code=503,
                detail=(
                    "AI extraction service is currently unavailable. "
                    "Please retry after AI connectivity is restored."
                ),
            )

        os.makedirs(TEMP_RESUME_DIR, exist_ok=True)

        zip_saved_path = os.path.join(TEMP_RESUME_DIR, f"{uuid.uuid4()}.zip")
        with open(zip_saved_path, "wb") as out_file:
            shutil.copyfileobj(resumes_zip.file, out_file)

        try:
            with zipfile.ZipFile(zip_saved_path) as zip_file:
                pdf_files = [f for f in zip_file.namelist() if f.lower().endswith(".pdf")]
                if not pdf_files:
                    raise HTTPException(status_code=400, detail="No PDF files found in ZIP")
                total_resumes = len(pdf_files)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP file")

        skills_list = [s.strip() for s in required_skills.split(",") if s.strip()]
        normalized_min_experience = int(min_experience)
        clean_title = job_title.strip() or f"Screening — {total_resumes} resumes"

        db = SessionLocal()
        try:
            db_job = models.Job(
                title=clean_title,
                description=job_description,
                min_experience=normalized_min_experience,
                required_skills=skills_list,
                is_active=True,
                company_id=current_user.company_id,
            )
            db.add(db_job)
            db.commit()
            db.refresh(db_job)
            db_job_id = db_job.id
        finally:
            db.close()

        tracking_job_id = str(uuid.uuid4())

        # Link tracking ID back to the DB job row immediately
        db2 = SessionLocal()
        try:
            db2.query(models.Job).filter(models.Job.id == db_job_id).update(
                {
                    "tracking_id": tracking_job_id,
                    "total_resumes": total_resumes,
                    "processed_resumes": 0,
                    "status": "processing",
                }
            )
            db2.commit()
        finally:
            db2.close()

        try:
            with zipfile.ZipFile(zip_saved_path) as zip_file:
                for member in pdf_files:
                    pdf_bytes = zip_file.read(member)
                    candidate_path = os.path.join(TEMP_RESUME_DIR, f"{uuid.uuid4()}.pdf")
                    with open(candidate_path, "wb") as out_pdf:
                        out_pdf.write(pdf_bytes)
                    process_resume.delay(
                        file_path=candidate_path,
                        job_id=db_job_id,
                        company_id=current_user.company_id,
                    )
        finally:
            if os.path.exists(zip_saved_path):
                os.remove(zip_saved_path)
        
        return JSONResponse({
            "job_id": tracking_job_id,
            "db_job_id": db_job_id,
            "total_resumes": total_resumes,
            "min_experience": normalized_min_experience,
            "required_skills": skills_list,
            "message": "Processing started. Use the job_id to check progress."
        })
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ bulk_screen_resumes failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error while starting bulk screening")


@app.get("/api/job/{job_id}")
def get_job_status(
    job_id: str,
    current_user: models.User = Depends(get_current_user)
):
    """
    Check the status of a bulk processing job.
    SECURED: Enforces tenant isolation - users can only view their company's jobs.
    """
    # Retrieve job with company_id verification
    job = job_tracker.get_job(job_id, company_id=current_user.company_id)

    if job:
        return JSONResponse(job)

    # Server-restart fallback: read persisted state from DB
    db = SessionLocal()
    try:
        db_job = (
            db.query(models.Job)
            .filter(
                models.Job.tracking_id == job_id,
                models.Job.company_id == current_user.company_id,
            )
            .first()
        )
        if not db_job:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to view this job or job not found",
            )
        return JSONResponse({
            "id": db_job.tracking_id,
            "status": db_job.status or "completed",
            "total_resumes": db_job.total_resumes or 0,
            "processed": db_job.processed_resumes if db_job.processed_resumes is not None else (db_job.results or {}).get("total_processed", 0),
            "created_at": db_job.created_at.isoformat() if db_job.created_at else None,
            "results": db_job.results,
            "error": None,
        })
    finally:
        db.close()


@app.get("/api/jobs")
def list_bulk_jobs(
    current_user: models.User = Depends(get_current_user)
):
    """
    List all bulk processing jobs for the authenticated user's company.
    SECURED: Enforces tenant isolation.
    """
    # Primary source: DB (survives server restarts)
    db = SessionLocal()
    try:
        db_jobs = (
            db.query(models.Job)
            .filter(models.Job.company_id == current_user.company_id)
            .order_by(models.Job.created_at.desc())
            .all()
        )
        jobs_list = [
            {
                "id": j.tracking_id,
                "db_job_id": j.id,
                "title": j.title,
                "status": j.status,
                "total_resumes": j.total_resumes,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "results": j.results,
                "company_id": j.company_id,
            }
            for j in db_jobs
            if j.tracking_id  # only rows that were created via bulk-screen
        ]
        return JSONResponse({"jobs": jobs_list, "total": len(jobs_list)})
    finally:
        db.close()