# ATS API Documentation

## 🔐 Security Overview

This API implements **strict multi-tenant isolation**. All endpoints enforce company-level data segregation to prevent data leaks between tenants.

### Authentication
All protected endpoints require a JWT token in the Authorization header:
```
Authorization: Bearer <your_jwt_token>
```

The JWT contains:
- `user_id`: Authenticated user's ID
- `company_id`: User's company (tenant) ID

---

## 📋 Endpoints

### Authentication Endpoints

#### `POST /auth/register`
Register a new user and optionally create a new company.

**Request Body:**
```json
{
  "email": "admin@example.com",
  "password": "SecurePass123!",
  "company_name": "Acme Corp"
}
```

**Response:**
```json
{
  "id": 1,
  "email": "admin@example.com",
  "role": "admin",
  "company_id": 1,
  "created_at": "2026-02-22T10:00:00"
}
```

#### `POST /auth/login`
Login and receive JWT token.

**Request Body:**
```json
{
  "email": "admin@example.com",
  "password": "SecurePass123!"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

---

### Job Endpoints

#### `GET /jobs/`
List all jobs for the authenticated user's company.

**Query Parameters:** None

**Response:**
```json
[
  {
    "id": 1,
    "company_id": 1,
    "title": "Senior Python Developer",
    "description": "Join our team...",
    "min_experience": 5,
    "required_skills": ["Python", "FastAPI", "SQL"],
    "is_active": true
  }
]
```

**Security:** ✅ Filtered by `company_id`

---

#### `POST /jobs/`
Create a new job posting.

**Request Body:**
```json
{
  "title": "Senior Python Developer",
  "description": "We are looking for...",
  "min_experience": 5,
  "required_skills": ["Python", "FastAPI", "SQL"]
}
```

**Response:** Job object with auto-assigned `company_id`

**Security:** ✅ `company_id` injected from JWT, never from client

---

#### `GET /jobs/{job_id}`
Get a specific job by ID.

**Path Parameters:**
- `job_id` (int): Job ID

**Response:** Job object

**Security:** ✅ Returns 404 if job doesn't belong to user's company

---

#### `PUT /jobs/{job_id}`
Update a job. **Admin only.**

**Request Body:**
```json
{
  "title": "Updated Title",
  "min_experience": 6,
  "is_active": false
}
```

**Response:** Updated job object

**Security:** ✅ Admin-only, company-scoped

---

#### `PATCH /jobs/{job_id}/status`
Toggle job active/inactive status. **Admin only.**

**Response:** Updated job object

**Security:** ✅ Admin-only, company-scoped

---

#### `DELETE /jobs/{job_id}`
Delete a job. **Admin only.**

**Response:** 204 No Content

**Security:** ✅ Admin-only, company-scoped

---

#### `GET /jobs/{job_id}/stats`
Get statistics for a specific job.

**Response:**
```json
{
  "job_id": 1,
  "job_title": "Senior Python Developer",
  "total_applicants": 50,
  "shortlisted": 10,
  "under_review": 15,
  "rejected": 20,
  "interviewed": 3,
  "hired": 2,
  "average_score": 72.4
}
```

**Security:** ✅ Company-scoped

---

#### `GET /jobs/dashboard/stats`
Get overall dashboard statistics for the company.

**Response:**
```json
{
  "total_jobs": 5,
  "active_jobs": 3,
  "total_applicants": 150,
  "shortlisted_applicants": 25,
  "pending_review": 40,
  "recent_applicants": [...]
}
```

**Security:** ✅ Company-scoped

---

### Applicant Endpoints

#### `POST /applicants/apply/{job_id}`
Submit a resume for a job (public endpoint - no auth required).

**Path Parameters:**
- `job_id` (int): Job ID to apply for

**Form Data:**
- `file` (PDF): Resume file

**Response:**
```json
{
  "message": "Application received",
  "score": 85,
  "status": "shortlisted"
}
```

**Security:** ✅ Applicant inherits `company_id` from parent job

---

#### `GET /applicants/`
List all applicants for the user's company.

**Query Parameters:**
- `job_id` (optional, int): Filter by job
- `status_filter` (optional, str): Filter by status

**Response:** Array of applicant objects

**Security:** ✅ Filtered by `company_id`

---

#### `GET /applicants/{applicant_id}`
Get detailed information about an applicant.

**Response:**
```json
{
  "id": 1,
  "job_id": 1,
  "company_id": 1,
  "name": "John Doe",
  "email": "john@example.com",
  "phone": "+1234567890",
  "years_experience": 6,
  "skills": ["Python", "FastAPI", "PostgreSQL"],
  "match_score": 85,
  "summary": "Score: 85 (Exp:9/10, Skill:8/10, Impact:7/10)...",
  "status": "shortlisted",
  "resume_text": "Full resume text..."
}
```

**Security:** ✅ Returns 404 if applicant doesn't belong to user's company

---

#### `PUT /applicants/{applicant_id}/status`
Update an applicant's status.

**Request Body:**
```json
{
  "status": "interviewed"
}
```

**Valid statuses:** `new`, `rejected`, `shortlisted`, `review`, `interviewed`, `hired`

**Response:** Updated applicant object

**Security:** ✅ Company-scoped

---

#### `PUT /applicants/bulk/status`
Bulk update multiple applicants' statuses.

**Request Body:**
```json
{
  "applicant_ids": [1, 2, 3, 4, 5],
  "status": "rejected"
}
```

**Response:**
```json
{
  "message": "Successfully updated 5 applicants",
  "updated_count": 5,
  "requested_count": 5,
  "new_status": "rejected"
}
```

**Security:** ✅ Only updates applicants belonging to user's company

---

#### `DELETE /applicants/{applicant_id}`
Delete an applicant. **Admin only.**

**Response:** 204 No Content

**Security:** ✅ Admin-only, company-scoped

---

### Bulk Processing Endpoints

#### `POST /api/bulk-screen`
Upload a ZIP file of resumes for bulk screening.

**Form Data:**
- `resumes_zip` (file): ZIP file containing PDF resumes
- `job_description` (text): Full job description
- `min_experience` (float): Minimum years of experience
- `required_skills` (text): Comma-separated skills (e.g., "Python,FastAPI,SQL")

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Processing started",
  "total_resumes": 50
}
```

**Security:** ✅ Job and applicants auto-assigned to user's `company_id`

---

#### `GET /api/job/{job_id}`
Get the status of a bulk processing job.

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "company_id": 1,
  "status": "completed",
  "total_resumes": 50,
  "processed": 50,
  "created_at": "2026-02-22T10:00:00",
  "updated_at": "2026-02-22T10:15:00",
  "results": {
    "total_processed": 50,
    "shortlisted_count": 12,
    "rejected_count": 38,
    ...
  }
}
```

**Security:** ✅ Returns 403 if job doesn't belong to user's company

---

#### `GET /api/jobs`
List all bulk processing jobs for the user's company.

**Response:**
```json
{
  "jobs": [...],
  "total": 5
}
```

**Security:** ✅ Filtered by `company_id`

---

## 🔒 Security Features

### 1. Tenant Isolation
- All database queries filtered by `company_id`
- JWT tokens contain `company_id` claim
- Cross-tenant access attempts return 403/404

### 2. Authorization
- Role-based access control (admin/recruiter)
- Admin-only operations (delete, update jobs)
- JWT-based authentication

### 3. Audit Logging
- All requests logged with user/company context
- Security events tracked
- Request/response logging middleware

### 4. Security Headers
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Strict-Transport-Security`

### 5. Input Validation
- Pydantic schemas for all inputs
- File type validation (PDF only)
- Status value validation

---

## 🧪 Testing

Run the tenant isolation test suite:
```bash
python -m pytest test_tenant_isolation.py -v
```

Key test scenarios:
- ✅ Users can only see their company's jobs
- ✅ Users cannot access other companies' applicants
- ✅ Job tracker enforces tenant isolation
- ✅ Bulk updates only affect user's company data

---

## 🚀 Getting Started

1. Register a new account: `POST /auth/register`
2. Login: `POST /auth/login`
3. Create a job: `POST /jobs/`
4. View applicants: `GET /applicants/?job_id={job_id}`
5. Update statuses: `PUT /applicants/{id}/status`

---

## ⚠️ Important Notes

- **Never send `company_id` from the client** - it's always injected from the JWT
- **All endpoints require authentication** except:
  - `POST /applicants/apply/{job_id}` (public job application)
  - `GET /login` (login page)
  - `GET /api/health` (health check)
- **Admin users** can delete and modify jobs/applicants
- **Recruiter users** can view and update applicant statuses only
