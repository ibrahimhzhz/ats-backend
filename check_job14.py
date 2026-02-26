"""Check applicants for AI Engineer job (ID: 14)."""
from database import SessionLocal
import models
import json

db = SessionLocal()

try:
    # Get the job
    job = db.query(models.Job).filter(models.Job.id == 14).first()
    
    if not job:
        print("Job 14 not found!")
        exit()
    
    print(f"\n📋 Job: {job.title} (ID: {job.id})")
    print(f"Description: {job.description[:100]}...")
    print(f"Min Experience: {job.min_experience} years")
    print(f"Required Skills: {job.required_skills}")
    print(f"Application Count: {job.application_count}")
    print(f"Is Active: {job.is_active}")
    print("=" * 120)
    
    # Get all applicants for this job
    applicants = db.query(models.Applicant).filter(
        models.Applicant.job_id == 14
    ).order_by(models.Applicant.created_at.desc()).all()
    
    print(f"\n📊 {len(applicants)} Applicants:\n")
    
    for i, app in enumerate(applicants, 1):
        print(f"\n{i}. {app.name} ({app.email})")
        print(f"   ID: {app.id}")
        print(f"   Score: {app.match_score}")
        print(f"   Status: {app.status}")
        print(f"   Experience: {app.years_experience} years")
        print(f"   Created: {app.created_at}")
        print(f"   Phone: {app.phone}")
        print(f"   LinkedIn: {app.linkedin_url}")
        print(f"   Portfolio: {app.portfolio_url}")
        print(f"   Has Breakdown: {'Yes' if app.breakdown else 'No'}")
        if app.breakdown:
            print(f"   Breakdown: {json.dumps(app.breakdown, indent=6)}")
        print(f"   Skills: {app.skills}")
        print(f"   Summary: {app.summary}")
        print("-" * 120)
    
finally:
    db.close()
