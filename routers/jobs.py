from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from database import get_db
import models, schemas
from services.auth import get_current_user
from services.tasks import extract_jd_requirements_task

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("/", response_model=schemas.JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job: schemas.JobCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Create a new job posting with Level 1 JD Requirement Extraction.
    The job is automatically associated with the authenticated user's company —
    tenants cannot create jobs on behalf of another company.
    
    The system will automatically extract verbatim requirement sentences from the
    job description using AI (Level 1 of the Grounded JD Matching System).
    """
    new_job = models.Job(
        **job.model_dump(),
        company_id=current_user.company_id,  # ← injected from JWT, never from client
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    extract_jd_requirements_task.delay(new_job.id, current_user.company_id, new_job.description or "")
    
    return new_job


@router.get("/", response_model=list[schemas.JobResponse])
def get_jobs(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    List all jobs belonging to the authenticated user's company.
    Data from other tenants is never exposed.
    """
    return (
        db.query(models.Job)
        .filter(models.Job.company_id == current_user.company_id)
        .all()
    )


@router.get("/{job_id}", response_model=schemas.JobResponse)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Fetch a single job, enforcing tenant ownership."""
    job = (
        db.query(models.Job)
        .filter(
            models.Job.id == job_id,
            models.Job.company_id == current_user.company_id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Delete a job. Only admins in the same company are allowed."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete jobs.",
        )
    job = (
        db.query(models.Job)
        .filter(
            models.Job.id == job_id,
            models.Job.company_id == current_user.company_id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    db.delete(job)
    db.commit()


@router.put("/{job_id}", response_model=schemas.JobResponse)
def update_job(
    job_id: int,
    job_update: schemas.JobUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Update a job's details.
    Only users in the same company can update their jobs.
    """
    job = (
        db.query(models.Job)
        .filter(
            models.Job.id == job_id,
            models.Job.company_id == current_user.company_id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    # Update only provided fields
    update_data = job_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(job, field, value)

    db.commit()
    db.refresh(job)
    return job


@router.put("/{job_id}/form-config", response_model=schemas.JobResponse)
def update_job_form_config(
    job_id: int,
    form_config: schemas.JobFormConfig,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Update the public application form configuration for a job.
    
    Example form_config:
    {
        "require_linkedin": true,
        "require_portfolio": false,
        "custom_questions": ["Why do you want to work here?", "What's your biggest achievement?"]
    }
    """
    job = (
        db.query(models.Job)
        .filter(
            models.Job.id == job_id,
            models.Job.company_id == current_user.company_id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    job.form_config = form_config.model_dump(exclude_none=True)
    db.commit()
    db.refresh(job)
    return job


@router.patch("/{job_id}/status", response_model=schemas.JobResponse)
def toggle_job_status(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Toggle job active/inactive status. Only admins can modify status."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can change job status."
        )
    
    job = (
        db.query(models.Job)
        .filter(
            models.Job.id == job_id,
            models.Job.company_id == current_user.company_id,
        )
        .first()
    )
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found."
        )
    
    # Toggle the status
    job.is_active = not job.is_active
    db.commit()
    db.refresh(job)
    return job


@router.get("/{job_id}/stats", response_model=schemas.JobStatsResponse)
def get_job_statistics(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Get statistics for a specific job with tenant isolation."""
    # Verify job exists and belongs to user's company
    job = (
        db.query(models.Job)
        .filter(
            models.Job.id == job_id,
            models.Job.company_id == current_user.company_id,
        )
        .first()
    )
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found."
        )
    
    # Calculate statistics
    applicants = db.query(models.Applicant).filter(
        models.Applicant.job_id == job_id
    ).all()
    
    total_applicants = len(applicants)
    shortlisted = sum(1 for a in applicants if a.status == "shortlisted")
    under_review = sum(1 for a in applicants if a.status == "review")
    rejected = sum(1 for a in applicants if a.status == "rejected")
    interviewed = sum(1 for a in applicants if a.status == "interviewed")
    hired = sum(1 for a in applicants if a.status == "hired")
    
    average_score = (
        sum(a.match_score for a in applicants) / total_applicants
        if total_applicants > 0
        else 0.0
    )
    
    return schemas.JobStatsResponse(
        job_id=job_id,
        job_title=job.title,
        total_applicants=total_applicants,
        shortlisted=shortlisted,
        under_review=under_review,
        rejected=rejected,
        interviewed=interviewed,
        hired=hired,
        average_score=round(average_score, 1)
    )


@router.get("/dashboard/stats", response_model=schemas.DashboardStatsResponse)
def get_dashboard_statistics(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Get overall dashboard statistics for the authenticated user's company."""
    # Job statistics
    jobs = db.query(models.Job).filter(
        models.Job.company_id == current_user.company_id
    ).all()
    
    total_jobs = len(jobs)
    active_jobs = sum(1 for j in jobs if j.is_active)
    
    # Applicant statistics
    applicants = db.query(models.Applicant).filter(
        models.Applicant.company_id == current_user.company_id
    ).all()
    
    total_applicants = len(applicants)
    shortlisted_applicants = sum(1 for a in applicants if a.status == "shortlisted")
    pending_review = sum(1 for a in applicants if a.status == "review")
    
    # Recent applicants (top 10 by score)
    recent_applicants = (
        db.query(models.Applicant)
        .filter(models.Applicant.company_id == current_user.company_id)
        .order_by(models.Applicant.match_score.desc())
        .limit(10)
        .all()
    )
    
    return schemas.DashboardStatsResponse(
        total_jobs=total_jobs,
        active_jobs=active_jobs,
        total_applicants=total_applicants,
        shortlisted_applicants=shortlisted_applicants,
        pending_review=pending_review,
        recent_applicants=recent_applicants
    )