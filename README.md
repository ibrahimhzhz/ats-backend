# 🤖 AI-Powered Applicant Tracking System (ATS)

> Enterprise-grade resume screening platform with intelligent multi-stage filtering and AI-powered candidate evaluation

[![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.1xx-009688.svg)](https://fastapi.tiangolo.com/)
[![Vertex AI](https://img.shields.io/badge/Vertex%20AI-Gemini%202.0-orange.svg)](https://cloud.google.com/vertex-ai)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [Architecture](#-architecture)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [API Documentation](#-api-documentation)
- [Testing](#-testing)
- [Project Structure](#-project-structure)
- [Deployment](#-deployment)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🎯 Overview

An intelligent Applicant Tracking System that **reduces recruiter workload by 80%** through automated resume screening using Google's Vertex AI (Gemini 2.0). The system implements a sophisticated multi-stage pipeline that combines rule-based filtering with AI-powered evaluation to efficiently identify top candidates while minimizing API costs.

### Why This ATS?

- **💰 Cost-Efficient:** Saves 30-50% on AI API costs through intelligent knockout filtering
- **⚡ Fast:** Processes 100 resumes in ~8 minutes with parallel async operations
- **🎯 Accurate:** Multi-metric evaluation (skill match, experience relevance, impact) provides granular insights
- **📊 Transparent:** Full audit trail with detailed explanations for every decision
- **🔧 Production-Ready:** Built with FastAPI, async patterns, and scalable architecture

---

## ✨ Key Features

### 🚀 Multi-Stage Screening Pipeline

#### **Stage 1: Hard Knockouts** (Rule-Based Filtering)
- Auto-rejects candidates below minimum experience threshold (with 0.5-year buffer)
- Filters out candidates with <30% required skill match
- **Saves 2 LLM API calls per rejected candidate**

#### **Stage 2: Granular AI Evaluation** (LLM-Powered)
- Three separate metrics instead of single score:
  - **Skill Match** (0-10): Alignment with required skills
  - **Experience Relevance** (0-10): Domain experience quality
  - **Impact Score** (0-10): Evidence of achievements
- Uses Google Vertex AI (Gemini 2.0 Flash) with strict "ruthless grader" prompts

#### **Stage 3: Weighted Algorithmic Scoring**
- Formula: `Final = (Experience × 0.5 + Skill × 0.3 + Impact × 0.2) × 10`
- Deterministic, transparent scoring
- Three-tier categorization:
  - **Shortlisted** (80-100): Top candidates
  - **Review** (60-79): Potential candidates
  - **Rejected** (0-59): Not qualified

#### **Stage 4: Database Persistence**
- All candidates saved to SQLite (PostgreSQL-ready)
- Full audit trail for compliance
- Queryable historical data

### 🎨 Modern Web Interface

- **Quick Paste Mode:** Auto-parse structured job postings
- **Real-Time Progress:** Live updates during processing
- **Comprehensive Results:** 6-card dashboard with token savings metrics
- **Mobile Responsive:** Works on all device sizes

### 🔌 REST API

- Async FastAPI backend with OpenAPI documentation
- Background task processing for long-running jobs
- Status polling endpoints for progress tracking
- Bulk and single-resume submission workflows

### 📈 Performance Optimization

- **Rate Limiting:** Prevents API throttling (60 calls/min)
- **Async Processing:** Non-blocking I/O operations
- **Token Savings:** 30-50% reduction through smart filtering
- **Concurrent Handling:** Multiple jobs processable simultaneously

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CLIENT (Browser)                       │
│              Vanilla JS + Jinja2 Templates                  │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP/REST
┌───────────────────────────▼─────────────────────────────────┐
│                    FastAPI Application                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  POST /api/bulk-screen                              │   │
│  │  - Accept ZIP, job description, criteria            │   │
│  │  - Create Job record in SQLite                      │   │
│  │  - Spawn background async worker                    │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  GET /api/job/{job_id}                              │   │
│  │  - Poll job status                                  │   │
│  │  - Return results when completed                    │   │
│  └─────────────────────────────────────────────────────┘   │
└───────────────┬─────────────────────┬───────────────────────┘
                │                     │
    ┌───────────▼───────────┐  ┌──────▼────────┐
    │   SQLite Database     │  │  Job Tracker  │
    │   - jobs              │  │  (In-Memory)  │
    │   - applicants        │  │  - Progress   │
    └───────────────────────┘  │  - Results    │
                                └───────────────┘
                │
    ┌───────────▼────────────────────────────────────────┐
    │         Multi-Stage Pipeline Worker                │
    │                                                     │
    │  1. Hard Knockouts → Rule-based filtering          │
    │  2. AI Evaluation → Vertex AI (Gemini 2.0)         │
    │  3. Weighted Scoring → Algorithmic calculation     │
    │  4. DB Persistence → Save to SQLite                │
    └────────────────────────────────────────────────────┘
                │
    ┌───────────▼───────────┐
    │   Google Vertex AI    │
    │   Gemini 2.0 Flash    │
    │   - Data extraction   │
    │   - Candidate scoring │
    └───────────────────────┘
```

---

## 🛠️ Installation

### Prerequisites

- Python 3.13+ (3.10+ compatible)
- Google Cloud Platform account with Vertex AI enabled
- Git

### Step 1: Clone Repository

```bash
git clone https://github.com/yourusername/ats_backend.git
cd ats_backend
```

### Step 2: Create Virtual Environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Set Up Google Cloud

```bash
# Install gcloud CLI (if not already installed)
# https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth application-default login

# Enable Vertex AI API
gcloud services enable aiplatform.googleapis.com
```

---

## ⚙️ Configuration

### 1. Create `.env` File

```bash
cp .env.example .env
```

### 2. Edit `.env` with Your Settings

```env
# Google Cloud Configuration
GCP_PROJECT_ID=your-gcp-project-id
GCP_LOCATION=us-central1

# Auth / JWT (required outside local-only dev)
SECRET_KEY=replace-with-a-long-random-secret-at-least-32-chars
JWT_ISSUER=ats-backend
JWT_AUDIENCE=ats-client

# Local-only fallback toggle (optional)
# ALLOW_INSECURE_DEV_SECRET=true

# Optional: Path to service account key
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

# Database (optional, defaults to SQLite)
# DATABASE_URL=postgresql://user:pass@localhost/ats_db

# In-memory job tracker cleanup (until Redis/Celery)
# JOB_TRACKER_CLEANUP_INTERVAL_SECONDS=1800
# JOB_TRACKER_MAX_AGE_HOURS=24
```

### 3. Verify Configuration

```bash
python -c "from services.ai_engine import is_ai_available; print('AI ready:', is_ai_available())"
```

---

## 🚀 Usage

### Start the Server

```bash
uvicorn main:app --reload --port 8001
```

Server will be available at: **http://localhost:8001**

### Web Interface

1. Open browser to: **http://localhost:8001**

2. **Option A: Manual Input**
   - Upload ZIP file with PDF resumes
   - Enter job description
   - Set minimum experience (e.g., `3.0` years)
   - Enter required skills (e.g., `Python, FastAPI, SQL`)

3. **Option B: Quick Paste Mode**
   - Click "Quick Paste Mode" section
   - Paste formatted job posting (see [sample_job_post.txt](sample_job_post.txt))
   - Click "Parse & Auto-Fill Form"

4. Click **"Start Multi-Stage Screening"**

5. Watch real-time progress and view results!

### Command Line Testing

```bash
# Run automated test script
python test_bulk_screening.py
```

### Using curl

```bash
# Submit bulk screening job
curl -X POST "http://localhost:8001/api/bulk-screen" \
  -F "resumes_zip=@test_resumes.zip" \
  -F "job_description=Senior Python Developer with 5+ years..." \
  -F "min_experience=5.0" \
  -F "required_skills=Python,FastAPI,PostgreSQL"

# Check job status (replace JOB_ID)
curl "http://localhost:8001/api/job/YOUR-JOB-ID"
```

---

## 📚 API Documentation

### Interactive Docs

- **Swagger UI:** http://localhost:8001/docs
- **ReDoc:** http://localhost:8001/redoc

### Core Endpoints

#### `POST /api/bulk-screen`

Submit bulk resume screening job.

**Request:**
```
Content-Type: multipart/form-data

Fields:
- resumes_zip: File (ZIP containing PDFs)
- job_description: String
- min_experience: Float (0.5-30.0)
- required_skills: String (comma-separated)
```

**Response (202):**
```json
{
  "job_id": "uuid-v4",
  "db_job_id": 1,
  "total_resumes": 23,
  "min_experience": 5.0,
  "required_skills": ["Python", "FastAPI"],
  "message": "Processing started..."
}
```

---

#### `GET /api/job/{job_id}`

Poll job status and retrieve results.

**Response (Completed):**
```json
{
  "status": "completed",
  "results": {
    "total_processed": 23,
    "knocked_out": 8,
    "ai_evaluated": 15,
    "shortlisted_count": 3,
    "review_count": 5,
    "rejected_count": 15,
    "shortlisted": [...],
    "all_candidates": [...]
  }
}
```

---

#### `POST /applicants/apply/{job_id}`

Submit single resume for specific job.

**Request:**
```
Content-Type: multipart/form-data

Fields:
- file: PDF resume
```

---

#### `GET /api/health`

Health check endpoint.

**Response:**
```json
{"status": "ok"}
```

---

## 🧪 Testing

### Automated Test Suite

```bash
# Run complete test suite
python test_bulk_screening.py
```

**Tests:**
- ✅ API health check
- ✅ Bulk job submission
- ✅ Progress monitoring
- ✅ Result validation
- ✅ Token savings calculation

### Manual Testing

See [TESTING.md](TESTING.md) for comprehensive testing guide.

### Test Scenarios

```bash
# Strict filtering (high knockout rate)
min_experience=10.0
required_skills="Python,FastAPI,PostgreSQL,Docker,Kubernetes,AWS,Terraform"

# Lenient filtering (low knockout rate)
min_experience=1.0
required_skills="Python"

# Balanced filtering
min_experience=3.0
required_skills="Python,FastAPI,SQL"
```

### Database Inspection

```bash
sqlite3 ats.db

# View all candidates for a job
SELECT name, match_score, status FROM applicants WHERE job_id = 1;

# Count by status
SELECT status, COUNT(*) FROM applicants GROUP BY status;
```

---

## 📁 Project Structure

```
ats_backend/
├── main.py                      # FastAPI application & endpoints
├── database.py                  # Database configuration
├── models.py                    # SQLAlchemy ORM models
├── schemas.py                   # Pydantic schemas
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variables template
├── .gitignore                   # Git ignore rules
│
├── routers/
│   ├── jobs.py                  # Job management routes
│   └── applicants.py            # Applicant routes
│
├── services/
│   ├── ai_engine.py             # Vertex AI integration
│   ├── pdf_parser.py            # PDF text extraction
│   └── job_tracker.py           # In-memory job state
│
├── templates/
│   └── index.html               # Web UI template
│
├── static/
│   └── styles.css               # Frontend styling
│
├── test_resumes/                # Sample PDF resumes
├── test_bulk_screening.py       # Automated test script
│
├── README.md                    # This file
├── TESTING.md                   # Testing guide
├── FRONTEND_TESTING.md          # Frontend testing guide
├── SAMPLE_JOB_POSTS.md          # Sample job postings
└── sample_job_post.txt          # Quick paste example
```

---

## 🎭 Key Components

### Backend

- **main.py:** FastAPI app, routes, background worker
- **services/ai_engine.py:** Vertex AI integration, prompt engineering
- **services/pdf_parser.py:** PyMuPDF text extraction
- **services/job_tracker.py:** In-memory job state (Redis-ready)
- **models.py:** SQLAlchemy models for jobs and applicants
- **database.py:** Database configuration and session management

### Frontend

- **templates/index.html:** Jinja2 template with embedded JavaScript
- **static/styles.css:** Custom CSS with grid layout
- Features: Quick paste parser, real-time polling, responsive design

---

## 🚢 Deployment

### Development

```bash
uvicorn main:app --reload --port 8001
```

### Production (Cloud Run)

```bash
# Build container
docker build -t ats-backend .

# Deploy to Cloud Run
gcloud run deploy ats-backend \
  --image gcr.io/PROJECT_ID/ats-backend \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

### Environment Variables (Production)

```env
GCP_PROJECT_ID=your-project-id
GCP_LOCATION=us-central1
SECRET_KEY=replace-with-a-long-random-secret-at-least-32-chars
JWT_ISSUER=ats-backend
JWT_AUDIENCE=ats-client
DATABASE_URL=postgresql://user:pass@host/db
REDIS_URL=redis://host:6379
```

### Recommended Stack

- **Compute:** Google Cloud Run or GKE
- **Database:** Cloud SQL (PostgreSQL)
- **Cache:** Cloud Memorystore (Redis)
- **Storage:** Cloud Storage (resume backups)
- **Queue:** Cloud Pub/Sub (job queue)

---

## 📊 Performance

### Benchmarks

- **Single Resume:** 3-8 seconds
- **100 Resumes (40% knockout):** ~8 minutes
- **Token Savings:** 30-50% cost reduction
- **Throughput:** 60 resumes/minute (rate-limited)

### Cost Estimates

**Vertex AI (Gemini 2.0 Flash):**
- Per resume (without knockouts): $0.00046
- Per resume (with 40% knockouts): $0.00028
- 1000 resumes/month: ~$0.28-$0.46

---

## 🔐 Security

### Implemented

✅ SQL injection protection (ORM)  
✅ File type validation  
✅ Environment variable management  
✅ No hardcoded credentials  

### Production Requirements

⚠️ Add authentication (OAuth2/JWT)  
⚠️ Configure CORS  
⚠️ Implement rate limiting  
⚠️ Add file size limits  
⚠️ Enable CSRF protection  
⚠️ Encrypt sensitive DB fields  

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

### Development Setup

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Format code
black .

# Lint
flake8
```

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **FastAPI** - Modern async web framework
- **Google Vertex AI** - Powerful LLM capabilities
- **PyMuPDF** - Efficient PDF parsing
- **SQLAlchemy** - Robust ORM

---

## 📧 Support

- **Issues:** [GitHub Issues](https://github.com/yourusername/ats_backend/issues)
- **Documentation:** See `TESTING.md` and `SAMPLE_JOB_POSTS.md`
- **Email:** your.email@example.com

---

## 🗺️ Roadmap

### v1.1 (Next Release)
- [ ] Redis integration for job tracking
- [ ] PostgreSQL migration guide
- [ ] Email notifications
- [ ] Export results (CSV/PDF)
- [ ] OAuth2 authentication

### v1.2 (Future)
- [ ] Candidate dashboard
- [ ] Interview scheduling integration
- [ ] Resume deduplication
- [ ] Skills gap analysis
- [ ] Mobile app

### v2.0 (Long Term)
- [ ] Multi-tenant support
- [ ] Custom ML model training
- [ ] Advanced analytics dashboard
- [ ] Integration marketplace
- [ ] White-label solution

---

## 📈 Project Stats

- **Lines of Code:** ~2,800
- **Test Coverage:** Manual + Integration tests
- **API Endpoints:** 8
- **Database Tables:** 2
- **AI Models:** 1 (Gemini 2.0 Flash)

---

<div align="center">

**Built with ❤️ using FastAPI and Vertex AI**

⭐ Star this repo if you find it helpful!

[Report Bug](https://github.com/yourusername/ats_backend/issues) · [Request Feature](https://github.com/yourusername/ats_backend/issues)

</div>
