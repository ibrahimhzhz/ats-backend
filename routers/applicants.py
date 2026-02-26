from fastapi import APIRouter, UploadFile, File, Depends, Form, HTTPException, status, Response
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from services.pdf_parser import extract_text_from_pdf
from services.ai_engine import extract_candidate_facts, calculate_deterministic_score
from services.auth import get_current_user
from typing import Optional
import re
from urllib.parse import quote

router = APIRouter(prefix="/applicants", tags=["Applicants"])

@router.post("/apply/{job_id}")
async def apply_for_job(
    job_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Single-resume apply endpoint.
    Mirrors the bulk pipeline: dedup → extract → knockout → deterministic score.
    """
    # Stage 0: Job lookup
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.is_active:
        raise HTTPException(status_code=400, detail="This job posting is no longer active")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF resumes are accepted")

    # Stage 0b: PDF parse
    file_content = await file.read()
    if len(file_content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Resume file too large (max 10MB)")

    text = extract_text_from_pdf(file_content)
    if len(text) < 50:
        raise HTTPException(status_code=400, detail="Could not extract text from PDF")

    # ── Stage 1: Fast deduplication ───────────────────────────────────────────
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
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
            raise HTTPException(
                status_code=409,
                detail="A resume with this email has already been submitted for this job.",
            )

    # ── Stage 2: Deep fact extraction (single AI call) ─────────────────────────
    candidate_data = await extract_candidate_facts(text, job.jd_requirements)

    total_years_experience: float = candidate_data["total_years_experience"]
    skills_with_years: dict = candidate_data["skills_with_years"]
    required_skills: list = job.required_skills or []

    # ── Stage 3: Strict knockouts ─────────────────────────────────────────────
    knocked_out = False
    knockout_reason = ""

    if total_years_experience < (job.min_experience - 0.5):
        knocked_out = True
        knockout_reason = (
            f"Insufficient experience: {total_years_experience:.1f} yrs "
            f"(required ≥ {job.min_experience - 0.5:.1f})"
        )

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
        final_score = 0
        assessment_status = "rejected"
        summary = f"Rejected at screening: {knockout_reason}"
    else:
        # ── Stage 4: Deterministic Python scoring ─────────────────────────────
        result = calculate_deterministic_score(
            candidate=candidate_data,
            required_skills=required_skills,
            min_experience=float(job.min_experience),
            job_title=job.title or "",
            raw_resume_text=text,
        )
        final_score = result["final_score"]
        assessment_status = result["status"]
        summary = result["summary"]

    # ── Stage 5: Persist ──────────────────────────────────────────────────────
    new_applicant = models.Applicant(
        job_id=job_id,
        company_id=job.company_id,
        name=candidate_data.get("name", "Unknown"),
        email=candidate_data.get("email", pre_scan_email or "N/A"),
        phone=candidate_data.get("phone", ""),
        years_experience=int(total_years_experience),
        skills=skills_with_years,
        resume_text=text[:10000],
        resume_pdf=file_content,  # Store original PDF for download
        match_score=final_score,
        summary=summary,
        status=assessment_status,
        breakdown=result["breakdown"] if not knocked_out else None,
    )
    db.add(new_applicant)
    db.commit()
    db.refresh(new_applicant)

    return {"message": "Application received", "score": final_score, "status": assessment_status}


@router.get("/", response_model=list[schemas.ApplicantResponse])
def get_applicants(
    job_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    List all applicants for the authenticated user's company.
    Enforces strict tenant isolation - users only see their company's applicants.
    
    Optional filters:
    - job_id: Filter by specific job
    - status_filter: Filter by status (new, shortlisted, review, rejected, etc.)
    """
    # Base query with tenant isolation
    query = db.query(models.Applicant).filter(
        models.Applicant.company_id == current_user.company_id
    )
    
    # Apply optional filters
    if job_id:
        # Verify the job belongs to the user's company
        job = db.query(models.Job).filter(
            models.Job.id == job_id,
            models.Job.company_id == current_user.company_id
        ).first()
        if not job:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view applicants for this job"
            )
        query = query.filter(models.Applicant.job_id == job_id)
    
    if status_filter:
        query = query.filter(models.Applicant.status == status_filter)
    
    # Order by match score descending (best candidates first)
    applicants = query.order_by(models.Applicant.match_score.desc()).all()
    
    return applicants


@router.get("/{applicant_id}", response_model=schemas.ApplicantDetailResponse)
def get_applicant(
    applicant_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Get detailed information about a specific applicant.
    Enforces tenant isolation - returns 403 if applicant belongs to another company.
    """
    applicant = db.query(models.Applicant).filter(
        models.Applicant.id == applicant_id,
        models.Applicant.company_id == current_user.company_id
    ).first()
    
    if not applicant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Applicant not found or not authorized"
        )
    
    return applicant


@router.put("/{applicant_id}/status", response_model=schemas.ApplicantResponse)
def update_applicant_status(
    applicant_id: int,
    status_update: schemas.ApplicantStatusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Update an applicant's status in the hiring workflow.
    Valid statuses: new, rejected, shortlisted, review, interviewed, hired
    Enforces tenant isolation.
    """
    # Verify applicant exists and belongs to user's company
    applicant = db.query(models.Applicant).filter(
        models.Applicant.id == applicant_id,
        models.Applicant.company_id == current_user.company_id
    ).first()
    
    if not applicant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Applicant not found or not authorized"
        )
    
    # Validate status value
    valid_statuses = ["new", "rejected", "shortlisted", "review", "interviewed", "hired"]
    if status_update.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
    
    # Update status
    applicant.status = status_update.status
    db.commit()
    db.refresh(applicant)
    
    return applicant


@router.delete("/{applicant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_applicant(
    applicant_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Delete an applicant. Only admins in the same company are allowed.
    Enforces tenant isolation.
    """
    # Only admins can delete applicants
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete applicants"
        )
    
    # Verify applicant exists and belongs to user's company
    applicant = db.query(models.Applicant).filter(
        models.Applicant.id == applicant_id,
        models.Applicant.company_id == current_user.company_id
    ).first()
    
    if not applicant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Applicant not found or not authorized"
        )
    
    db.delete(applicant)
    db.commit()


@router.put("/bulk/status", response_model=dict)
def bulk_update_applicant_status(
    bulk_update: schemas.BulkApplicantStatusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Bulk update the status of multiple applicants.
    Enforces tenant isolation - only updates applicants belonging to user's company.
    Returns count of updated applicants.
    """
    # Validate status value
    valid_statuses = ["new", "rejected", "shortlisted", "review", "interviewed", "hired"]
    if bulk_update.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
    
    # Fetch applicants that belong to user's company
    applicants = db.query(models.Applicant).filter(
        models.Applicant.id.in_(bulk_update.applicant_ids),
        models.Applicant.company_id == current_user.company_id
    ).all()
    
    if not applicants:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No applicants found or not authorized"
        )
    
    # Update all fetched applicants
    updated_count = 0
    for applicant in applicants:
        applicant.status = bulk_update.status
        updated_count += 1
    
    db.commit()
    
    return {
        "message": f"Successfully updated {updated_count} applicants",
        "updated_count": updated_count,
        "requested_count": len(bulk_update.applicant_ids),
        "new_status": bulk_update.status
    }


@router.get("/{applicant_id}/download-resume")
def download_resume(
    applicant_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Download the original resume PDF for an applicant.
    Enforces tenant isolation - only users from the same company can download.
    """
    # Verify applicant exists and belongs to user's company
    applicant = db.query(models.Applicant).filter(
        models.Applicant.id == applicant_id,
        models.Applicant.company_id == current_user.company_id
    ).first()
    
    if not applicant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Applicant not found or not authorized"
        )
    
    if not applicant.resume_pdf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume PDF not available for this applicant"
        )
    
    # Generate filename
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", (applicant.name or "resume")).strip("._") or "resume"
    filename = quote(f"{safe_name}_resume.pdf")
    
    # Return PDF with proper headers
    return Response(
        content=applicant.resume_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}"
        }
    )