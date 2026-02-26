from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

# If DATABASE_URL is not set, default to a local SQLite file
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ats.db")

# SQLite-only engine args
engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

# 1. Create the Engine
engine = create_engine(DATABASE_URL, **engine_kwargs)

# 2. Create the SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 3. Create the Base class
Base = declarative_base()

# 4. Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 5. Safe schema migrations (SQLite-compatible, idempotent)
def run_migrations():
    """
    ADD new columns to existing tables without dropping data.
    Each ALTER TABLE is wrapped in try/except — SQLite raises an error if
    the column already exists, which we silently ignore.
    """
    from sqlalchemy import text

    dialect = engine.dialect.name
    datetime_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
    binary_type = "BYTEA" if dialect == "postgresql" else "BLOB"

    new_columns = [
        # jobs table
        "ALTER TABLE jobs ADD COLUMN tracking_id TEXT",
        "ALTER TABLE jobs ADD COLUMN status TEXT DEFAULT 'completed'",
        "ALTER TABLE jobs ADD COLUMN results JSON",
        "ALTER TABLE jobs ADD COLUMN total_resumes INTEGER",
        "ALTER TABLE jobs ADD COLUMN processed_resumes INTEGER DEFAULT 0",
        # SQLite rejects DEFAULT CURRENT_TIMESTAMP in ALTER TABLE;
        # add as nullable — SQLAlchemy server_default handles new inserts.
        f"ALTER TABLE jobs ADD COLUMN created_at {datetime_type}",
        # Public Careers Portal analytics
        "ALTER TABLE jobs ADD COLUMN views INTEGER DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN application_count INTEGER DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN form_config JSON",
        # Level 1: Grounded JD Requirements
        "ALTER TABLE jobs ADD COLUMN jd_requirements JSON",
        # applicants table
        "ALTER TABLE applicants ADD COLUMN breakdown JSON",
        f"ALTER TABLE applicants ADD COLUMN created_at {datetime_type}",
        # Public Careers Portal fields
        "ALTER TABLE applicants ADD COLUMN linkedin_url TEXT",
        "ALTER TABLE applicants ADD COLUMN portfolio_url TEXT",
        "ALTER TABLE applicants ADD COLUMN custom_answers JSON",
        # Resume PDF storage for downloads
        f"ALTER TABLE applicants ADD COLUMN resume_pdf {binary_type}",
    ]

    def _is_already_exists_error(error_message: str) -> bool:
        normalized = (error_message or "").lower()
        return (
            "duplicate column name" in normalized
            or "already exists" in normalized
            or "duplicate_table" in normalized
            or "duplicate_object" in normalized
        )

    with engine.connect() as conn:
        for stmt in new_columns:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                conn.rollback()
                if _is_already_exists_error(str(e)):
                    continue
                print(f"⚠️ Migration statement failed: {stmt} | error={e}")

        dedup_statements = [
            """
            DELETE FROM applicants
            WHERE email IS NOT NULL
              AND TRIM(email) != ''
              AND id NOT IN (
                SELECT MAX(id)
                FROM applicants
                WHERE email IS NOT NULL AND TRIM(email) != ''
                GROUP BY job_id, email
              )
            """,
        ]

        for stmt in dedup_statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"⚠️ Dedup migration failed: {e}")

        index_statements = [
            "CREATE INDEX IF NOT EXISTS ix_jobs_company_id_created_at ON jobs (company_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_applicants_company_job ON applicants (company_id, job_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_applicants_job_email ON applicants (job_id, email)",
        ]

        for stmt in index_statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"⚠️ Index migration failed: {stmt} | error={e}")