"""
Public-facing unauthenticated endpoints for the Careers Portal.

These endpoints do NOT require authentication and are accessible to candidates
applying to jobs through public links.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from typing import Optional
from collections import defaultdict, deque
import threading
import time
import os
import uuid
import tempfile
import shutil
import models
import schemas
from database import get_db
from services.ai_engine import is_ai_available
from services.tasks import process_public_resume
import json

router = APIRouter(prefix="/api/public", tags=["public"])
TEMP_RESUME_DIR = os.getenv("ATS_RESUME_TMP_DIR", os.path.join(tempfile.gettempdir(), "ats_resumes"))

PUBLIC_APPLY_WINDOW_SECONDS = 60
PUBLIC_APPLY_LIMIT_PER_IP = 20
PUBLIC_APPLY_LIMIT_PER_EMAIL = 5
_public_apply_rate_lock = threading.Lock()
_public_apply_ip_windows: dict[str, deque[float]] = defaultdict(deque)
_public_apply_email_windows: dict[str, deque[float]] = defaultdict(deque)


def _is_rate_limited(bucket: dict[str, deque[float]], key: str, limit: int, window_seconds: int) -> bool:
    now = time.time()
    with _public_apply_rate_lock:
        samples = bucket[key]
        while samples and (now - samples[0]) > window_seconds:
            samples.popleft()
        if len(samples) >= limit:
            return True
        samples.append(now)
        return False


# ==============================================================================
# PUBLIC JOB VIEW ENDPOINT
# ==============================================================================

@router.get("/job/{job_id}", response_model=schemas.PublicJobResponse)
def get_public_job(job_id: int, db: Session = Depends(get_db)):
    """
    Fetch public job details and increment view counter.
    
    Returns 404 if job is not found or inactive.
    No authentication required.
    """
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if not job.is_active:
        raise HTTPException(status_code=404, detail="This job posting is no longer active")
    
    # Increment view counter
    job.views = (job.views or 0) + 1
    db.commit()
    
    return job


@router.post("/apply/{job_id}")
async def submit_public_application(
    job_id: int,
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(None),
    linkedin_url: Optional[str] = Form(None),
    portfolio_url: Optional[str] = Form(None),
    custom_answers_json: Optional[str] = Form(None),
    resume: UploadFile = File(...),
    website_url_catch: Optional[str] = Form(None),  # Honeypot field for bot detection
    db: Session = Depends(get_db)
):
    """
    Submit a public job application.
    
    Accepts multipart/form-data with:
    - Candidate info (name, email, phone)
    - Optional fields (linkedin_url, portfolio_url)
    - Custom answers (JSON string)
    - Resume PDF file
    - Honeypot field (website_url_catch) for spam protection
    
    Returns 200 OK immediately and processes in background.
    No authentication required.
    """
    
    # Spam Protection: Honeypot check
    # If the hidden field is filled, silently discard (bots typically fill all fields)
    if website_url_catch and website_url_catch.strip():
        print(f"🤖 Bot detected via honeypot: {email}")
        return {"status": "success", "message": "Application received"}

    if not is_ai_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Application processing is temporarily unavailable. "
                "Please try again shortly."
            ),
        )

    client_ip = request.client.host if request.client else "unknown"
    normalized_email = (email or "").strip().lower()

    if _is_rate_limited(_public_apply_ip_windows, client_ip, PUBLIC_APPLY_LIMIT_PER_IP, PUBLIC_APPLY_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="Too many submissions from this IP. Please retry shortly.")
    if normalized_email and _is_rate_limited(_public_apply_email_windows, normalized_email, PUBLIC_APPLY_LIMIT_PER_EMAIL, PUBLIC_APPLY_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="Too many submissions for this email. Please retry shortly.")
    
    # Fetch job and validate
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if not job.is_active:
        raise HTTPException(status_code=400, detail="This job posting is no longer active")
    
    # Validate file type
    if not resume.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF resumes are accepted")
    
    if not resume.size and not resume.filename:
        raise HTTPException(status_code=400, detail="Resume file is required")

    if resume.size and resume.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Resume file too large (max 10MB)")
    
    # Parse custom answers JSON if provided
    custom_answers = None
    if custom_answers_json:
        try:
            custom_answers = json.loads(custom_answers_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid custom_answers_json payload")

    duplicate = (
        db.query(models.Applicant)
        .filter(models.Applicant.job_id == job.id, models.Applicant.email == email)
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="An application with this email already exists for this job")

    os.makedirs(TEMP_RESUME_DIR, exist_ok=True)
    extension = os.path.splitext(resume.filename or "resume.pdf")[1] or ".pdf"
    saved_path = os.path.join(TEMP_RESUME_DIR, f"{uuid.uuid4()}{extension}")

    with open(saved_path, "wb") as out_file:
        shutil.copyfileobj(resume.file, out_file)

    if os.path.getsize(saved_path) > 10 * 1024 * 1024:
        os.remove(saved_path)
        raise HTTPException(status_code=400, detail="Resume file too large (max 10MB)")

    process_public_resume.delay(
        file_path=saved_path,
        job_id=job.id,
        company_id=job.company_id,
        submitted_name=name,
        submitted_email=normalized_email,
        submitted_phone=phone,
        linkedin_url=linkedin_url,
        portfolio_url=portfolio_url,
        custom_answers=custom_answers,
    )
    
    return {
        "status": "success",
        "message": "Application received and being processed"
    }
