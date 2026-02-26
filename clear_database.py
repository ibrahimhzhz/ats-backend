"""
Database cleanup utility - Clear all processing data while preserving user accounts.
WARNING: This will delete all jobs and applicants from ALL companies!
"""
from database import SessionLocal
import models
from sqlalchemy import func

def clear_processing_data():
    """
    Clear all jobs and applicants from the database.
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
            print("✅ Database is already clean - no processing data to delete.")
            return
        
        # Ask for confirmation
        print("\n⚠️  WARNING: This will permanently delete:")
        print(f"   - {applicant_count} applicants")
        print(f"   - {job_count} jobs")
        print("\n✓  Will preserve:")
        print(f"   - {company_count} companies")
        print(f"   - {user_count} users")
        
        confirm = input("\nType 'DELETE' to confirm: ").strip()
        
        if confirm != "DELETE":
            print("❌ Cleanup cancelled.")
            return
        
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
    finally:
        db.close()


def clear_everything():
    """
    NUCLEAR OPTION: Clear the entire database including users and companies.
    USE WITH EXTREME CAUTION!
    """
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("⚠️  NUCLEAR OPTION - CLEAR EVERYTHING")
        print("=" * 60)
        print("This will delete ALL data including:")
        print("  - All applicants")
        print("  - All jobs")
        print("  - All users")
        print("  - All companies")
        print("=" * 60)
        
        confirm = input("\nType 'DELETE EVERYTHING' to confirm: ").strip()
        
        if confirm != "DELETE EVERYTHING":
            print("❌ Cleanup cancelled.")
            return
        
        print("\n🧹 Clearing entire database...")
        
        # Delete in correct order (respect foreign keys)
        deleted_applicants = db.query(models.Applicant).delete()
        print(f"✓ Deleted {deleted_applicants} applicants")
        
        deleted_jobs = db.query(models.Job).delete()
        print(f"✓ Deleted {deleted_jobs} jobs")
        
        deleted_users = db.query(models.User).delete()
        print(f"✓ Deleted {deleted_users} users")
        
        deleted_companies = db.query(models.Company).delete()
        print(f"✓ Deleted {deleted_companies} companies")
        
        db.commit()
        
        print("\n✅ Database completely cleared!")
        
    except Exception as e:
        db.rollback()
        print(f"\n❌ ERROR: {str(e)}")
        print("Database rolled back - no changes made.")
    finally:
        db.close()


if __name__ == "__main__":
    print("\n🗑️  Database Cleanup Utility")
    print("\nOptions:")
    print("1. Clear processing data only (keep users & companies)")
    print("2. Clear everything (NUCLEAR OPTION)")
    print("3. Cancel")
    
    choice = input("\nEnter choice (1-3): ").strip()
    
    if choice == "1":
        clear_processing_data()
    elif choice == "2":
        clear_everything()
    else:
        print("❌ Cancelled.")
