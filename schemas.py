from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Union
from datetime import datetime


# ==============================================================================
# COMPANY SCHEMAS
# ==============================================================================

class CompanyCreate(BaseModel):
    name: str
    subscription_tier: str = "free"

class CompanyResponse(BaseModel):
    id: int
    name: str
    subscription_tier: str
    created_at: datetime

    class Config:
        from_attributes = True


# ==============================================================================
# USER / AUTH SCHEMAS
# ==============================================================================

class UserCreate(BaseModel):
    """Payload to register a new user and (optionally) create their company."""
    email: EmailStr
    password: str
    company_name: str  # Used to create or look up the tenant on registration

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    role: str
    company_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    """JWT response returned on successful login."""
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    """Claims extracted from a decoded JWT — used internally."""
    user_id: Optional[int] = None
    company_id: Optional[int] = None


# ==============================================================================
# JOB SCHEMAS
# ==============================================================================

class JobCreate(BaseModel):
    title: str
    description: str
    min_experience: int
    required_skills: List[str]
    # NOTE: company_id is intentionally NOT here; it is injected server-side
    #       from the authenticated user's token so tenants can never spoof it.

class JobUpdate(BaseModel):
    """Schema for updating job details."""
    title: Optional[str] = None
    description: Optional[str] = None
    min_experience: Optional[int] = None
    required_skills: Optional[List[str]] = None
    is_active: Optional[bool] = None

class JobResponse(JobCreate):
    id: int
    company_id: int
    is_active: bool
    views: Optional[int] = 0
    application_count: Optional[int] = 0
    form_config: Optional[dict] = None

    class Config:
        from_attributes = True

class JobStatsResponse(BaseModel):
    """Statistics for a specific job."""
    job_id: int
    job_title: str
    total_applicants: int
    shortlisted: int
    under_review: int
    rejected: int
    interviewed: int
    hired: int
    average_score: float

class DashboardStatsResponse(BaseModel):
    """Overall dashboard statistics for a company."""
    total_jobs: int
    active_jobs: int
    total_applicants: int
    shortlisted_applicants: int
    pending_review: int
    recent_applicants: List["ApplicantResponse"]


class JobFormConfig(BaseModel):
    require_linkedin: Optional[Union[bool, str]] = None
    require_portfolio: Optional[Union[bool, str]] = None
    custom_questions: Optional[List[str]] = None


# ==============================================================================
# APPLICANT SCHEMAS
# ==============================================================================

class ApplicantResponse(BaseModel):
    id: int
    job_id: int
    company_id: int
    name: str
    email: str
    match_score: int
    years_experience: int
    summary: str
    status: str
    breakdown: Optional[dict] = None

    class Config:
        from_attributes = True

class ApplicantStatusUpdate(BaseModel):
    """Schema for updating an applicant's status in the hiring workflow."""
    status: str  # new | rejected | shortlisted | review | interviewed | hired

class BulkApplicantStatusUpdate(BaseModel):
    """Schema for bulk updating multiple applicants' statuses."""
    applicant_ids: List[int]
    status: str

class ApplicantDetailResponse(ApplicantResponse):
    """Extended applicant response with full resume text."""
    phone: Optional[str]
    skills: Union[Dict[str, float], List[str]]
    resume_text: str
    linkedin_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    custom_answers: Optional[dict] = None

    class Config:
        from_attributes = True


# ==============================================================================
# PUBLIC CAREERS PORTAL SCHEMAS
# ==============================================================================

class PublicJobResponse(BaseModel):
    """Public-facing job details (no sensitive company data)."""
    id: int
    title: str
    description: str
    required_skills: List[str]
    min_experience: int
    form_config: Optional[dict] = None

    class Config:
        from_attributes = True

class PublicApplicationSubmission(BaseModel):
    """Schema for public application submission (validated before processing)."""
    name: str
    email: EmailStr
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    custom_answers: Optional[dict] = None