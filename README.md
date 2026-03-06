# LoqATS — AI-Powered Applicant Tracking System

LoqATS is a multi-tenant, AI-powered Applicant Tracking System (ATS) built with FastAPI. It automates resume screening through structured AI extraction (Google Vertex AI / Gemini), deterministic Python-based scoring, and a full hiring pipeline with Kanban board support. The system serves both an authenticated recruiter dashboard and a public-facing careers portal for candidates.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Technology Stack](#technology-stack)
3. [Project Structure](#project-structure)
4. [Data Models](#data-models)
5. [Authentication & Authorization](#authentication--authorization)
6. [Multi-Tenancy](#multi-tenancy)
7. [AI Extraction Engine](#ai-extraction-engine)
8. [Scoring Engine](#scoring-engine)
9. [Knockout Filters](#knockout-filters)
10. [Candidate Signals](#candidate-signals)
11. [Hiring Pipeline](#hiring-pipeline)
12. [API Reference](#api-reference)
13. [Celery Task Workers](#celery-task-workers)
14. [Public Careers Portal](#public-careers-portal)
15. [Frontend](#frontend)
16. [Database & Migrations](#database--migrations)
17. [Security](#security)
18. [Deployment](#deployment)
19. [Environment Variables](#environment-variables)

---

## Architecture Overview

```
┌──────────────┐    ┌──────────────┐    ┌──────────────────┐
│   Frontend   │───▶│  FastAPI App  │───▶│  PostgreSQL / DB │
│  (HTML/JS)   │    │   (main.py)  │    │   (SQLAlchemy)   │
└──────────────┘    └──────┬───────┘    └──────────────────┘
                           │
                    ┌──────▼───────┐    ┌──────────────────┐
                    │    Celery    │───▶│      Redis       │
                    │   Workers    │    │    (Broker)      │
                    └──────┬───────┘    └──────────────────┘
                           │
                    ┌──────▼───────┐
                    │  Google      │
                    │  Vertex AI   │
                    │  (Gemini)    │
                    └──────────────┘
```

**Request flow for resume processing:**

1. A resume PDF is uploaded (via bulk ZIP or individual public application).
2. The FastAPI endpoint validates the input and enqueues a Celery task.
3. The Celery worker extracts text from the PDF using PyMuPDF.
4. The extracted text is sent to **Google Vertex AI (Gemini 2.0 Flash)** for structured fact extraction.
5. The AI response is validated and enriched with Python-calculated fields (employment gaps, average tenure, skill years).
6. A **deterministic scoring engine** (pure Python, no AI) scores the candidate across 5 weighted dimensions.
7. **Knockout filters** flag hard/soft disqualifiers.
8. **Candidate signals** are generated for the pipeline UI.
9. The scored applicant is persisted to the database and aggregated results are updated on the parent job.

---

## Technology Stack

| Component | Technology |
|---|---|
| **Web Framework** | FastAPI (Python) |
| **Database** | PostgreSQL (production) / SQLite (local development) |
| **ORM** | SQLAlchemy (declarative base) |
| **Task Queue** | Celery with Redis broker/backend |
| **AI/ML** | Google Vertex AI — Gemini 2.0 Flash model |
| **PDF Parsing** | PyMuPDF (`fitz`) |
| **Authentication** | JWT (HS256) via `python-jose`, bcrypt password hashing |
| **Frontend** | Vanilla HTML/JS with Tailwind CSS, Lucide icons |
| **Containerization** | Docker + Docker Compose |
| **Process Manager** | Procfile (Railway / Heroku compatible) |

---

## Project Structure

```
ats_backend/
├── main.py                  # FastAPI app entry point, bulk-screen endpoints
├── database.py              # SQLAlchemy engine, session, Base, migrations
├── models.py                # ORM models (Company, User, Job, Applicant, StageLog)
├── schemas.py               # Pydantic request/response schemas
├── scoring.py               # Pure deterministic scoring engine (no DB/AI deps)
│
├── routers/
│   ├── auth.py              # POST /auth/register, /auth/login, GET /auth/me
│   ├── jobs.py              # CRUD for jobs + dashboard stats
│   ├── applicants.py        # CRUD for applicants + resume download
│   ├── pipeline.py          # Kanban pipeline stage management + audit trail
│   └── public.py            # Unauthenticated public careers portal endpoints
│
├── services/
│   ├── auth.py              # Password hashing, JWT creation/validation, get_current_user
│   ├── ai_engine.py         # Vertex AI integration, extraction, JD normalization
│   ├── tasks.py             # Celery tasks (process_resume, process_public_resume, etc.)
│   ├── pdf_parser.py        # PyMuPDF text extraction from PDF bytes
│   └── job_tracker.py       # In-memory job progress tracker with tenant isolation
│
├── core/
│   └── celery_app.py        # Celery application configuration
│
├── middleware/
│   └── security.py          # Request logging + security headers middleware
│
├── frontend/
│   ├── index.html           # Recruiter dashboard (3600+ lines SPA)
│   ├── login.html           # Login / registration page
│   ├── apply.html           # Public job application form
│   └── static/js/auth.js    # Client-side JWT auth layer
│
├── alembic/                 # Database migration versions
├── docker-compose.yml       # Multi-service Docker setup
├── Dockerfile               # Python 3.11 slim image
├── Procfile                 # Railway/Heroku process types
└── requirements.txt         # Python dependencies
```

---

## Data Models

### Company (Tenant)

The top-level entity. Every piece of data in the system belongs to a `Company`. This is the foundation of multi-tenancy.

| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Auto-incrementing identifier |
| `name` | String (unique) | Company name |
| `subscription_tier` | String | `free`, `pro`, or `enterprise` |
| `created_at` | DateTime | Account creation timestamp |

### User

An authenticated user scoped to a specific company.

| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Auto-incrementing identifier |
| `company_id` | Integer (FK → companies) | Tenant association |
| `email` | String (unique) | Login credential |
| `hashed_password` | String | bcrypt hash |
| `role` | String | `recruiter` or `admin` |
| `created_at` | DateTime | Registration timestamp |

### Job

A job posting with full metadata, application form configuration, and AI-extracted requirements.

| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Auto-incrementing identifier |
| `company_id` | Integer (FK → companies) | Tenant scope |
| `tracking_id` | String (unique) | UUID for bulk-screen tracking |
| `title` | String | Job title |
| `description` | Text | Full job description |
| `status` | String | `Draft`, `Live`, `processing`, `completed` |
| `min_experience` | Integer | Required minimum years of experience |
| `required_skills` | JSON | List of required skill strings |
| `is_active` | Boolean | Whether accepting applications |
| `jd_requirements` | JSON | AI-extracted structured requirements |
| `department` | String | e.g. Engineering, Marketing |
| `job_type` | String | e.g. Full-time, Part-time, Contract |
| `work_location_type` | String | Remote, Hybrid, On-site |
| `office_location` | String | Physical location if applicable |
| `openings` | Integer | Number of positions |
| `salary_min` / `salary_max` | Integer | Salary range |
| `currency` | String | Default `USD` |
| `pay_frequency` | String | `Annual`, `Monthly`, `Hourly` |
| `show_salary` | Boolean | Display salary on public portal |
| `equity_bonus` | String | Equity/bonus details |
| `nice_to_have_skills` | JSON | Optional skills list |
| `benefits` | JSON | List of benefits |
| `require_cover_letter` | Boolean | Require cover letter from candidates |
| `require_portfolio` | Boolean | Require portfolio URL |
| `require_linkedin` | Boolean | Require LinkedIn URL |
| `custom_questions` | JSON | Up to 5 custom application questions |
| `hiring_manager` | String | Name of hiring manager |
| `target_hire_date` | Date | Target date to fill position |
| `application_deadline` | Date | Last day to accept applications |
| `visibility` | String | `Public` or `Internal` |
| `views` | Integer | Page view counter on public portal |
| `application_count` | Integer | Total submitted applications |
| `form_config` | JSON | Custom form configuration |
| `total_resumes` | Integer | Total resumes in bulk screen |
| `processed_resumes` | Integer | Progress counter |
| `results` | JSON | Aggregated results payload |

### Applicant

A candidate application with resume data, AI extraction results, scores, and pipeline state.

| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Auto-incrementing identifier |
| `job_id` | Integer (FK → jobs) | Associated job |
| `company_id` | Integer (FK → companies) | Denormalized tenant scope |
| `name` | String | Candidate name |
| `email` | String | Candidate email (unique per job) |
| `phone` | String | Phone number |
| `resume_text` | Text | Extracted raw text (first 10,000 chars) |
| `resume_pdf` | LargeBinary | Original PDF for download |
| `years_experience` | Integer | Extracted total years |
| `skills` | JSON | Skills with years dict |
| `match_score` | Integer | Final score (0–100) |
| `summary` | Text | Human-readable scoring summary |
| `status` | String | `new`, `knockout`, `rejected`, `review`, `shortlisted` |
| `breakdown` | JSON | Score breakdown by category |
| `cover_letter` | Text | Submitted cover letter |
| `linkedin_url` | String | Submitted LinkedIn |
| `portfolio_url` | String | Submitted portfolio |
| `custom_answers` | JSON | Answers to custom questions |
| `skills_detailed` | JSON | [{name, years_used, last_used_year, job_index}] |
| `extracted_jobs` | JSON | [{title, company, start_year, end_year, domain, ...}] |
| `extracted_education` | JSON | [{degree, field_of_study, institution, year}] |
| `has_measurable_impact` | Boolean | Resume contains quantified achievements |
| `has_contact_info` | Boolean | Resume has email/phone |
| `has_clear_job_titles` | Boolean | Each role has clear title |
| `employment_gaps` | Boolean | Gaps of 6+ months detected |
| `average_tenure_years` | Float | Average years per role |
| `extractable_text` | Boolean | PDF was parseable |
| `cover_letter_analysis` | JSON | AI analysis of cover letter quality |
| `custom_answer_analysis` | JSON | AI analysis of custom answers |
| `score_breakdown` | JSON | Full 5-dimension score breakdown |
| `knockout_flags` | JSON | [{type, severity, reason}] |
| `candidate_signals` | JSON | UI-ready signal badges |
| `pipeline_stage` | String | Current Kanban stage |
| `stage_updated_at` | DateTime | Last stage change timestamp |

**Unique constraint:** `(job_id, email)` — one application per email per job.

### ApplicantStageLog

Immutable audit trail for pipeline stage changes. Rows are never updated or deleted.

| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Auto-incrementing identifier |
| `applicant_id` | Integer (FK → applicants) | Associated applicant |
| `from_stage` | String | Previous pipeline stage |
| `to_stage` | String | New pipeline stage |
| `changed_by_recruiter_id` | Integer (FK → users) | Who made the change |
| `note` | Text | Optional recruiter note |
| `changed_at` | DateTime | Timestamp of the change |

---

## Authentication & Authorization

### Registration Flow

`POST /auth/register` creates both a **Company** (tenant) and its first **admin User** atomically:
1. Checks for unique email and company name (409 on conflict).
2. Creates the `Company` record.
3. Creates the `User` with `role=admin` and a bcrypt-hashed password.

### Login Flow

`POST /auth/login` uses OAuth2 password flow (form-encoded `username` + `password`):
1. Looks up the user by email.
2. Verifies the bcrypt password hash.
3. Returns a signed JWT containing `user_id`, `company_id`, `sub`, `exp`, `iss`, and `aud` claims.

### JWT Configuration

| Setting | Default | Description |
|---|---|---|
| `SECRET_KEY` | (required) | Min 32 chars; app refuses to start with weak key |
| `ALGORITHM` | HS256 | Signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 480 (8 hours) | Token lifetime |
| `JWT_ISSUER` | `ats-backend` | `iss` claim |
| `JWT_AUDIENCE` | `ats-client` | `aud` claim |

In development, set `ALLOW_INSECURE_DEV_SECRET=true` to use a fallback dev-only secret. This is blocked in production.

### Route Protection

All authenticated routes use the `get_current_user` dependency:
1. Extracts `Bearer <token>` from the `Authorization` header.
2. Decodes and validates the JWT (checks signature, expiry, issuer, audience).
3. Fetches the User from the database.
4. Injects the hydrated `User` ORM object into the route handler.

Admin-only operations (delete job, delete applicant, toggle job status) additionally check `current_user.role == "admin"`.

---

## Multi-Tenancy

The system implements **row-level multi-tenancy** using `company_id` columns:

- Every `Job` and `Applicant` has a `company_id` foreign key.
- `company_id` is **never** accepted from the client — it is always injected server-side from the authenticated user's JWT.
- Every database query includes a `company_id` filter to ensure strict tenant isolation.
- The `Applicant` table has a denormalized `company_id` (redundant with `job.company_id`) to enable fast tenant-scoped queries without joins.
- The in-memory `JobTracker` also enforces tenant isolation via `company_id` checks.

**Cross-tenant data access is impossible** through the API — a user from Company A can never see, modify, or delete data belonging to Company B.

---

## AI Extraction Engine

Located in `services/ai_engine.py`. Uses **Google Vertex AI Gemini 2.0 Flash** for structured data extraction.

### Initialization

The AI model is lazy-initialized on first use. If Vertex AI credentials or `GCP_PROJECT_ID` are missing, the system degrades gracefully — AI-dependent endpoints return 503, but the rest of the app continues running.

Credentials can be provided via:
- `GOOGLE_APPLICATION_CREDENTIALS` (path to service account JSON)
- `GOOGLE_APPLICATION_CREDENTIALS_JSON` / `GOOGLE_CREDENTIALS_BASE64` / `GOOGLE_CREDENTIALS_JSON` (inline JSON or base64-encoded JSON)

### JD Requirement Extraction

`extract_jd_requirements(jd_text)` converts a freeform job description into a structured JSON contract:

```json
{
    "must_have_skills": ["Python", "React", "PostgreSQL"],
    "minimum_years_experience": 3,
    "education_requirement": "Bachelor's in Computer Science or equivalent",
    "offers_visa_sponsorship": false
}
```

This runs automatically (via Celery) when a job transitions to `Live` status, and is re-triggered when JD-relevant fields are updated on live jobs.

### Resume Fact Extraction

`extract_candidate_facts(resume_text, job_requirements)` performs a **single-pass structured extraction** from resume text:

**AI extracts (via strict JSON schema):**
- `total_years_experience` — calculated from job dates
- `skills[]` — every skill with `name`, `last_used_year`, `job_index`
- `jobs[]` — work history in reverse chronological order with `title`, `company`, dates, `domain`, `work_type`
- `education[]` — degrees with `degree`, `field_of_study`, `institution`, `year`
- Boolean signals: `extractable_text`, `requires_visa_sponsorship`, `has_measurable_impact`, `has_contact_info`, `has_clear_job_titles`
- `cover_letter_analysis` — word count, role mention, generic check
- `custom_answer_analysis` — per-question relevance and detail assessment

**Python enriches post-extraction:**
- `years_used` per skill — calculated from associated job durations
- `employment_gaps` — true if any 6+ month gap between roles
- `average_tenure_years` — mean years per role
- Contact info (`name`, `email`, `phone`) — regex-extracted from raw text for reliability

**Validation:** `validate_extraction_result()` ensures every field conforms to the expected type and shape, with logging and safe defaults for any malformed data.

### Rate Limiting

A global `RateLimiter` (60 calls/minute) throttles Vertex AI requests to stay within quotas.

---

## Scoring Engine

Located in `scoring.py`. This is a **pure Python module with zero external dependencies** — no database, no ORM, no AI calls. Every function is deterministic and testable in isolation.

### Score Weights (100 points total)

| Dimension | Max Points | Weight |
|---|---|---|
| **Experience** | 25 | 25% |
| **Skills** | 35 | 35% |
| **Education** | 15 | 15% |
| **Role Level Fit** | 10 | 10% |
| **Application Quality** | 15 | 15% |

### 1. Experience Score (25 points)

Split into two sub-scores:

- **Total Experience** (15 pts) — Based on the delta between candidate years and required years. Exact match or slight excess = full marks. Large deficit or significant overqualification = reduced score.
- **Domain Experience** (10 pts) — Measures years spent in the same industry domain as the job. Full marks if domain years meet requirements.

### 2. Skills Score (35 points)

Split into three sub-scores:

- **Required Skills Match** (20 pts) — Percentage of required skills found in the candidate's profile. Skills are canonicalized through `SKILL_ALIASES` (e.g., "ReactJS" → "react", "PostgreSQL" → "postgres").
- **Nice-to-Have Skills** (8 pts) — Percentage of optional skills matched.
- **Depth & Recency** (7 pts) — For matched required skills, factors in `years_used` and `last_used_year`. Senior roles demand deeper experience (4+ years) while junior roles accept less.

### 3. Education Score (15 points)

- **Degree Score** (10 pts) — Compares the candidate's highest degree against the job requirement using a ranked scale: `none(0) → high school(1) → associate(2) → bachelor(3) → master(4) → PhD(5)`. If "equivalent experience accepted" is specified, years of experience can substitute.
- **Field Relevance** (5 pts) — Evaluates field of study against the job's department using `FIELD_RELEVANCE` maps (e.g., Computer Science is 1.0 for Engineering, 0.7 for Design).

### 4. Role Level Fit (10 points)

Compares the seniority of the candidate's most recent role against the target job title using the `SENIORITY_LEVELS` map (intern=0 through C-level=8). Exact match = 10, off by 1 = 8, off by 2 = 4, further = 0.

### 5. Application Quality (15 points)

Evaluates the completeness and quality of the application submission:

- **Cover Letter** (5 pts) — Word count ≥200, mentions role title, has specific examples, is not generic.
- **Portfolio** (3 pts) — GitHub link = 3, other link = 2, missing when required = 0.
- **LinkedIn** (2 pts) — Present = 2, missing when required = 0.
- **Custom Answers** (5 pts) — Per-question scoring based on word count, relevance, and specificity.

### Status Bucketing

| Score Range | Hard Knockout? | Result |
|---|---|---|
| Any | Yes | `Rejected` |
| ≥ 70 | No | `Shortlisted` |
| 45–69 | No | `Needs Review` |
| < 45 | No | `Rejected` |

---

## Knockout Filters

Evaluated in `scoring.py → evaluate_knockout_filters()`. Each flag has a type, severity (`hard` or `soft`), and human-readable reason.

### Hard Knockouts (auto-reject, score set to 0)

| Type | Condition |
|---|---|
| `visa_sponsorship` | Candidate requires sponsorship but role doesn't offer it |
| `insufficient_experience` | 0 years experience when role requires ≥ 3 |
| `past_deadline` | Application submitted after the posting deadline |
| `unreadable_resume` | PDF could not be parsed |

### Soft Knockouts (flagged but not auto-rejected)

| Type | Condition |
|---|---|
| `overqualified` | Candidate has 5+ more years than required |
| `skills_gap` | Matches < 40% of required skills |
| `location_mismatch` | Recent roles remote but position on-site |
| `level_mismatch` | Seniority level off by ≥ 2 levels |
| `missing_portfolio` | Portfolio required but not submitted |
| `missing_linkedin` | LinkedIn required but not submitted |

---

## Candidate Signals

Generated by `scoring.py → generate_candidate_signals()`. These are UI-ready badge objects displayed on the pipeline board:

| Signal Type | Levels | Description |
|---|---|---|
| `stability` | green/grey/yellow | Average tenure ≥3y (stable), ≥1.5y (neutral), <1.5y (unstable) |
| `job_hopping` | red | 3+ jobs in last 2 years |
| `measurable_impact` | green | Resume contains quantified achievements |
| `employment_gap` | yellow | Gap of 6+ months detected |
| `completeness` | green/yellow/red | Resume completeness score (0–5 factors) |

---

## Hiring Pipeline

### Pipeline Stages

The hiring workflow follows these ordered stages:

```
Applied → Recruiter Screen → Hiring Manager Review → Interview → Offer → Hired
                                                                          │
                                   (any non-terminal stage) ──────────→ Rejected
```

**Terminal stages:** `Hired` and `Rejected` — candidates cannot be moved out of these.

**Business rules:**
- Stages only move **forward** (no backward moves).
- `Rejected` is a special lateral move allowed from any non-terminal stage.
- Moving to the same stage is a no-op error.
- Stage changes and audit logs are written in a single atomic transaction.

### Audit Trail

Every stage change creates an immutable `ApplicantStageLog` entry recording:
- From/to stages
- Which recruiter made the change (by user ID)
- Optional note
- Timestamp

The audit history is queryable per applicant via `GET /api/jobs/{job_id}/applicants/{applicant_id}/history`.

### Kanban View

`GET /api/jobs/{job_id}/pipeline` returns all applicants grouped by stage, pre-filled for every valid stage so the frontend always gets a complete shape:

```json
{
    "Applied": [...],
    "Recruiter Screen": [...],
    "Hiring Manager Review": [...],
    "Interview": [...],
    "Offer": [...],
    "Hired": [...],
    "Rejected": [...]
}
```

---

## API Reference

### Authentication

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | No | Create company + first admin user |
| POST | `/auth/login` | No | OAuth2 password flow → JWT |
| GET | `/auth/me` | Yes | Current user profile |

### Jobs

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/jobs/` | Yes | Create a new job posting |
| GET | `/jobs/` | Yes | List all jobs for company |
| GET | `/jobs/{job_id}` | Yes | Get single job details |
| PUT | `/jobs/{job_id}` | Yes | Update job details |
| DELETE | `/jobs/{job_id}` | Admin | Delete job and its applicants |
| PATCH | `/jobs/{job_id}/status` | Admin | Toggle job active/inactive |
| PUT | `/jobs/{job_id}/form-config` | Yes | Update application form config |
| GET | `/jobs/{job_id}/stats` | Yes | Get job statistics |
| GET | `/jobs/dashboard/stats` | Yes | Get company dashboard stats |

### Applicants

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/applicants/apply/{job_id}` | No | Single resume apply (legacy) |
| GET | `/applicants/` | Yes | List applicants (with filters) |
| GET | `/applicants/{id}` | Yes | Get applicant detail |
| PUT | `/applicants/{id}/status` | Yes | Update applicant status |
| DELETE | `/applicants/{id}` | Admin | Delete applicant |
| PUT | `/applicants/bulk/status` | Yes | Bulk update statuses |
| GET | `/applicants/{id}/download-resume` | Yes | Download original PDF |

### Pipeline

| Method | Path | Auth | Description |
|---|---|---|---|
| PATCH | `/api/jobs/{job_id}/applicants/{id}/stage` | Yes | Move to new pipeline stage |
| GET | `/api/jobs/{job_id}/applicants/{id}/history` | Yes | Stage change audit trail |
| GET | `/api/jobs/{job_id}/pipeline` | Yes | Kanban view grouped by stage |

### Bulk Screening

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/bulk-screen` | Yes | Upload ZIP of resume PDFs |
| GET | `/api/job/{job_id}` | Yes | Check bulk processing status |
| GET | `/api/jobs` | Yes | List all bulk screening jobs |

### Public Careers Portal

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/public/job/{job_id}` | No | View public job details |
| POST | `/api/public/apply/{job_id}` | No | Submit application (multipart) |

### Other

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/health` | No | Health check with AI readiness |
| GET | `/` | No | Recruiter dashboard (HTML) |
| GET | `/login` | No | Login page (HTML) |
| GET | `/apply/{job_id}` | No | Application form (HTML) |

---

## Celery Task Workers

Defined in `services/tasks.py`, configured in `core/celery_app.py`.

### Broker & Backend

Redis (default: `redis://localhost:6379/0`, configurable via `REDIS_URL`).

### Tasks

| Task Name | Trigger | Description |
|---|---|---|
| `process_resume` | Bulk screen ZIP upload | Processes a single PDF: extract text → AI extraction → scoring → knockout → signals → persist applicant |
| `process_public_resume` | Public portal application | Same pipeline as above, plus merges form-submitted fields (name, email, cover letter, etc.) and increments `application_count` |
| `aggregate_job_results` | After each resume processed | Rebuilds the `jobs.results` JSON payload with all applicant scores, counts, and shortlist |
| `extract_jd_requirements_task` | Job created/updated as Live | Runs AI JD extraction and persists structured requirements to `jobs.jd_requirements` |

### Deduplication

Both `process_resume` and `process_public_resume` guard against duplicate applications:
1. Pre-scan email via regex from resume text.
2. Check for existing applicant with same `(job_id, email)`.
3. If found, skip processing silently.
4. Database-level unique constraint `uq_applicants_job_email` as a final safety net.

---

## Public Careers Portal

Unauthenticated endpoints for candidates (`routers/public.py`).

### Job Viewing

`GET /api/public/job/{job_id}`:
- Returns public-safe job details (no internal company data).
- Increments the view counter.
- Blocks internal-only (`visibility=Internal`) and inactive jobs.

### Application Submission

`POST /api/public/apply/{job_id}`:
- Accepts multipart form data: candidate info, optional fields, resume PDF.
- **Anti-spam measures:**
  - Honeypot field (`website_url_catch`) — silently discards bot submissions.
  - IP-based rate limiting (20 requests/minute per IP).
  - Email-based rate limiting (5 requests/minute per email).
- **Validation:**
  - Job must be active, public, and before deadline.
  - Required fields (cover letter, portfolio, LinkedIn) enforced per job config.
  - Custom questions must all be answered if configured.
  - PDF only, max 10MB.
- **Deduplication:** Silent success response if email already applied (no information leak).
- Enqueues `process_public_resume` Celery task and returns immediately.

---

## Frontend

The frontend is a server-rendered set of HTML pages with inline JavaScript and Tailwind CSS styling.

### Pages

| Page | File | Description |
|---|---|---|
| **Dashboard** | `frontend/index.html` | Full recruiter SPA (~3,600 lines). Includes job management, applicant lists, score breakdowns, pipeline Kanban board, bulk screening, and real-time progress polling. |
| **Login** | `frontend/login.html` | Login + registration form with animated UI. |
| **Apply** | `frontend/apply.html` | Public application form that dynamically adapts to job requirements (custom questions, required fields). |

### Auth Layer (`frontend/static/js/auth.js`)

A vanilla JavaScript module providing:
- `Auth.checkAuth()` — Redirects to `/login` if no valid token. Call on page load for protected pages.
- `Auth.authFetch(url, options)` — Drop-in `fetch()` replacement that attaches `Authorization: Bearer` header and auto-redirects on 401.
- `Auth.login(email, password)` — Authenticates via OAuth2 form POST, stores token + user profile in `localStorage`.
- `Auth.logout()` — Clears auth state, redirects to `/login`.
- `Auth.getToken()` / `Auth.getUser()` — Accessors with automatic expiry checking.

---

## Database & Migrations

### Connection

Configured via `DATABASE_URL` environment variable:
- **PostgreSQL** (production): `postgresql://user:pass@host:5432/dbname`
- **SQLite** (local default): `sqlite:///./ats.db`

SQLite-specific settings (`check_same_thread=False`) are auto-detected.

### Schema Migrations

The application uses a **hybrid migration strategy**:

1. **SQLAlchemy `create_all`** — Creates all tables on startup from the ORM models.
2. **`run_migrations()`** — Executes idempotent `ALTER TABLE ADD COLUMN` statements to evolve the schema without data loss. Each statement is wrapped in try/except — if the column already exists, the error is silently ignored. This handles:
   - New columns on `jobs` table (tracking, portal analytics, JD requirements, redesigned fields)
   - New columns on `applicants` table (enriched extraction, scoring, pipeline)
   - Deduplication cleanup (removes duplicate applicants by email per job)
   - Backfill (sets `pipeline_stage='Applied'` for existing applicants)
   - Index creation for performance
3. **Alembic** — Available for formal versioned migrations when needed.

### Key Indexes

- `ix_jobs_company_id_created_at` — Fast company-scoped job listing
- `ix_applicants_company_job` — Fast company+job scoped applicant queries
- `uq_applicants_job_email` — Unique constraint preventing duplicate applications
- `ix_stage_log_applicant` — Fast audit trail lookups

---

## Security

### Middleware

Two security middleware layers process every request/response:

1. **`SecurityLoggingMiddleware`** — Logs all requests with timestamp, client IP, method, path, user ID, and company ID for audit trail and anomaly detection.
2. **`SecurityHeadersMiddleware`** — Adds hardened response headers:
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
   - `X-XSS-Protection: 1; mode=block`
   - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
   - Removes the `Server` header.

### CORS

Configured for `http://localhost:8001` by default. Adjust `allow_origins` for production.

### Additional Security Measures

- **bcrypt** password hashing with random salts.
- **JWT** tokens with expiry, issuer, and audience validation.
- **SECRET_KEY** enforcement — app refuses to start without a strong key (≥32 chars) in non-dev environments.
- **Tenant isolation** on every query — `company_id` is injected from JWT, never accepted from client.
- **Input validation** — Pydantic schemas with `EmailStr`, file size limits (10MB), PDF-only enforcement.
- **Rate limiting** — Public endpoints have per-IP and per-email rate limits.
- **Honeypot** field on public forms for bot detection.
- **Silent dedup responses** — Duplicate applications return success to prevent information leaking.

---

## Deployment

### Docker Compose (Full Stack)

```bash
docker-compose up --build
```

Launches 4 services:
- **db** — PostgreSQL 15 with health checks
- **redis** — Redis Alpine for Celery broker
- **web** — FastAPI app on port 8000
- **worker** — Celery worker processing resume tasks

### Railway / Heroku

The `Procfile` defines two process types:

```
web: uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: celery -A core.celery_app worker --loglevel=info
```

### Dockerfile

Python 3.11 slim base image. Copies requirements, installs dependencies, copies source code, exposes port 8000.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | No | `sqlite:///./ats.db` | Database connection string |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Celery broker/backend URL |
| `SECRET_KEY` | **Yes*** | — | JWT signing secret (≥32 chars) |
| `ALLOW_INSECURE_DEV_SECRET` | No | `false` | Allow weak secret in dev mode |
| `APP_ENV` | No | `development` | Environment: development, staging, production |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `480` | JWT token lifetime in minutes |
| `JWT_ISSUER` | No | `ats-backend` | JWT issuer claim |
| `JWT_AUDIENCE` | No | `ats-client` | JWT audience claim |
| `GCP_PROJECT_ID` | Yes** | — | Google Cloud project ID for Vertex AI |
| `GCP_LOCATION` | No | `us-central1` | Vertex AI region |
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes** | — | Path to GCP service account JSON |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | Alt** | — | Inline JSON credentials |
| `GOOGLE_CREDENTIALS_BASE64` | Alt** | — | Base64-encoded JSON credentials |
| `JOB_TRACKER_CLEANUP_INTERVAL_SECONDS` | No | `1800` | Job tracker cleanup interval |
| `JOB_TRACKER_MAX_AGE_HOURS` | No | `24` | Max age for in-memory jobs |
| `ATS_RESUME_TMP_DIR` | No | system temp | Temporary directory for ZIP uploads |

\* Required in production. Dev mode can use `ALLOW_INSECURE_DEV_SECRET=true`.
\** Required for AI features. App runs without AI if missing (screening endpoints return 503).
