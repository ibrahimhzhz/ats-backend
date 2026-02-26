"""Check which company owns job 14 and test API call."""
from database import SessionLocal
import models
import requests
import json

db = SessionLocal()

try:
    # Get job 14
    job = db.query(models.Job).filter(models.Job.id == 14).first()
    
    if not job:
        print("Job 14 not found!")
        exit()
    
    print(f"Job 14: {job.title}")
    print(f"Company ID: {job.company_id}")
    
    # Get company
    company = db.query(models.Company).filter(models.Company.id == job.company_id).first()
    print(f"Company: {company.name if company else 'Unknown'}")
    
    # Get user for this company
    user = db.query(models.User).filter(models.User.company_id == job.company_id).first()
    
    if not user:
        print("No user found for this company!")
        exit()
    
    print(f"User: {user.email}")
    print("=" * 80)
    
finally:
    db.close()

# Now test the API call - we need to know the password
# Let's just call the API with a made-up token to see the structure
print("\nAttempting to call API...")
print("Note: We need the actual password for the user to get a valid token.")
print("\nInstead, let's directly query the applicants from the database API endpoint without auth:")

# Actually, let me just make a direct database query to see what applicants exist
db2 = SessionLocal()
try:
    applicants = db2.query(models.Applicant).filter(
        models.Applicant.job_id == 14
    ).order_by(models.Applicant.id.desc()).all()
    
    print(f"\nDirect DB Query - {len(applicants)} applicants for job 14:")
    for app in applicants:
        print(f"  ID: {app.id}, Name: {app.name}, Email: {app.email}, Score: {app.match_score}, Status: {app.status}")
        print(f"  Has breakdown: {app.breakdown is not None}")
        if app.breakdown:
            print(f"  Breakdown keys: {app.breakdown.keys()}")
finally:
    db2.close()
