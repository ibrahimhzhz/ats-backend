"""Check existing users in database."""
from database import SessionLocal
import models

db = SessionLocal()

try:
    users = db.query(models.User).all()
    
    print(f"\n📊 {len(users)} Users in Database:\n")
    print("=" * 80)
    
    for user in users:
        company = db.query(models.Company).filter(models.Company.id == user.company_id).first()
        print(f"Email: {user.email}")
        print(f"Company: {company.name if company else 'Unknown'} (ID: {user.company_id})")
        print(f"User ID: {user.id}")
        print("-" * 80)
    
finally:
    db.close()
