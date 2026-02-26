from sqlalchemy import Column, Integer, String, Text, ForeignKey, Float, Boolean, JSON, DateTime, LargeBinary, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


# ==============================================================================
# TENANT MODEL
# ==============================================================================

class Company(Base):
    """Top-level tenant. Every piece of data belongs to a Company."""
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    subscription_tier = Column(String, default="free")  # free | pro | enterprise
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", back_populates="company")
    jobs = relationship("Job", back_populates="company")


# ==============================================================================
# USER MODEL
# ==============================================================================

class User(Base):
    """Authenticated user scoped to a Company tenant."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="recruiter")  # recruiter | admin
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="users")


# ==============================================================================
# CORE ATS MODELS (now tenant-scoped via company_id)
# ==============================================================================

class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    # Multi-tenancy: every job belongs to exactly one company
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    # Bulk-screen tracking
    tracking_id = Column(String, unique=True, nullable=True, index=True)  # UUID from job_tracker
    status     = Column(String, default="pending")                         # pending|processing|completed|failed
    total_resumes = Column(Integer, nullable=True)
    processed_resumes = Column(Integer, nullable=True, default=0)
    results    = Column(JSON, nullable=True)                               # full results dict persisted on completion
    title = Column(String, index=True)
    description = Column(Text)
    min_experience = Column(Integer)
    required_skills = Column(JSON)  # List of strings ["Python", "SQL"]
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Public Careers Portal Analytics
    views = Column(Integer, default=0)  # Track page views on public portal
    application_count = Column(Integer, default=0)  # Track submitted applications
    form_config = Column(JSON, nullable=True)  # Custom form configuration
    
    # Level 1: Grounded JD Requirements (extracted verbatim sentences)
    jd_requirements = Column(JSON, nullable=True)  # List of requirement strings

    company = relationship("Company", back_populates="jobs")
    applicants = relationship("Applicant", back_populates="job")


class Applicant(Base):
    __tablename__ = "applicants"
    __table_args__ = (
        UniqueConstraint("job_id", "email", name="uq_applicants_job_email"),
    )

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    # Denormalized for fast tenant-scoped queries without a JOIN on jobs
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String)
    email = Column(String)
    phone = Column(String, nullable=True)
    resume_text = Column(Text)  # Raw text from PDF
    resume_pdf = Column(LargeBinary, nullable=True)  # Original PDF file for download

    # AI Extracted Data
    years_experience = Column(Integer)
    skills = Column(JSON)  # Extracted skills ["Python", "FastAPI"]

    # Scoring
    match_score = Column(Integer)
    summary = Column(Text)  # AI reasoning
    breakdown = Column(JSON, nullable=True)            # {skill_depth, title_match, experience, impact}
    status = Column(String, default="new")             # new | rejected | shortlisted | review
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Public Careers Portal Fields
    linkedin_url = Column(String, nullable=True)
    portfolio_url = Column(String, nullable=True)
    custom_answers = Column(JSON, nullable=True)  # Store custom form question answers

    job = relationship("Job", back_populates="applicants")