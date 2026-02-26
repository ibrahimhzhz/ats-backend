# Authentication & Multi-Tenancy Upgrade

**Date:** February 20, 2026  
**Scope:** JWT-based authentication + company-scoped multi-tenancy across the entire ATS backend.

---

## New Dependencies

```bash
pip install "passlib[bcrypt]" "python-jose[cryptography]" "pydantic[email]"
# python-multipart was already present
```

Added to `requirements.txt`:
```
pydantic[email]
passlib[bcrypt]
python-jose[cryptography]
```

---

## Files Changed

### `models.py`

- Added `Company` model — top-level tenant record.
  - Columns: `id`, `name`, `subscription_tier` (default `"free"`), `created_at`
- Added `User` model — authenticated user scoped to a company.
  - Columns: `id`, `company_id` (FK → `companies.id`), `email`, `hashed_password`, `role` (default `"recruiter"`), `created_at`
- Updated `Job` — added `company_id` (`ForeignKey("companies.id")`, `nullable=False`, indexed).
- Updated `Applicant` — added `company_id` (`ForeignKey("companies.id")`, `nullable=False`, indexed). Denormalized for fast tenant-scoped queries without a JOIN through `jobs`.

---

### `schemas.py`

| Schema | Description |
|---|---|
| `CompanyCreate` | Payload to create a new company |
| `CompanyResponse` | Public company shape |
| `UserCreate` | Registration payload: `email`, `password`, `company_name` |
| `UserResponse` | Safe public user (no `hashed_password`) |
| `Token` | JWT login response: `access_token`, `token_type` |
| `TokenData` | Internal decoded JWT claims: `user_id`, `company_id` |
| `JobCreate` | `company_id` is intentionally absent — injected server-side from the JWT |
| `JobResponse` | Now includes `company_id` |
| `ApplicantResponse` | Now includes `job_id` and `company_id` |

---

### `services/auth.py` _(new file)_

Core security layer.

| Symbol | Description |
|---|---|
| `hash_password(plain)` | Returns a bcrypt hash via passlib |
| `verify_password(plain, hashed)` | Constant-time comparison |
| `create_access_token(data)` | Creates a signed HS256 JWT embedding `user_id` + `company_id` |
| `decode_access_token(token)` | Decodes and validates a JWT; raises `401` on failure |
| `get_current_user(token, db)` | FastAPI dependency — extracts `Authorization: Bearer`, decodes JWT, fetches `User` from DB |
| `authenticate_user(db, email, pw)` | Email lookup + password verification; used by the login endpoint |
| `oauth2_scheme` | `OAuth2PasswordBearer(tokenUrl="/auth/login")` — tells FastAPI/OpenAPI where to get a token |

Configuration (read from environment variables):

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | `CHANGE_ME_IN_PRODUCTION_...` | **Must be overridden in production** (`openssl rand -hex 32`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` (8 hours) | Adjust to match your session policy |

---

### `routers/auth.py` _(new file)_

| Endpoint | Method | Auth required | Description |
|---|---|---|---|
| `/auth/register` | POST | No | Creates a `Company` + first admin `User`. Guards duplicate email/company with `409`. |
| `/auth/login` | POST | No | OAuth2 password form. Returns `{ access_token, token_type }`. |
| `/auth/me` | GET | Yes | Returns the current authenticated user's profile. |

---

### `routers/jobs.py`

All endpoints now require `current_user: models.User = Depends(get_current_user)`.

| Endpoint | Change |
|---|---|
| `POST /jobs/` | `company_id` injected from JWT — never from the request body |
| `GET /jobs/` | Filtered by `Job.company_id == current_user.company_id` |
| `GET /jobs/{id}` | _(new)_ Filtered by tenant + 404 if not owned |
| `DELETE /jobs/{id}` | _(new)_ Admin-only + tenant-scoped |

---

### `main.py`

- Imported and registered `auth_router`: `app.include_router(auth_router.router)`
- `bulk_screen_resumes` endpoint:
  - Added `current_user: models.User = Depends(get_current_user)` parameter.
  - `Job` stub created with `company_id=current_user.company_id`.
- `process_resumes_background` background task:
  - New `company_id: int` parameter added to signature.
  - Every `Applicant` record saved with `company_id=company_id`.

---

## Authentication Flow

```
POST /auth/register
Body: { "email": "...", "password": "...", "company_name": "Acme Corp" }
→ 201 { id, email, role, company_id, created_at }

POST /auth/login
Form: username=<email>&password=<password>
→ 200 { "access_token": "eyJ...", "token_type": "bearer" }

GET /jobs/
Header: Authorization: Bearer eyJ...
→ 200 [ ...only this company's jobs... ]

POST /api/bulk-screen
Header: Authorization: Bearer eyJ...
Form: resumes_zip=<file>, job_description=..., min_experience=..., required_skills=...
→ 200 { job_id, db_job_id, total_resumes, ... }
```

---

## Tenant Isolation Guarantee

Every read and write query involving `Job` or `Applicant` is scoped by `company_id` derived from the validated JWT — it is never accepted from the client payload. A user from Company A cannot read, create, or delete data belonging to Company B.

---

## Production Checklist

- [ ] Set `SECRET_KEY` env var to a cryptographically random 32-byte hex string (`openssl rand -hex 32`)
- [ ] Set `ACCESS_TOKEN_EXPIRE_MINUTES` in env to match your session policy
- [ ] Run database migrations (or `Base.metadata.create_all()`) to create the new `companies` and `users` tables
- [ ] Switch `DATABASE_URL` env var from SQLite to PostgreSQL for production
- [ ] Set `HTTPS` / TLS termination (Bearer tokens must not travel over plain HTTP)
