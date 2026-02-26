"""
Non-interactive database cleanup - Clear all processing data.
Automatically confirms and deletes all jobs and applicants.
"""
from database import SessionLocal
import models
from sqlalchemy import func

def clear_processing_data_auto():
    """
    Clear all jobs and applicants from the database (non-interactive).
    Preserves: Companies and Users
    Deletes: All Jobs and all Applicants
    """
    db = SessionLocal()
    
    try:
        # Get counts before deletion
        applicant_count = db.query(func.count(models.Applicant.id)).scalar()
        job_count = db.query(func.count(models.Job.id)).scalar()
        company_count = db.query(func.count(models.Company.id)).scalar()
        user_count = db.query(func.count(models.User.id)).scalar()
        
        print("=" * 60)
        print("DATABASE CLEANUP - CURRENT STATE")
        print("=" * 60)
        print(f"📊 Companies:  {company_count}")
        print(f"👥 Users:      {user_count}")
        print(f"📋 Jobs:       {job_count}")
        print(f"📄 Applicants: {applicant_count}")
        print("=" * 60)
        
        if applicant_count == 0 and job_count == 0:
            print("\n✅ Database is already clean - no processing data to delete.")
            return
        
        print("\n⚠️  AUTO-CLEANUP: Deleting all processing data...")
        print(f"   - {applicant_count} applicants")
        print(f"   - {job_count} jobs")
        print(f"\n✓  Preserving:")
        print(f"   - {company_count} companies")
        print(f"   - {user_count} users")
        
        print("\n🧹 Cleaning database...")
        
        # Delete all applicants first (due to foreign key constraints)
        deleted_applicants = db.query(models.Applicant).delete()
        print(f"✓ Deleted {deleted_applicants} applicants")
        
        # Delete all jobs
        deleted_jobs = db.query(models.Job).delete()
        print(f"✓ Deleted {deleted_jobs} jobs")
        
        # Commit the changes
        db.commit()
        
        print("\n" + "=" * 60)
        print("✅ DATABASE CLEANUP COMPLETE")
        print("=" * 60)
        print(f"Removed: {deleted_applicants} applicants, {deleted_jobs} jobs")
        print(f"Preserved: {company_count} companies, {user_count} users")
        print("=" * 60)
        
    except Exception as e:
        db.rollback()
        print(f"\n❌ ERROR: {str(e)}")
        print("Database rolled back - no changes made.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    clear_processing_data_auto()
