"""Quick script to check applicants in the database."""
from database import SessionLocal
import models

db = SessionLocal()

try:
    applicants = db.query(models.Applicant).order_by(models.Applicant.created_at.desc()).limit(10).all()
    
    print(f"\n📊 Latest {len(applicants)} Applicants:\n")
    print("=" * 120)
    
    for app in applicants:
        job = db.query(models.Job).filter(models.Job.id == app.job_id).first()
        job_title = job.title if job else "Unknown Job"
        
        print(f"ID: {app.id}")
        print(f"Name: {app.name}")
        print(f"Email: {app.email}")
        print(f"Job: {job_title} (ID: {app.job_id})")
        print(f"Score: {app.match_score}")
        print(f"Status: {app.status}")
        print(f"Created: {app.created_at}")
        print(f"Has Breakdown: {'Yes' if app.breakdown else 'No'}")
        if app.breakdown:
            print(f"  Breakdown: {app.breakdown}")
        print(f"Summary: {app.summary[:100]}..." if len(app.summary) > 100 else f"Summary: {app.summary}")
        print("-" * 120)
    
    # Count by job
    print("\n📈 Applications by Job:")
    jobs = db.query(models.Job).all()
    for job in jobs:
        count = db.query(models.Applicant).filter(models.Applicant.job_id == job.id).count()
        print(f"  {job.title} (ID: {job.id}): {count} applicants")
    
finally:
    db.close()
