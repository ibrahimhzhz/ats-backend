# Sample Job Posts for Quick Paste Feature

Copy any of these formats and paste them into the "Quick Paste Mode" section in the web UI, then click "Parse & Auto-Fill Form".

---

## Example 1: AI Backend Engineer

```
Job Title:
AI Backend Engineer

Job Description:
We are looking for a backend engineer to architect scalable AI solutions. The ideal candidate has experience building REST APIs with Python (FastAPI or Django) and integrating Large Language Models using frameworks like Google Agentic Development Kit (ADK) or LangChain. You should be comfortable with multi-agent orchestration, prompt engineering, and optimizing SQL databases (PostgreSQL/MySQL).

Minimum Experience Required:
1 Year

Required Technical Skills:
Python
FastAPI
Google Agentic Development Kit (ADK)
Vertex AI
SQL
Prompt Engineering
```

---

## Example 2: Senior Full Stack Developer

```
Job Title:
Senior Full Stack Developer

Job Description:
Join our team as a Senior Full Stack Developer. You'll be responsible for building modern web applications using React and Node.js. The ideal candidate has strong experience with TypeScript, REST APIs, and cloud platforms. You should be comfortable working in an Agile environment and mentoring junior developers.

Minimum Experience Required:
5 Years

Required Technical Skills:
JavaScript
TypeScript
React
Node.js
PostgreSQL
AWS
Docker
```

---

## Example 3: Data Engineer (Minimal Format)

```
Job Description:
Looking for a Data Engineer to build and maintain data pipelines using Python, Spark, and Airflow. Experience with AWS services (S3, Glue, Redshift) required.

Minimum Experience Required:
3 Years

Required Technical Skills:
Python
Apache Spark
Airflow
SQL
AWS
ETL
```

---

## Example 4: DevOps Engineer (Bullet Points)

```
Job Title: DevOps Engineer

Job Description:
We need a DevOps Engineer to manage our cloud infrastructure and CI/CD pipelines. You'll work with Kubernetes, Terraform, and various monitoring tools to ensure high availability and performance of our production systems.

Minimum Experience Required:
4 Years

Required Technical Skills:
- Kubernetes
- Docker
- Terraform
- AWS/GCP
- Jenkins
- Prometheus
- Grafana
```

---

## Example 5: Junior Python Developer

```
Job Title:
Junior Python Developer

Job Description:
Great opportunity for a junior developer to learn and grow! You'll work on web applications using Django and contribute to API development. We're looking for someone with basic Python knowledge and eagerness to learn.

Minimum Experience Required:
0.5 Year

Required Technical Skills:
Python
Django
REST API
Git
SQL
```

---

## Supported Formats

The parser is flexible and supports:

### Experience Formats:
- "1 Year"
- "2 Years"
- "3 yr"
- "5.5 Years"
- "0.5 Year" (6 months)

### Skills Formats:
- One skill per line (with or without bullets)
- Skills with spaces: "Google Agentic Development Kit (ADK)"
- Skills with parentheses: "AWS (Amazon Web Services)"

### Section Headers (case-insensitive):
- "Job Description:"
- "Minimum Experience Required:"
- "Required Technical Skills:" or "Required Skills:"

---

## Tips

1. **Copy the entire block** including section headers
2. Skills should be **one per line** under "Required Technical Skills"
3. Experience must include **number + "Year" or "Years"**
4. Parser is **case-insensitive** and handles extra whitespace

---

## What Gets Extracted

✅ **Job Description** → Fills "Job Description" textarea
✅ **Minimum Experience** → Fills "Minimum Experience (Years)" field
✅ **Required Skills** → Fills "Required Skills" field (comma-separated)

Then just upload your ZIP file and click "Start Multi-Stage Screening"!
