# 🔒 Security Hardening Checklist

## ✅ Implemented Security Measures

### 1. Multi-Tenant Data Isolation
- [x] All Job queries filtered by `company_id`
- [x] All Applicant queries filtered by `company_id`
- [x] Job Tracker stores and validates `company_id`
- [x] Cross-tenant access returns 403 Forbidden
- [x] `company_id` injected from JWT, never from client input

### 2. Authentication & Authorization
- [x] JWT-based authentication
- [x] Password hashing with bcrypt
- [x] Token expiration (configurable in `services/auth.py`)
- [x] Role-based access control (admin/recruiter)
- [x] Protected endpoints with `Depends(get_current_user)`

### 3. Input Validation
- [x] Pydantic schemas for all request bodies
- [x] File type validation (PDF only)
- [x] Status value validation (whitelist)
- [x] Email validation with EmailStr
- [x] SQL injection prevention (SQLAlchemy ORM)

### 4. API Security
- [x] Security headers middleware
- [x] CORS configuration
- [x] Request/response logging
- [x] Error handling (no sensitive data in errors)

### 5. Audit Trail
- [x] All requests logged with user context
- [x] Security events logged
- [x] Timestamp on all database records

---

## 🔧 Additional Hardening Recommendations

### High Priority

#### 1. Rate Limiting
Add rate limiting to prevent abuse:

```python
# Install: pip install slowapi
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# On endpoints:
@app.post("/auth/login")
@limiter.limit("5/minute")  # 5 attempts per minute
async def login(...):
    ...
```

#### 2. Password Policy
Enhance password requirements:

```python
from pydantic import validator
import re

class UserCreate(BaseModel):
    password: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 12:
            raise ValueError('Password must be at least 12 characters')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain lowercase letter')
        if not re.search(r'[0-9]', v):
            raise ValueError('Password must contain digit')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError('Password must contain special character')
        return v
```

#### 3. Environment Variables
Move secrets to environment variables:

Create `.env` file:
```bash
SECRET_KEY=your-super-secret-key-here-at-least-32-chars
DATABASE_URL=postgresql://user:pass@localhost/atsdb
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
GOOGLE_VERTEX_PROJECT=your-project-id
GOOGLE_VERTEX_LOCATION=us-central1
```

Update code:
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    secret_key: str
    database_url: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    class Config:
        env_file = ".env"

settings = Settings()
```

#### 4. HTTPS Enforcement
```python
# Add to middleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

if os.getenv("ENVIRONMENT") == "production":
    app.add_middleware(HTTPSRedirectMiddleware)
```

#### 5. Database Connection Pooling
```python
# In database.py
from sqlalchemy.pool import QueuePool

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True  # Verify connections before use
)
```

### Medium Priority

#### 6. API Key for Public Endpoints
For the public `/applicants/apply/{job_id}` endpoint, consider adding honeypot protection:

```python
@router.post("/apply/{job_id}")
async def apply_for_job(
    job_id: int,
    file: UploadFile = File(...),
    honeypot: str = Form(None),  # Hidden field
    db: Session = Depends(get_db)
):
    # If honeypot is filled, it's likely a bot
    if honeypot:
        raise HTTPException(status_code=400, detail="Invalid submission")
    ...
```

#### 7. File Size Limits
```python
from fastapi import UploadFile

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

@router.post("/apply/{job_id}")
async def apply_for_job(
    file: UploadFile = File(...),
    ...
):
    # Check file size
    file_size = 0
    chunk_size = 1024 * 1024  # 1MB chunks
    
    for chunk in file.file:
        file_size += len(chunk)
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="File too large. Maximum size is 10MB"
            )
```

#### 8. Background Job Cleanup
```python
# Add scheduled task to clean old jobs
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('cron', hour=2)  # Run at 2 AM daily
def cleanup_old_jobs():
    job_tracker.cleanup_old_jobs(max_age_hours=24)

scheduler.start()
```

#### 9. SQL Query Logging (Development Only)
```python
# In database.py
import logging

if os.getenv("ENVIRONMENT") == "development":
    logging.basicConfig()
    logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

#### 10. Content Security Policy
```python
# Add to SecurityHeadersMiddleware
response.headers["Content-Security-Policy"] = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline';"
)
```

---

## 🚨 Pre-Production Checklist

Before deploying to production:

- [ ] Change `SECRET_KEY` in `services/auth.py` to a secure random value
- [ ] Set `ACCESS_TOKEN_EXPIRE_MINUTES` to reasonable value (30-60 minutes)
- [ ] Enable HTTPS only (no HTTP)
- [ ] Update CORS `allow_origins` to production frontend URL only
- [ ] Set up database backups
- [ ] Configure log rotation
- [ ] Set up monitoring (Sentry, DataDog, etc.)
- [ ] Enable rate limiting
- [ ] Review all error messages (no sensitive data leakage)
- [ ] Test all tenant isolation scenarios
- [ ] Set up WAF (Web Application Firewall)
- [ ] Configure DDoS protection
- [ ] Enable database encryption at rest
- [ ] Set up SSL/TLS certificates
- [ ] Review and lock down firewall rules
- [ ] Disable debug mode
- [ ] Set up automated security scanning
- [ ] Configure alerting for suspicious activity

---

## 🧪 Security Testing

### 1. Run Tenant Isolation Tests
```bash
python -m pytest test_tenant_isolation.py -v
```

### 2. Manual Security Testing

#### Test Cross-Tenant Access
```bash
# Get token for Company A
TOKEN_A=$(curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@companya.com","password":"pass123"}' \
  | jq -r '.access_token')

# Get token for Company B
TOKEN_B=$(curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@companyb.com","password":"pass123"}' \
  | jq -r '.access_token')

# Try to access Company B's job with Company A's token (should fail)
curl -X GET "http://localhost:8000/jobs/2" \
  -H "Authorization: Bearer $TOKEN_A"
# Expected: 404 Not Found or 403 Forbidden
```

#### Test Authorization
```bash
# Try to delete without admin role (should fail)
curl -X DELETE "http://localhost:8000/jobs/1" \
  -H "Authorization: Bearer $RECRUITER_TOKEN"
# Expected: 403 Forbidden
```

### 3. Automated Security Scanning
```bash
# Install OWASP ZAP or use online tools
# Run vulnerability scans against your API
```

---

## 📊 Monitoring & Alerting

Set up alerts for:
- Multiple failed login attempts
- Cross-tenant access attempts (403 errors)
- Unusual API usage patterns
- Database query performance issues
- High error rates
- Unexpected data access patterns

---

## 🔄 Incident Response Plan

1. **Detection**: Monitor logs for security events
2. **Containment**: Revoke JWT tokens if compromised
3. **Investigation**: Review audit logs
4. **Recovery**: Restore from backups if needed
5. **Post-Mortem**: Document and improve

---

## 📚 References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Multi-Tenant Best Practices](https://docs.microsoft.com/en-us/azure/architecture/guide/multitenant/overview)
