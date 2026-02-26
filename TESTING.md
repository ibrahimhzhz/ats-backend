# Testing Guide for Multi-Stage ATS Pipeline

## Quick Start

### 1. Start the Server
```powershell
# Make sure you're in the project directory and venv is activated
uvicorn main:app --reload --port 8001
```

Server will be available at: **http://localhost:8001**

---

## Automated Testing

### Run the Test Script

```powershell
# Install requests if not already installed
pip install requests

# Run the automated test
python test_bulk_screening.py
```

The script will:
- ✅ Check if API is running
- ✅ Submit a bulk screening job with strict criteria
- ✅ Monitor progress in real-time
- ✅ Display detailed results with token savings

---

## Manual Testing

### Option 1: Using PowerShell

#### Step 1: Create test ZIP (if you don't have one)
```powershell
# If you have a test_resumes folder with PDFs
Compress-Archive -Path 'test_resumes\*.pdf' -DestinationPath 'test_resumes.zip' -Force
```

#### Step 2: Submit screening request
```powershell
$boundary = [System.Guid]::NewGuid().ToString()
$uri = "http://localhost:8001/api/bulk-screen"

# Prepare multipart form data
$filePath = "test_resumes.zip"
$jobDescription = "Senior Python Developer with 5+ years experience. Must have FastAPI and PostgreSQL skills."
$minExperience = "5.0"
$requiredSkills = "Python,FastAPI,PostgreSQL,Docker,AWS"

# Using curl (easier)
curl -X POST "http://localhost:8001/api/bulk-screen" `
  -F "resumes_zip=@test_resumes.zip" `
  -F "job_description=$jobDescription" `
  -F "min_experience=$minExperience" `
  -F "required_skills=$requiredSkills"
```

#### Step 3: Check job status
```powershell
# Replace JOB_ID with the job_id from the response
$jobId = "your-job-id-here"
curl "http://localhost:8001/api/job/$jobId" | ConvertFrom-Json | ConvertTo-Json -Depth 10
```

---

### Option 2: Using the Web UI

1. Open browser to: **http://localhost:8001**
2. The HTML form needs to be updated to include new fields (see below)

---

### Option 3: Using Postman

1. Create a new POST request to: `http://localhost:8001/api/bulk-screen`

2. In **Body** tab, select **form-data**

3. Add these fields:
   - Key: `resumes_zip` | Type: File | Value: [Select your ZIP file]
   - Key: `job_description` | Type: Text | Value: Your job description
   - Key: `min_experience` | Type: Text | Value: `5.0`
   - Key: `required_skills` | Type: Text | Value: `Python,FastAPI,PostgreSQL`

4. Click **Send**

5. Copy the `job_id` from response

6. Create a GET request to: `http://localhost:8001/api/job/{job_id}`

7. Keep clicking Send to monitor progress

---

## Testing Different Scenarios

### Scenario 1: Strict Filtering (Many Knockouts)
```python
min_experience = 10.0  # Very high
required_skills = "Python,FastAPI,PostgreSQL,Docker,Kubernetes,AWS,Terraform,Go"  # Many skills

# Expected: High knockout rate, low AI evaluation cost
```

### Scenario 2: Lenient Filtering (Few Knockouts)
```python
min_experience = 1.0  # Low barrier
required_skills = "Python"  # Just one skill

# Expected: Low knockout rate, most candidates AI-evaluated
```

### Scenario 3: Balanced Filtering
```python
min_experience = 3.0
required_skills = "Python,FastAPI,SQL"

# Expected: Moderate knockout rate
```

---

## What to Look For

### ✅ Success Indicators

1. **Stage 1 - Knockouts Working:**
   ```json
   {
     "knocked_out": 8,
     "ai_evaluated": 15
   }
   ```
   If `knocked_out > 0`, rule-based filtering is working!

2. **Stage 2 - AI Granular Metrics:**
   Check candidate summaries contain 3 scores:
   ```
   "Score: 73.0 (Exp:8/10, Skill:7/10, Impact:6/10). Strong Python..."
   ```

3. **Stage 3 - Weighted Scoring:**
   Scores should be decimal values (not just 0-100 integers):
   ```json
   {"match_score": 67.5}
   ```

4. **Stage 4 - Database Persistence:**
   ```sql
   -- Check if candidates were saved
   SELECT COUNT(*) FROM applicants WHERE job_id = 1;
   ```

### ⚠️ Warning Signs

- All candidates have score 0 → Knockout logic too strict
- No candidates in `knocked_out` → Rules not applying
- Scores all near 90-100 → AI prompt not harsh enough
- Database empty → Transaction not committing

---

## Checking the Database

```powershell
# Open SQLite database
sqlite3 ats.db

# View all jobs
SELECT * FROM jobs;

# View applicants for a specific job
SELECT id, name, email, match_score, status FROM applicants WHERE job_id = 1;

# Count by status
SELECT status, COUNT(*) as count FROM applicants WHERE job_id = 1 GROUP BY status;

# View shortlisted candidates
SELECT name, email, match_score, summary FROM applicants 
WHERE job_id = 1 AND status = 'shortlisted' 
ORDER BY match_score DESC;

# Exit
.quit
```

---

## Expected API Response Format

### Successful Submission
```json
{
  "job_id": "8f3e9c7a-1b2c-4d5e-9f8a-7b6c5d4e3f2a",
  "db_job_id": 1,
  "total_resumes": 23,
  "min_experience": 5.0,
  "required_skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"],
  "message": "Processing started. Use the job_id to check progress."
}
```

### Status Check (Processing)
```json
{
  "id": "8f3e9c7a-1b2c-4d5e-9f8a-7b6c5d4e3f2a",
  "status": "processing",
  "total_resumes": 23,
  "processed": 15,
  "created_at": "2026-02-20T10:30:00",
  "results": null
}
```

### Status Check (Completed)
```json
{
  "id": "8f3e9c7a-1b2c-4d5e-9f8a-7b6c5d4e3f2a",
  "status": "completed",
  "total_resumes": 23,
  "processed": 23,
  "results": {
    "total_processed": 23,
    "knocked_out": 8,
    "ai_evaluated": 15,
    "shortlisted_count": 3,
    "review_count": 5,
    "rejected_count": 15,
    "criteria": {
      "min_experience": 5.0,
      "required_skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"]
    },
    "shortlisted": [...],
    "all_candidates": [...]
  }
}
```

---

## Performance Benchmarks

For 100 resumes:

**Without Knockouts (Old System):**
- API Calls: 200 (2 per resume)
- Time: ~200 seconds (with rate limiting)

**With 40% Knockout Rate (New System):**
- API Calls: 120 (40 skipped, 60 × 2)
- Time: ~120 seconds
- **Savings: 40% time and cost**

---

## Troubleshooting

### "Connection Error"
```
✅ Make sure server is running: uvicorn main:app --reload --port 8001
✅ Check port 8001 is not blocked
```

### "No PDF files found in ZIP"
```
✅ ZIP must contain PDF files at root level
✅ Test: unzip and check file extensions
```

### "GCP_PROJECT_ID not found"
```
✅ Update .env file with your Google Cloud project
✅ GCP_PROJECT_ID=your-project-id
```

### "No candidates passed knockout"
```
✅ Reduce min_experience
✅ Reduce number of required_skills
✅ Check resume quality (years of experience present?)
```

### "All candidates scored 0"
```
✅ Check if AI extraction is working
✅ Look for "VERTEX AI EXTRACTION FAILED" in logs
✅ Verify API credentials
```

---

## Next Steps After Testing

1. **Update the Web UI** to include new form fields
2. **Add authentication** for production use
3. **Set up job queuing** with Redis/Celery for scale
4. **Add email notifications** when processing completes
5. **Create candidate dashboard** to view results
