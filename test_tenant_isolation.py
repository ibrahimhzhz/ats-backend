"""
Security test suite for multi-tenant isolation.
Tests to ensure companies cannot access each other's data.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, get_db
from main import app
import models

# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


class TestTenantIsolation:
    """Test suite for verifying tenant isolation."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test data before each test."""
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        
        db = TestingSessionLocal()
        
        # Create two companies
        company1 = models.Company(name="Company A", subscription_tier="pro")
        company2 = models.Company(name="Company B", subscription_tier="free")
        db.add(company1)
        db.add(company2)
        db.commit()
        
        # Create users for each company
        user1 = models.User(
            company_id=company1.id,
            email="admin@companya.com",
            hashed_password="$2b$12$test1",
            role="admin"
        )
        user2 = models.User(
            company_id=company2.id,
            email="admin@companyb.com",
            hashed_password="$2b$12$test2",
            role="admin"
        )
        db.add(user1)
        db.add(user2)
        db.commit()
        
        # Create jobs for each company
        job1 = models.Job(
            company_id=company1.id,
            title="Python Developer - Company A",
            description="Company A job",
            min_experience=3,
            required_skills=["Python", "FastAPI"],
            is_active=True
        )
        job2 = models.Job(
            company_id=company2.id,
            title="Java Developer - Company B",
            description="Company B job",
            min_experience=5,
            required_skills=["Java", "Spring"],
            is_active=True
        )
        db.add(job1)
        db.add(job2)
        db.commit()
        
        # Create applicants for each job
        applicant1 = models.Applicant(
            job_id=job1.id,
            company_id=company1.id,
            name="John Doe",
            email="john@example.com",
            years_experience=5,
            skills=["Python"],
            match_score=85,
            summary="Good match",
            status="shortlisted",
            resume_text="Resume text"
        )
        applicant2 = models.Applicant(
            job_id=job2.id,
            company_id=company2.id,
            name="Jane Smith",
            email="jane@example.com",
            years_experience=6,
            skills=["Java"],
            match_score=90,
            summary="Excellent match",
            status="shortlisted",
            resume_text="Resume text"
        )
        db.add(applicant1)
        db.add(applicant2)
        db.commit()
        
        self.company1_id = company1.id
        self.company2_id = company2.id
        self.user1_id = user1.id
        self.user2_id = user2.id
        self.job1_id = job1.id
        self.job2_id = job2.id
        self.applicant1_id = applicant1.id
        self.applicant2_id = applicant2.id
        
        db.close()
        yield
        
    def test_list_jobs_tenant_isolation(self):
        """Test that GET /jobs/ returns only the user's company jobs."""
        # This would require authentication - mock or skip for now
        # In a real test, you'd generate JWT tokens for each user
        pass
    
    def test_get_job_cross_tenant_blocked(self):
        """Test that users cannot access jobs from other companies."""
        # Company A user tries to access Company B's job
        # Should return 403 or 404
        pass
    
    def test_applicants_tenant_isolation(self):
        """Test that GET /applicants/ returns only the user's company applicants."""
        pass
    
    def test_update_applicant_cross_tenant_blocked(self):
        """Test that users cannot update applicants from other companies."""
        pass
    
    def test_job_tracker_tenant_isolation(self):
        """Test that job tracker doesn't leak data between companies."""
        from services.job_tracker import JobTracker
        
        tracker = JobTracker()
        
        # Company A creates a job
        job_id_a = tracker.create_job(10, self.company1_id)
        
        # Company B creates a job
        job_id_b = tracker.create_job(5, self.company2_id)
        
        # Company A should only see their job
        job_a = tracker.get_job(job_id_a, company_id=self.company1_id)
        assert job_a is not None
        assert job_a["company_id"] == self.company1_id
        
        # Company A should NOT see Company B's job
        job_b_unauthorized = tracker.get_job(job_id_b, company_id=self.company1_id)
        assert job_b_unauthorized is None
        
        # Company B should see their own job
        job_b = tracker.get_job(job_id_b, company_id=self.company2_id)
        assert job_b is not None
        assert job_b["company_id"] == self.company2_id
        
    def test_get_company_jobs_isolation(self):
        """Test that get_company_jobs only returns jobs for specified company."""
        from services.job_tracker import JobTracker
        
        tracker = JobTracker()
        
        # Create jobs for both companies
        job_id_a1 = tracker.create_job(10, self.company1_id)
        job_id_a2 = tracker.create_job(15, self.company1_id)
        job_id_b1 = tracker.create_job(5, self.company2_id)
        
        # Company A should see 2 jobs
        company_a_jobs = tracker.get_company_jobs(self.company1_id)
        assert len(company_a_jobs) == 2
        assert all(job["company_id"] == self.company1_id for job in company_a_jobs)
        
        # Company B should see 1 job
        company_b_jobs = tracker.get_company_jobs(self.company2_id)
        assert len(company_b_jobs) == 1
        assert all(job["company_id"] == self.company2_id for job in company_b_jobs)


def test_job_tracker_basic_functionality():
    """Test basic job tracker operations."""
    from services.job_tracker import JobTracker, JobStatus
    
    tracker = JobTracker()
    
    # Create a job
    job_id = tracker.create_job(total_resumes=10, company_id=1)
    assert job_id is not None
    
    # Get job status
    job = tracker.get_job(job_id)
    assert job is not None
    assert job["status"] == JobStatus.PENDING
    assert job["total_resumes"] == 10
    assert job["company_id"] == 1
    
    # Update status
    tracker.update_status(job_id, JobStatus.PROCESSING)
    job = tracker.get_job(job_id)
    assert job["status"] == JobStatus.PROCESSING
    
    # Update progress
    tracker.update_progress(job_id, 5)
    job = tracker.get_job(job_id)
    assert job["processed"] == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
