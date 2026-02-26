# Frontend Testing Guide

## ✅ The Frontend is Ready!

Your HTML interface has been upgraded to support the multi-stage pipeline.

---

## How to Test on the Frontend

### 1. Make Sure Server is Running

```powershell
# In your terminal
uvicorn main:app --reload --port 8001
```

Server should show:
```
INFO:     Uvicorn running on http://127.0.0.1:8001 (Press CTRL+C to quit)
```

---

### 2. Open the Web Interface

Open your browser and go to: **http://localhost:8001**

---

### 3. Fill Out the Form

You'll now see **4 input fields**:

#### **1. ZIP File with Resumes**
- Click "Choose File" and select your `test_resumes.zip`
- Must contain PDF files

#### **2. Job Description**
```
Example:
Senior Backend Engineer

We need an experienced Python developer to build scalable APIs.

Requirements:
- 5+ years Python development
- FastAPI or Django experience
- PostgreSQL knowledge
- Docker and cloud experience
```

#### **3. Minimum Experience (Years)**
```
Example: 5.0
```
- Use decimals (e.g., 3.5 for 3.5 years)
- Candidates below this (minus 0.5 year buffer) get auto-rejected
- Try different values: 1.0 (lenient), 5.0 (balanced), 10.0 (strict)

#### **4. Required Skills**
```
Example: Python,FastAPI,PostgreSQL,Docker,AWS
```
- Comma-separated list
- Case-insensitive matching
- Candidates need 30%+ match to pass knockout stage

---

### 4. Submit and Watch

Click **"🚀 Start Multi-Stage Screening"**

You'll see:
1. **Progress bar** updating in real-time
2. **Processing status**: "Processing 5 of 23 resumes (22%)..."

---

### 5. View Results

Once complete, you'll see a comprehensive dashboard:

#### **📊 Statistics (6 Cards)**
```
┌─────────────┬─────────────┬─────────────┬─────────────┬─────────────┬─────────────┐
│   Total     │  Knocked    │     AI      │ Shortlisted │   Review    │  Rejected   │
│ Processed   │    Out      │  Evaluated  │   (80+)     │  (60-79)    │   (<60)     │
│     23      │      8      │     15      │      3      │      5      │     15      │
└─────────────┴─────────────┴─────────────┴─────────────┴─────────────┴─────────────┘
```

#### **💰 Token Savings**
```
💰 Token Savings: Saved 16 LLM calls by knockout filtering (35% API cost reduction)
```

#### **✅ Shortlisted Candidates (80+)**
- Green cards with scores 80-100
- Full candidate details with 3-metric breakdown
- Example: "Score: 83.5 (Exp:9/10, Skill:8/10, Impact:7/10)"

#### **⚠️ Needs Review (60-79)**
- Orange cards with scores 60-79
- Candidates that might be worth considering

#### **❌ Rejected (<60)**
- Red cards, collapsed by default
- Click to expand and see who was rejected

---

## Test Scenarios

### Scenario 1: Strict Filtering
```
Min Experience: 10.0
Required Skills: Python,FastAPI,PostgreSQL,Docker,Kubernetes,AWS,Terraform,Go
```
**Expected:** High knockout rate (50%+), few shortlisted

---

### Scenario 2: Lenient Filtering
```
Min Experience: 1.0
Required Skills: Python
```
**Expected:** Low knockout rate (10%), more AI evaluations

---

### Scenario 3: Balanced
```
Min Experience: 3.0
Required Skills: Python,FastAPI,SQL
```
**Expected:** Moderate knockout rate (30%), mixed results

---

## What You Should See

### ✅ Success Indicators

1. **Knockout Stage Working:**
   - "Knocked Out" card shows > 0
   - Token savings displayed

2. **AI Metrics Visible:**
   - Summaries show: "Score: 73.0 (Exp:8/10, Skill:7/10, Impact:6/10)"
   - Not just a single number

3. **Three Result Categories:**
   - Shortlisted (green, 80+)
   - Review (orange, 60-79)
   - Rejected (red, <60)

4. **Criteria Displayed:**
   - Shows exactly what filters were applied

---

## Compare Before vs After

### Old Frontend (Single-Pass)
- 2 input fields (ZIP + description)
- 2 result categories (shortlisted vs all)
- Single score (0-100)
- No filtering metrics

### New Frontend (Multi-Stage)
- 4 input fields (+ experience + skills)
- 3 result categories (shortlisted/review/rejected)
- 6 statistics cards
- Token savings displayed
- Granular 3-metric scores
- Knockout stage visibility

---

## Troubleshooting

### "Form fields don't show up"
- Hard refresh: `Ctrl + F5` or `Cmd + Shift + R`
- Check browser console for errors (F12)

### "Results look wrong"
- Check Network tab (F12) to see API response
- Verify server logs for processing details

### "Shortlist threshold still 70"
- It's now 80 in the new system
- Check the criteria card matches your input

---

## Mobile Responsive

The form is now responsive:
- Form fields stack on mobile
- Stats cards wrap to grid
- Candidate cards remain readable

---

## Next Steps

After testing, you might want to:

1. **Adjust UI colors** in [static/styles.css](../static/styles.css)
2. **Add export functionality** (CSV/PDF download)
3. **Add candidate comparison** (side-by-side view)
4. **Add filters** (filter by experience, skills, status)
5. **Add pagination** for large result sets

---

**Your ATS frontend is ready for enterprise-grade multi-stage screening! 🎉**
