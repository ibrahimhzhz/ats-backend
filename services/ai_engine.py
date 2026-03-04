import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
import json
import os
import asyncio
import concurrent.futures
import time
import re
import logging
from dotenv import dotenv_values
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# --- 1. SETUP & AUTHENTICATION ---

# Try to find the .env file
base_dir = Path(__file__).resolve().parent.parent
env_path = base_dir / ".env"

# Attempt to load from .env
config = dotenv_values(env_path)
project_id = os.getenv("GCP_PROJECT_ID") or config.get("GCP_PROJECT_ID")
location = os.getenv("GCP_LOCATION") or config.get("GCP_LOCATION", "us-central1")  # Default to us-central1

# Support injecting credentials directly as JSON (or base64 JSON) via environment.
# Accept multiple env var names for deployment platform compatibility.
credentials_json = (
    os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    or os.getenv("GOOGLE_CREDENTIALS_BASE64")
    or os.getenv("GOOGLE_CREDENTIALS_JSON")
)
if credentials_json:
    try:
        import base64
        decoded = base64.b64decode(credentials_json).decode("utf-8")
        parsed = json.loads(decoded)
        normalized_json = json.dumps(parsed)
    except Exception:
        parsed = json.loads(credentials_json)
        normalized_json = json.dumps(parsed)

    runtime_creds_path = "/tmp/gcp-service-account.json"
    with open(runtime_creds_path, "w", encoding="utf-8") as credentials_file:
        credentials_file.write(normalized_json)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = runtime_creds_path
    print(f"✅ Using credentials from GOOGLE_APPLICATION_CREDENTIALS_JSON at: {runtime_creds_path}")

# Set Google Cloud credentials path if specified
credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or config.get("GOOGLE_APPLICATION_CREDENTIALS")
if credentials_path:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
    print(f"✅ Using credentials from: {credentials_path}")

_model = None
_vertex_init_error = None


class AIServiceUnavailableError(RuntimeError):
    """Raised when AI extraction is requested but Vertex AI is unavailable."""


def _get_model():
    """Lazy-init Vertex model so app startup doesn't crash if AI config is missing."""
    global _model, _vertex_init_error

    if _model is not None:
        return _model

    if _vertex_init_error is not None:
        return None

    if not project_id:
        _vertex_init_error = (
            "GCP_PROJECT_ID not found in environment variables or .env file. "
            "AI extraction is unavailable."
        )
        print(f"⚠️ {_vertex_init_error}")
        return None

    try:
        vertexai.init(project=project_id, location=location)
        print(f"✅ Vertex AI initialized with project: {project_id}, location: {location}")
        _model = GenerativeModel("gemini-2.0-flash-001")
        return _model
    except Exception as exc:
        _vertex_init_error = f"Vertex AI initialization failed: {str(exc)}"
        print(f"⚠️ {_vertex_init_error}")
        return None


def is_ai_available() -> bool:
    """Return True when Vertex AI model can be used for extraction."""
    return _get_model() is not None


def get_ai_unavailable_reason() -> Optional[str]:
    """Return initialization error reason when AI is unavailable."""
    _get_model()
    return _vertex_init_error


# --- RATE LIMITING ---
class RateLimiter:
    """Simple rate limiter for API calls."""
    
    def __init__(self, calls_per_minute: int = 15):
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute
        self.last_call_time = 0
    
    async def wait_if_needed(self):
        """Wait if necessary to respect rate limits."""
        current_time = time.time()
        time_since_last_call = current_time - self.last_call_time
        
        if time_since_last_call < self.min_interval:
            wait_time = self.min_interval - time_since_last_call
            print(f"⏳ Rate limiting: waiting {wait_time:.2f}s...")
            await asyncio.sleep(wait_time)
        
        self.last_call_time = time.time()


# Global rate limiter instance (Vertex AI has higher limits, set to 60 calls per minute)
rate_limiter = RateLimiter(calls_per_minute=60)


# --- 2. HELPER FUNCTIONS ---
def clean_json_string(text):
    """
    Cleans API response if it includes markdown formatting like ```json ... ```
    """
    text = text.strip()
    # Remove markdown code blocks if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line if it's ```json and last line if it's ```
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


DEFAULT_JD_REQUIREMENTS: Dict[str, Any] = {
    "must_have_skills": [],
    "minimum_years_experience": 0.0,
    "education_requirement": "Not specified",
    "offers_visa_sponsorship": None,
}


CANDIDATE_FACT_SCHEMA: Dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "total_years_experience": {
            "type": "INTEGER",
            "description": "Total years of professional work experience across all roles. Calculate from job dates, do not guess.",
        },
        "extractable_text": {
            "type": "BOOLEAN",
            "description": "true if the resume contained readable text. false if the document appeared blank, corrupted, or image-only with no parseable content.",
        },
        "requires_visa_sponsorship": {
            "type": "BOOLEAN",
            "description": "true if the candidate explicitly mentions needing visa sponsorship, work authorization, or OPT/CPT/H1B. false if not mentioned or if they state they are authorized.",
        },
        "has_measurable_impact": {
            "type": "BOOLEAN",
            "description": "true if the resume contains at least one quantified achievement using numbers, percentages, or dollar amounts (e.g. 'increased revenue by 30%', 'reduced latency by 200ms', 'managed $2M budget'). false otherwise.",
        },
        "has_contact_info": {
            "type": "BOOLEAN",
            "description": "true if the resume contains at least an email address or phone number.",
        },
        "has_clear_job_titles": {
            "type": "BOOLEAN",
            "description": "true if each role in the work history has a clearly stated job title.",
        },
        "skills": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {
                        "type": "STRING",
                        "description": "The skill name exactly as it appears or can be clearly inferred from context. Lowercase.",
                    },
                    "last_used_year": {
                        "type": "INTEGER",
                        "nullable": True,
                        "description": "The year this skill was most recently used based on the job it appears in. null if cannot be determined.",
                    },
                    "job_index": {
                        "type": "INTEGER",
                        "nullable": True,
                        "description": "Zero-based index into the jobs array indicating which job this skill was most recently associated with. null if cannot be determined.",
                    },
                },
                "required": ["name"],
            },
            "description": "Every technical skill, tool, framework, language, and platform mentioned anywhere in the resume.",
        },
        "education": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "degree": {
                        "type": "STRING",
                        "description": "One of: none, high school, associate, bachelor, master, phd. Lowercase. Map all variations (e.g. 'BS', 'B.Sc', 'Bachelor of Science' all map to 'bachelor').",
                    },
                    "field_of_study": {
                        "type": "STRING",
                        "nullable": True,
                        "description": "The major or field of study, lowercase. e.g. 'computer science', 'mathematics', 'business administration'. null if not specified.",
                    },
                    "institution": {
                        "type": "STRING",
                        "nullable": True,
                        "description": "Name of the university or school. null if not specified.",
                    },
                    "year": {
                        "type": "INTEGER",
                        "nullable": True,
                        "description": "Graduation year. null if not specified.",
                    },
                },
                "required": ["degree"],
            },
            "description": "All education entries from the resume.",
        },
        "jobs": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {
                        "type": "STRING",
                        "description": "The exact job title as stated on the resume.",
                    },
                    "company": {
                        "type": "STRING",
                        "description": "The company name.",
                    },
                    "start_year": {
                        "type": "INTEGER",
                        "description": "The year this role started.",
                    },
                    "end_year": {
                        "type": "INTEGER",
                        "nullable": True,
                        "description": "The year this role ended. null if this is the current role.",
                    },
                    "is_current": {
                        "type": "BOOLEAN",
                        "description": "true if this is the candidate's current or most recent active role.",
                    },
                    "domain": {
                        "type": "STRING",
                        "description": "The industry domain of this company. One of: fintech, healthcare, saas, ecommerce, enterprise, agency, startup, government, education, media, logistics, other.",
                    },
                    "work_type": {
                        "type": "STRING",
                        "description": "One of: remote, hybrid, onsite, unknown. Infer from the resume if explicitly stated. unknown if not stated.",
                    },
                },
                "required": ["title", "company", "start_year", "is_current", "domain", "work_type"],
            },
            "description": "Work history in reverse chronological order. Index 0 is always the most recent role.",
        },
        "cover_letter_analysis": {
            "type": "OBJECT",
            "properties": {
                "word_count": {
                    "type": "INTEGER",
                    "description": "Total word count of the cover letter. 0 if no cover letter was provided.",
                },
                "mentions_role_title": {
                    "type": "BOOLEAN",
                    "description": "true if the cover letter explicitly mentions the job title or a close variation of it. false if no cover letter or title not mentioned.",
                },
                "skills_mentioned": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "List of technical skills mentioned in the cover letter, lowercase. Empty array if none or no cover letter.",
                },
                "has_specific_example": {
                    "type": "BOOLEAN",
                    "description": "true if the cover letter contains at least one specific example of past work, achievement, or project with concrete details. false otherwise.",
                },
                "is_generic": {
                    "type": "BOOLEAN",
                    "description": "true if the cover letter appears to be a generic template with no role-specific content. false if it contains specific relevant content.",
                },
            },
            "required": ["word_count", "mentions_role_title", "skills_mentioned", "has_specific_example", "is_generic"],
        },
        "custom_answer_analysis": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "question_index": {
                        "type": "INTEGER",
                        "description": "Zero-based index of the question this answer corresponds to.",
                    },
                    "word_count": {
                        "type": "INTEGER",
                        "description": "Word count of the answer.",
                    },
                    "is_relevant": {
                        "type": "BOOLEAN",
                        "description": "true if the answer is topically relevant to the question asked. false if off-topic, nonsensical, or placeholder text.",
                    },
                    "has_specific_example": {
                        "type": "BOOLEAN",
                        "description": "true if the answer contains a specific real example, project, or measurable outcome. false if entirely vague or generic.",
                    },
                },
                "required": ["question_index", "word_count", "is_relevant", "has_specific_example"],
            },
            "description": "Analysis of custom question answers. Empty array if no custom answers provided.",
        },
    },
    "required": [
        "total_years_experience",
        "extractable_text",
        "requires_visa_sponsorship",
        "has_measurable_impact",
        "has_contact_info",
        "has_clear_job_titles",
        "skills",
        "education",
        "jobs",
        "cover_letter_analysis",
        "custom_answer_analysis",
    ],
}


EXTRACTION_SYSTEM_PROMPT = """You are a resume data extraction API. Your only function is to extract factual information from the provided resume text and return it as a strict JSON object.

Rules you must follow without exception:
1. Extract only facts that are explicitly stated or can be directly calculated from stated dates. Never infer, guess, or assume anything that is not written.
2. Never evaluate, score, rank, or make any judgment about the candidate's quality, suitability, or skills. You are forbidden from producing any subjective assessment.
3. If a piece of information is not present in the resume, return null for that field. Never fabricate data to fill a field.
4. For the jobs array, list roles in reverse chronological order — most recent first. Index 0 is always the most recent role.
5. For skills, extract every technical skill, tool, framework, language, and platform mentioned anywhere in the resume including job descriptions, skills sections, and project descriptions.
6. For degree, map all variations to the canonical values: none, high school, associate, bachelor, master, phd.
7. For domain, use your knowledge of the company to determine the industry domain. If the company is unknown or ambiguous, use "other".
8. For work_type, only mark remote or hybrid if the resume explicitly states it. Otherwise use unknown.
9. Return only the JSON object. No explanation, no preamble, no markdown formatting, no code fences."""


def validate_extraction_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Standalone pure validation function for Gemini extraction results.

    Takes the raw JSON response from Gemini and returns a clean, guaranteed-shape
    object. Logs warnings for any field that required correction.

    This function must never be inlined into the Celery task.
    """
    result = dict(raw)  # shallow copy

    # 1. extractable_text — must be boolean. If false, return null shell immediately.
    if not isinstance(result.get("extractable_text"), bool):
        logger.warning("Extraction validation: extractable_text missing or not boolean, defaulting to True")
        result["extractable_text"] = True

    if result["extractable_text"] is False:
        logger.warning("Extraction validation: extractable_text is False — resume not readable")
        return {
            "extractable_text": False,
            "total_years_experience": 0,
            "requires_visa_sponsorship": False,
            "has_measurable_impact": False,
            "has_contact_info": False,
            "has_clear_job_titles": False,
            "employment_gaps": False,
            "average_tenure_years": 0.0,
            "skills": [],
            "education": [],
            "jobs": [],
            "cover_letter_analysis": {
                "word_count": 0,
                "mentions_role_title": False,
                "skills_mentioned": [],
                "has_specific_example": False,
                "is_generic": True,
            },
            "custom_answer_analysis": [],
        }

    # 2. total_years_experience — integer >= 0
    try:
        tye = int(result.get("total_years_experience") or 0)
        if tye < 0:
            logger.warning(f"Extraction validation: total_years_experience was negative ({tye}), setting to 0")
            tye = 0
    except (TypeError, ValueError):
        logger.warning("Extraction validation: total_years_experience not parseable, setting to 0")
        tye = 0
    result["total_years_experience"] = tye

    # 3. skills — array, every item must have at least a 'name' field
    skills = result.get("skills")
    if not isinstance(skills, list):
        logger.warning("Extraction validation: skills was not an array, setting to []")
        skills = []
    valid_skills = []
    for s in skills:
        if isinstance(s, dict) and s.get("name") and isinstance(s["name"], str) and s["name"].strip():
            valid_skills.append(s)
        else:
            logger.warning(f"Extraction validation: dropping skill entry missing name: {s}")
    result["skills"] = valid_skills

    # 4. jobs — array, every item must have title, company, start_year
    jobs = result.get("jobs")
    if not isinstance(jobs, list):
        logger.warning("Extraction validation: jobs was not an array, setting to []")
        jobs = []
    valid_jobs = []
    for j in jobs:
        if (isinstance(j, dict)
                and j.get("title") and isinstance(j["title"], str) and j["title"].strip()
                and j.get("company") and isinstance(j["company"], str) and j["company"].strip()
                and j.get("start_year") is not None):
            valid_jobs.append(j)
        else:
            logger.warning(f"Extraction validation: dropping job entry missing required fields: {j}")
    result["jobs"] = valid_jobs

    # 5. education — must be an array, never null
    education = result.get("education")
    if not isinstance(education, list):
        logger.warning("Extraction validation: education was not an array, setting to []")
        result["education"] = []

    # 6. Boolean fields — must be boolean, default False
    for field in [
        "requires_visa_sponsorship",
        "has_measurable_impact",
        "has_contact_info",
        "has_clear_job_titles",
        "employment_gaps",
    ]:
        if not isinstance(result.get(field), bool):
            logger.warning(f"Extraction validation: {field} not boolean, defaulting to False")
            result[field] = False

    # 7. average_tenure_years — must be float
    try:
        result["average_tenure_years"] = round(float(result.get("average_tenure_years") or 0.0), 1)
    except (TypeError, ValueError):
        logger.warning("Extraction validation: average_tenure_years not parseable, setting to 0.0")
        result["average_tenure_years"] = 0.0

    # 8. cover_letter_analysis — must be a dict with required keys
    cla = result.get("cover_letter_analysis")
    if not isinstance(cla, dict):
        logger.warning("Extraction validation: cover_letter_analysis missing, setting default")
        result["cover_letter_analysis"] = {
            "word_count": 0,
            "mentions_role_title": False,
            "skills_mentioned": [],
            "has_specific_example": False,
            "is_generic": True,
        }

    # 9. custom_answer_analysis — must be an array
    caa = result.get("custom_answer_analysis")
    if not isinstance(caa, list):
        logger.warning("Extraction validation: custom_answer_analysis not array, setting to []")
        result["custom_answer_analysis"] = []

    return result


def normalize_job_requirements(job_requirements: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize extracted job requirements to a strict, typed schema."""
    if not isinstance(job_requirements, dict):
        return dict(DEFAULT_JD_REQUIREMENTS)

    skills = job_requirements.get("must_have_skills") or []
    if not isinstance(skills, list):
        skills = []
    normalized_skills = []
    for skill in skills:
        val = str(skill).strip()
        if val:
            normalized_skills.append(val)

    try:
        min_years = float(job_requirements.get("minimum_years_experience") or 0.0)
    except (TypeError, ValueError):
        min_years = 0.0
    min_years = max(0.0, min_years)

    education_requirement = str(
        job_requirements.get("education_requirement") or "Not specified"
    ).strip() or "Not specified"

    visa_value = job_requirements.get("offers_visa_sponsorship")
    if isinstance(visa_value, bool):
        offers_visa_sponsorship = visa_value
    elif visa_value is None:
        offers_visa_sponsorship = None
    else:
        text = str(visa_value).strip().lower()
        if text in {"true", "yes", "y", "1"}:
            offers_visa_sponsorship = True
        elif text in {"false", "no", "n", "0"}:
            offers_visa_sponsorship = False
        else:
            offers_visa_sponsorship = None

    return {
        "must_have_skills": normalized_skills,
        "minimum_years_experience": min_years,
        "education_requirement": education_requirement,
        "offers_visa_sponsorship": offers_visa_sponsorship,
    }

# --- 3. LEVEL 1: JD REQUIREMENT EXTRACTION (Grounded) ---

async def extract_jd_requirements(jd_text: str) -> Dict[str, Any]:
    """
    LEVEL 1: Strict JD normalization.

    Converts a freeform job description into a deterministic JSON contract used
    by downstream screening and scoring logic.
    """
    print("📋 Extracting structured JD requirements (Level 1 baseline)...")
    await rate_limiter.wait_if_needed()
    model = _get_model()
    if model is None:
        return dict(DEFAULT_JD_REQUIREMENTS)

    prompt = f"""
        You are a strict information extractor.
        Convert the job description into a strict JSON object with EXACTLY these keys:
        - must_have_skills: array of canonical skill names (strings only)
        - minimum_years_experience: number (float or int)
        - education_requirement: string (single concise requirement)
        - offers_visa_sponsorship: true, false, or null if not specified

    JOB DESCRIPTION:
    {jd_text[:8000]}

        RULES:
        1) Include only hard requirements for must_have_skills.
        2) If years are unspecified, set minimum_years_experience to 0.
        3) Keep education_requirement as "Not specified" when absent.
        4) Do NOT add extra keys.
        5) Return ONLY JSON.
    
        Example:
        {{
            "must_have_skills": ["Python", "React", "PostgreSQL"],
            "minimum_years_experience": 3,
            "education_requirement": "Bachelor's in Computer Science or equivalent",
            "offers_visa_sponsorship": false
        }}
    """

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(
                prompt,
                generation_config=GenerationConfig(
                    temperature=0.0,  # Maximum determinism
                    response_mime_type="application/json"
                )
            )
        )
        json_text = clean_json_string(response.text)
        requirements = normalize_job_requirements(json.loads(json_text))
        print(
            "✅ Structured JD extracted "
            f"({len(requirements['must_have_skills'])} skills, "
            f"{requirements['minimum_years_experience']} yrs min)"
        )
        return requirements

    except Exception as e:
        print(f"❌ JD REQUIREMENT EXTRACTION FAILED: {str(e)}")
        return dict(DEFAULT_JD_REQUIREMENTS)


# --- 4. LEVEL 2: GROUNDED RESUME VERIFICATION ---

# Degree ranking used for backward-compatible highest_education_level derivation
_DEGREE_RANK = {"none": 0, "high school": 1, "associate": 2, "bachelor": 3, "master": 4, "phd": 5}
_DEGREE_DISPLAY = {0: "None", 1: "High School", 2: "Associate", 3: "Bachelors", 4: "Masters", 5: "PhD"}


def calculate_years_used(skill: dict, jobs: list, current_year: int = 2026) -> float | None:
    """
    Calculates years a skill was used based on the duration of the job
    it was associated with. Uses job_index from the skill to look up
    the corresponding job in the jobs list and computes end - start.
    Returns None if job_index is missing or out of bounds.
    """
    job_index = skill.get("job_index")
    if job_index is None:
        return None
    if job_index >= len(jobs):
        return None

    job = jobs[job_index]
    start = job.get("start_year")
    end = job.get("end_year") or current_year

    if start is None:
        return None

    duration = max(end - start, 0)
    return round(max(duration, 0.5), 1)  # minimum 0.5 to avoid zero for short contracts


def calculate_employment_gaps(jobs: list, current_year: int = 2026) -> bool:
    """
    Returns True if any gap of 6 or more months exists between consecutive
    roles, or between the most recent role's end date and today.
    Sorts jobs by start_year ascending before comparing.
    Returns False if fewer than 2 jobs exist.
    """
    if not jobs or len(jobs) < 2:
        return False

    sorted_jobs = sorted(
        [j for j in jobs if j.get("start_year")],
        key=lambda j: j["start_year"]
    )

    for i in range(len(sorted_jobs) - 1):
        current_end = sorted_jobs[i].get("end_year") or current_year
        next_start = sorted_jobs[i + 1].get("start_year", current_year)
        gap_months = (next_start - current_end) * 12
        if gap_months >= 6:
            return True

    return False


def calculate_average_tenure(jobs: list, current_year: int = 2026) -> float:
    """
    Calculates average years spent per role across all jobs in the list.
    Uses end_year if present, otherwise uses current_year for active roles.
    Returns 0.0 if the jobs list is empty.
    """
    if not jobs:
        return 0.0

    tenures = []
    for job in jobs:
        start = job.get("start_year")
        if start is None:
            continue
        end = job.get("end_year") or current_year
        tenure = max(end - start, 0)
        tenures.append(tenure)

    if not tenures:
        return 0.0

    return round(sum(tenures) / len(tenures), 1)


def _derive_highest_education(education: List[Dict[str, Any]]) -> str:
    """Derive the highest education level string from the new education array for backward compat."""
    highest_rank = 0
    for entry in education:
        degree = str(entry.get("degree") or "none").strip().lower()
        rank = _DEGREE_RANK.get(degree, 0)
        if rank > highest_rank:
            highest_rank = rank
    return _DEGREE_DISPLAY.get(highest_rank, "None")


async def extract_candidate_facts(
    resume_text: str,
    job_requirements: Optional[Dict[str, Any]] = None,
    fail_on_unavailable: bool = True,
    cover_letter_text: Optional[str] = None,
    custom_questions_and_answers: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    LEVEL 2: Grounded Resume Verification

    Single-pass factual extraction from a resume using the enriched schema.
    AI performs extraction only (no evaluation/judgment).
    Returns a dict that is backward-compatible with the existing scoring functions
    while also exposing all new enriched fields.
    """
    _EMPTY_FALLBACK: Dict[str, Any] = {
        "name": "Unknown Candidate",
        "email": "unknown@error.com",
        "phone": "",
        "total_years_experience": 0.0,
        "highest_education_level": "None",
        "job_titles": [],
        "skills": [],
        "skills_with_years": {},
        "skills_detailed": [],
        "skill_matches": [],
        "requires_sponsorship": False,
        "requires_visa_sponsorship": False,
        "extractable_text": False,
        "has_measurable_impact": False,
        "has_contact_info": False,
        "has_clear_job_titles": False,
        "employment_gaps": False,
        "average_tenure_years": 0.0,
        "education": [],
        "jobs": [],
        "cover_letter_analysis": {
            "word_count": 0,
            "mentions_role_title": False,
            "skills_mentioned": [],
            "has_specific_example": False,
            "is_generic": True,
        },
        "custom_answer_analysis": [],
    }

    print("🤖 Sending resume to Gemini for strict fact extraction...")
    await rate_limiter.wait_if_needed()
    model = _get_model()
    if model is None:
        if fail_on_unavailable:
            reason = get_ai_unavailable_reason() or "AI extraction service is unavailable"
            raise AIServiceUnavailableError(reason)
        return dict(_EMPTY_FALLBACK)

    normalized_requirements = normalize_job_requirements(job_requirements)
    required_skills = normalized_requirements.get("must_have_skills", [])

    # --- Build prompt ---
    prompt_parts = [EXTRACTION_SYSTEM_PROMPT, "\n\nRESUME TEXT:\n", resume_text[:12000]]

    if cover_letter_text and cover_letter_text.strip():
        prompt_parts.append("\n\nCOVER LETTER:\n")
        prompt_parts.append(cover_letter_text[:5000])

    if custom_questions_and_answers:
        prompt_parts.append("\n\nCUSTOM APPLICATION QUESTIONS AND ANSWERS:\n")
        for i, qa in enumerate(custom_questions_and_answers):
            q = qa.get("question", "")
            a = qa.get("answer", "")
            prompt_parts.append(f"Question {i}: {q}\nAnswer {i}: {a}\n")

    prompt = "".join(prompt_parts)

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(
                prompt,
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=CANDIDATE_FACT_SCHEMA,
                    temperature=0.0,
                )
            )
        )
        json_text = clean_json_string(response.text)
        raw_extracted = json.loads(json_text)

        # --- Step 1: Validate raw Gemini output ---
        extracted = validate_extraction_result(raw_extracted)

        # --- Step 2: Calculate employment gaps from job dates ---
        extracted["employment_gaps"] = calculate_employment_gaps(
            extracted.get("jobs", []), current_year=2026
        )

        # --- Step 3: Calculate average tenure from job dates ---
        extracted["average_tenure_years"] = calculate_average_tenure(
            extracted.get("jobs", []), current_year=2026
        )

        # --- Step 4: Calculate years_used per skill from job durations ---
        for skill in extracted.get("skills", []):
            skill["years_used"] = calculate_years_used(
                skill, extracted.get("jobs", []), current_year=2026
            )

        # --- If resume was not extractable, return early with fallback ---
        if extracted.get("extractable_text") is False:
            fallback = dict(_EMPTY_FALLBACK)
            # Still try to pull name/email/phone from raw text via regex
            email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", resume_text)
            phone_match = re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", resume_text)
            first_line = (resume_text or "").splitlines()[0].strip() if resume_text else ""
            if first_line and len(first_line.split()) <= 6 and "@" not in first_line:
                fallback["name"] = first_line
            if email_match:
                fallback["email"] = email_match.group(0).lower()
            if phone_match:
                fallback["phone"] = phone_match.group(0).strip()
            print("⚠️ Resume not extractable — returning fallback")
            return fallback

        # --- Build backward-compatible fields from enriched extraction ---
        total_years_experience = float(extracted.get("total_years_experience") or 0)

        # Skills: build flat list + skills_with_years dict from new detailed schema
        extracted_skills = extracted.get("skills") or []
        skills: List[str] = []
        skills_with_years: Dict[str, float] = {}
        for item in extracted_skills:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            skills.append(name)
            try:
                years = float(item.get("years_used") or 1.0)
            except (TypeError, ValueError):
                years = 1.0
            skills_with_years[name] = max(0.5, years)

        # Education: derive highest_education_level from education array
        education = extracted.get("education") or []
        highest_education_level = _derive_highest_education(education)

        # Jobs: derive job_titles from jobs array
        jobs = extracted.get("jobs") or []
        job_titles = [str(j.get("title") or "").strip() for j in jobs if str(j.get("title") or "").strip()]

        # Sponsorship: map to both old field names
        requires_sponsorship = bool(extracted.get("requires_visa_sponsorship", False))

        # Skill matches against required skills (same logic as before)
        extracted_skill_set = {skill.lower() for skill in skills}
        skill_matches = [
            {
                "skill": skill,
                "matched": skill.lower() in extracted_skill_set,
            }
            for skill in required_skills
        ]

        # Contact info from raw text via regex (more reliable than AI extraction)
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", resume_text)
        phone_match = re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", resume_text)
        name = "Unknown Candidate"
        first_line = (resume_text or "").splitlines()[0].strip() if resume_text else ""
        if first_line and len(first_line.split()) <= 6 and "@" not in first_line:
            name = first_line

        # --- Assemble final data dict ---
        data: Dict[str, Any] = {
            # Backward-compatible fields (used by scoring, tasks, knockout filters)
            "name": name,
            "email": email_match.group(0).lower() if email_match else "unknown@error.com",
            "phone": phone_match.group(0).strip() if phone_match else "",
            "total_years_experience": total_years_experience,
            "highest_education_level": highest_education_level,
            "job_titles": job_titles,
            "skills": skills,
            "skills_with_years": skills_with_years,
            "skill_matches": skill_matches,
            "requires_sponsorship": requires_sponsorship,
            "requires_visa_sponsorship": requires_sponsorship,
            # New enriched fields
            "extractable_text": extracted.get("extractable_text", True),
            "has_measurable_impact": extracted.get("has_measurable_impact", False),
            "has_contact_info": extracted.get("has_contact_info", False),
            "has_clear_job_titles": extracted.get("has_clear_job_titles", False),
            "employment_gaps": extracted.get("employment_gaps", False),
            "average_tenure_years": extracted.get("average_tenure_years", 0.0),
            "skills_detailed": extracted_skills,
            "education": education,
            "jobs": jobs,
            "cover_letter_analysis": extracted.get("cover_letter_analysis", {
                "word_count": 0,
                "mentions_role_title": False,
                "skills_mentioned": [],
                "has_specific_example": False,
                "is_generic": True,
            }),
            "custom_answer_analysis": extracted.get("custom_answer_analysis", []),
        }

        print("✅ Vertex AI Fact Extraction Successful")
        return data

    except Exception as e:
        print(f"❌ VERTEX AI EXTRACTION FAILED: {str(e)}")
        return dict(_EMPTY_FALLBACK)


# --- 4. DETERMINISTIC PYTHON SCORING — no LLM, 100% repeatable ---

def _fuzzy_match_skill(
    required: str, candidate_skills_lower: Dict[str, float]
) -> tuple:
    """
    Returns (matched_key, years) for the best fuzzy match of `required` against
    the candidate's skill dict, or (None, 0.0) if nothing matches.

    Strategy (in priority order):
      1. Exact lowercase match          — "python" == "python"
      2. Required is substring of key   — "postgres" in "postgresql"
      3. Key is substring of required   — "js" in "javascript"
    """
    req = required.lower()
    # 1. Exact
    if req in candidate_skills_lower:
        return req, candidate_skills_lower[req]
    # 2 & 3. Substring (both directions)
    for key, yrs in candidate_skills_lower.items():
        if req in key or key in req:
            return key, yrs
    return None, 0.0


def calculate_deterministic_score(
    candidate: Dict[str, Any],
    required_skills: List[str],
    min_experience: float,
    job_title: str = "",
    raw_resume_text: str = "",
    required_education: str = "Not specified",
    job_requirements: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Deterministic ATS score with explicit, inspectable math.

    Weights:
      Experience    40 pts
      Skills Match  40 pts
      Education     20 pts
    Total:         100 pts
    """
    normalized_requirements = normalize_job_requirements(job_requirements)
    effective_required_skills = normalized_requirements["must_have_skills"] or required_skills
    effective_min_experience = (
        normalized_requirements["minimum_years_experience"]
        if normalized_requirements["minimum_years_experience"] > 0
        else float(min_experience or 0)
    )
    effective_required_education = (
        normalized_requirements["education_requirement"]
        if normalized_requirements["education_requirement"] != "Not specified"
        else required_education
    )

    skills_with_years: Dict[str, float] = candidate.get("skills_with_years") or {}
    total_years_experience: float = float(candidate.get("total_years_experience") or 0)
    highest_education_level = str(candidate.get("highest_education_level") or "Unknown")
    skill_matches_input: List[Dict[str, Any]] = candidate.get("skill_matches") or []

    # Normalise skill keys to lowercase once
    candidate_skills_lower: Dict[str, float] = {
        k.lower(): v for k, v in skills_with_years.items()
    }
    required_skills_lower: List[str] = [s.lower() for s in effective_required_skills if s]

    # ── 1. Experience Score (40 pts) ─────────────────────────────────────
    exp_denominator = max(effective_min_experience, 1.0)
    exp_ratio = min(1.0, max(0.0, total_years_experience / exp_denominator))
    experience_points = exp_ratio * 40.0

    # ── 2. Skills Match Score (40 pts) ───────────────────────────────────
    matched_skills: List[str] = []

    if skill_matches_input:
        llm_matches_lower = {
            str(item.get("skill", "")).strip().lower(): bool(item.get("matched", False))
            for item in skill_matches_input
            if isinstance(item, dict) and str(item.get("skill", "")).strip()
        }
        for required_skill in required_skills_lower:
            if llm_matches_lower.get(required_skill, False):
                matched_skills.append(required_skill)
    else:
        for required_skill in required_skills_lower:
            matched_key, _ = _fuzzy_match_skill(required_skill, candidate_skills_lower)
            if matched_key is not None:
                matched_skills.append(required_skill)

    matched_skills_count = len(set(matched_skills))
    required_skill_count = len(required_skills_lower)
    skill_ratio = (matched_skills_count / required_skill_count) if required_skill_count else 1.0
    skills_points = skill_ratio * 40.0

    # ── 3. Education Score (20 pts) ──────────────────────────────────────
    education_met = _education_requirement_met(
        highest_education_level=highest_education_level,
        education_requirement=effective_required_education,
    )
    education_points = 20.0 if education_met else 0.0

    # ── Final Score ───────────────────────────────────────────────────────
    raw = experience_points + skills_points + education_points
    final_score = int(round(raw))

    # ── Status Bucketing ─────────────────────────────────────────────────
    if final_score >= 80:
        status = "shortlisted"
    elif final_score >= 60:
        status = "review"
    else:
        status = "rejected"

    summary = (
        f"Experience {total_years_experience:.1f}/{exp_denominator:.1f} years, "
        f"skills matched {matched_skills_count}/{required_skill_count}, "
        f"education requirement met: {'yes' if education_met else 'no'}."
    )

    return {
        "final_score": final_score,
        "status": status,
        "summary": summary,
        "matched_skills_count": matched_skills_count,
        "matched_skills": sorted(set(matched_skills)),
        "required_skills_count": required_skill_count,
        "education_met": education_met,
        "breakdown": {
            "experience": round(experience_points, 1),
            "skills": round(skills_points, 1),
            "education": round(education_points, 1),
        },
    }


def _education_requirement_met(highest_education_level: str, education_requirement: str) -> bool:
    """Return whether extracted education satisfies job requirement."""
    requirement = (education_requirement or "").strip().lower()
    if not requirement or requirement in {"not specified", "none", "n/a"}:
        return True

    ranking = {
        "unknown": 0,
        "high school": 1,
        "associate": 2,
        "bachelor": 3,
        "master": 4,
        "phd": 5,
        "doctorate": 5,
    }

    level_text = (highest_education_level or "unknown").strip().lower()
    candidate_rank = 0
    for key, rank in ranking.items():
        if key in level_text:
            candidate_rank = max(candidate_rank, rank)

    required_rank = 0
    for key, rank in ranking.items():
        if key in requirement:
            required_rank = max(required_rank, rank)

    if required_rank == 0:
        return True

    return candidate_rank >= required_rank


def evaluate_knockout_filters(
    candidate: Dict[str, Any],
    required_skills: List[str],
    min_experience: float,
    job_title: str = "",
    job_requirements: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate deterministic knockout conditions and return status metadata."""
    normalized_requirements = normalize_job_requirements(job_requirements)
    effective_required_skills = normalized_requirements["must_have_skills"] or required_skills
    effective_min_experience = (
        normalized_requirements["minimum_years_experience"]
        if normalized_requirements["minimum_years_experience"] > 0
        else float(min_experience or 0)
    )

    total_years_experience = float(candidate.get("total_years_experience") or 0.0)
    required_skills_lower = [s.lower() for s in effective_required_skills if s]

    skill_matches = candidate.get("skill_matches") or []
    candidate_skills_lower = {
        str(k).lower(): float(v) for k, v in (candidate.get("skills_with_years") or {}).items()
    }

    matched_skills_count = 0
    if skill_matches:
        llm_matches_lower = {
            str(item.get("skill", "")).strip().lower(): bool(item.get("matched", False))
            for item in skill_matches
            if isinstance(item, dict) and str(item.get("skill", "")).strip()
        }
        matched_skills_count = sum(1 for s in required_skills_lower if llm_matches_lower.get(s, False))
    else:
        for skill in required_skills_lower:
            key, _ = _fuzzy_match_skill(skill, candidate_skills_lower)
            if key is not None:
                matched_skills_count += 1

    if effective_min_experience > 0:
        exp_ratio = total_years_experience / max(effective_min_experience, 1.0)
    else:
        exp_ratio = 1.0

    skill_ratio = (
        matched_skills_count / len(required_skills_lower)
        if required_skills_lower
        else 1.0
    )

    reasons: List[str] = []

    if "senior" in (job_title or "").lower() and total_years_experience <= 0:
        reasons.append("0 years of experience for senior role")

    requires_visa = candidate.get("requires_sponsorship")
    if requires_visa is None:
        requires_visa = candidate.get("requires_visa_sponsorship")
    offers_visa = normalized_requirements.get("offers_visa_sponsorship")
    if requires_visa is True and offers_visa is False:
        reasons.append("candidate requires visa sponsorship but role does not offer it")

    knockout = bool(reasons)
    reason = "; ".join(reasons)
    return {
        "knockout": knockout,
        "reason": reason,
        "experience_ratio": max(0.0, min(1.0, exp_ratio)),
        "skills_ratio": max(0.0, min(1.0, skill_ratio)),
        "matched_skills_count": matched_skills_count,
        "required_skills_count": len(required_skills_lower),
    }


# --- 5. SYNC WRAPPERS (for single-resume endpoints that can't be async) ---

def extract_candidate_facts_sync(
    resume_text: str,
    cover_letter_text: Optional[str] = None,
    custom_questions_and_answers: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Synchronous wrapper around extract_candidate_facts."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(extract_candidate_facts(
            resume_text,
            cover_letter_text=cover_letter_text,
            custom_questions_and_answers=custom_questions_and_answers,
        ))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: asyncio.run(extract_candidate_facts(
            resume_text,
            cover_letter_text=cover_letter_text,
            custom_questions_and_answers=custom_questions_and_answers,
        )))
        return future.result()


# ==============================================================================
# VERIFICATION TEST OUTPUTS — March 4, 2026 (Updated after Python-calculated fields fix)
# Run via test_extraction_verification.py against 3 test resumes.
# years_used, employment_gaps, and average_tenure_years are now calculated
# in Python after Gemini extraction, not by Gemini itself.
# ==============================================================================
#
# --- TEST CASE 1: Strong resume (clear dates, many skills, degree) ---
# {
#   "name": "Unknown Candidate",
#   "email": "jane.smith@example.com",
#   "phone": "555) 123-4567",
#   "total_years_experience": 10.0,
#   "highest_education_level": "Masters",
#   "job_titles": ["Senior Software Engineer", "Software Engineer", "Junior Developer"],
#   "skills": ["python", "go", "kubernetes", "postgresql", "redis", "kafka", "aws",
#     "ruby", "react", "typescript", "mysql", "docker", "graphql", "java",
#     "spring boot", "oracle db", "angular", "ruby on rails", "javascript", "git",
#     "ci/cd", "terraform", "gcp"],
#   "skills_with_years": {"python": 5.0, "go": 5.0, "kubernetes": 5.0, "postgresql": 5.0,
#     "redis": 5.0, "kafka": 5.0, "aws": 5.0, "ruby": 3.0, "react": 3.0,
#     "typescript": 3.0, "mysql": 3.0, "docker": 3.0, "graphql": 3.0, "java": 3.0,
#     "spring boot": 3.0, "oracle db": 3.0, "angular": 3.0, "ruby on rails": 3.0,
#     "javascript": 1.0, "git": 1.0, "ci/cd": 1.0, "terraform": 1.0, "gcp": 1.0},
#   "skill_matches": [
#     {"skill": "Python", "matched": true},
#     {"skill": "React", "matched": true},
#     {"skill": "AWS", "matched": true}
#   ],
#   "requires_sponsorship": false,
#   "requires_visa_sponsorship": false,
#   "extractable_text": true,
#   "has_measurable_impact": true,
#   "has_contact_info": true,
#   "has_clear_job_titles": true,
#   "employment_gaps": true,
#   "average_tenure_years": 3.7,
#   "skills_detailed": [
#     {"name": "python", "last_used_year": 2023, "job_index": 0, "years_used": 5},
#     {"name": "go", "last_used_year": 2023, "job_index": 0, "years_used": 5},
#     {"name": "kubernetes", "last_used_year": 2023, "job_index": 0, "years_used": 5},
#     {"name": "postgresql", "last_used_year": 2023, "job_index": 0, "years_used": 5},
#     {"name": "redis", "last_used_year": 2023, "job_index": 0, "years_used": 5},
#     {"name": "kafka", "last_used_year": 2023, "job_index": 0, "years_used": 5},
#     {"name": "aws", "last_used_year": 2023, "job_index": 0, "years_used": 5},
#     {"name": "ruby", "last_used_year": 2020, "job_index": 1, "years_used": 3},
#     {"name": "react", "last_used_year": 2020, "job_index": 1, "years_used": 3},
#     {"name": "typescript", "last_used_year": 2020, "job_index": 1, "years_used": 3},
#     {"name": "mysql", "last_used_year": 2020, "job_index": 1, "years_used": 3},
#     {"name": "docker", "last_used_year": 2020, "job_index": 1, "years_used": 3},
#     {"name": "graphql", "last_used_year": 2020, "job_index": 1, "years_used": 3},
#     {"name": "java", "last_used_year": 2017, "job_index": 2, "years_used": 3},
#     {"name": "spring boot", "last_used_year": 2017, "job_index": 2, "years_used": 3},
#     {"name": "oracle db", "last_used_year": 2017, "job_index": 2, "years_used": 3},
#     {"name": "angular", "last_used_year": 2017, "job_index": 2, "years_used": 3},
#     {"name": "ruby on rails", "last_used_year": 2020, "job_index": 1, "years_used": 3},
#     {"name": "javascript", "last_used_year": null, "job_index": null, "years_used": null},
#     {"name": "git", "last_used_year": null, "job_index": null, "years_used": null},
#     {"name": "ci/cd", "last_used_year": null, "job_index": null, "years_used": null},
#     {"name": "terraform", "last_used_year": null, "job_index": null, "years_used": null},
#     {"name": "gcp", "last_used_year": null, "job_index": null, "years_used": null}
#   ],
#   "education": [
#     {"degree": "master", "field_of_study": "computer science", "institution": "stanford university", "year": 2014},
#     {"degree": "bachelor", "field_of_study": "mathematics", "institution": "uc berkeley", "year": 2012}
#   ],
#   "jobs": [
#     {"title": "Senior Software Engineer", "company": "Stripe", "start_year": 2021,
#      "end_year": null, "is_current": true, "domain": "fintech", "work_type": "remote"},
#     {"title": "Software Engineer", "company": "Shopify", "start_year": 2017,
#      "end_year": 2020, "is_current": false, "domain": "ecommerce", "work_type": "unknown"},
#     {"title": "Junior Developer", "company": "Accenture", "start_year": 2014,
#      "end_year": 2017, "is_current": false, "domain": "enterprise", "work_type": "unknown"}
#   ],
#   "cover_letter_analysis": {
#     "word_count": 0, "mentions_role_title": false, "skills_mentioned": [],
#     "has_specific_example": false, "is_generic": false
#   },
#   "custom_answer_analysis": []
# }
#
# --- TEST CASE 2: Employment gaps, no degree ---
# {
#   "name": "Unknown Candidate",
#   "email": "mike.j@gmail.com",
#   "phone": "",
#   "total_years_experience": 6.0,
#   "highest_education_level": "None",
#   "job_titles": ["Freelance Web Developer", "Data Entry Clerk", "Warehouse Associate", "Barista"],
#   "skills": ["html", "css", "javascript", "php", "wordpress", "microsoft excel", "microsoft access"],
#   "skills_with_years": {"html": 2.0, "css": 2.0, "javascript": 2.0, "php": 2.0,
#     "wordpress": 2.0, "microsoft excel": 2.0, "microsoft access": 2.0},
#   "skill_matches": [
#     {"skill": "Python", "matched": false},
#     {"skill": "React", "matched": false},
#     {"skill": "AWS", "matched": false}
#   ],
#   "requires_sponsorship": false,
#   "requires_visa_sponsorship": false,
#   "extractable_text": true,
#   "has_measurable_impact": true,
#   "has_contact_info": true,
#   "has_clear_job_titles": true,
#   "employment_gaps": true,
#   "average_tenure_years": 1.5,
#   "skills_detailed": [
#     {"name": "html", "last_used_year": 2024, "job_index": 0, "years_used": 2},
#     {"name": "css", "last_used_year": 2024, "job_index": 0, "years_used": 2},
#     {"name": "javascript", "last_used_year": 2024, "job_index": 0, "years_used": 2},
#     {"name": "php", "last_used_year": 2024, "job_index": 0, "years_used": 2},
#     {"name": "wordpress", "last_used_year": 2024, "job_index": 0, "years_used": 2},
#     {"name": "microsoft excel", "last_used_year": 2022, "job_index": 1, "years_used": 2},
#     {"name": "microsoft access", "last_used_year": 2022, "job_index": 1, "years_used": 2}
#   ],
#   "education": [],
#   "jobs": [
#     {"title": "Freelance Web Developer", "company": "Freelance", "start_year": 2024,
#      "end_year": null, "is_current": true, "domain": "other", "work_type": "unknown"},
#     {"title": "Data Entry Clerk", "company": "OfficeMax", "start_year": 2020,
#      "end_year": 2022, "is_current": false, "domain": "other", "work_type": "unknown"},
#     {"title": "Warehouse Associate", "company": "Amazon", "start_year": 2018,
#      "end_year": 2018, "is_current": false, "domain": "logistics", "work_type": "unknown"},
#     {"title": "Barista", "company": "Starbucks", "start_year": 2015,
#      "end_year": 2017, "is_current": false, "domain": "other", "work_type": "unknown"}
#   ],
#   "cover_letter_analysis": {
#     "word_count": 0, "mentions_role_title": false, "skills_mentioned": [],
#     "has_specific_example": false, "is_generic": false
#   },
#   "custom_answer_analysis": []
# }
#
# --- TEST CASE 3: Minimal / poorly formatted resume ---
# {
#   "name": "Unknown Candidate",
#   "email": "alexthompson99@hotmail.com",
#   "phone": "2019-2021",
#   "total_years_experience": 2.0,
#   "highest_education_level": "None",
#   "job_titles": ["doing stuff"],
#   "skills": ["python", "excel"],
#   "skills_with_years": {"python": 2.0, "excel": 2.0},
#   "skill_matches": [
#     {"skill": "Python", "matched": true},
#     {"skill": "React", "matched": false},
#     {"skill": "AWS", "matched": false}
#   ],
#   "requires_sponsorship": false,
#   "requires_visa_sponsorship": false,
#   "extractable_text": true,
#   "has_measurable_impact": false,
#   "has_contact_info": true,
#   "has_clear_job_titles": true,
#   "employment_gaps": false,
#   "average_tenure_years": 2.0,
#   "skills_detailed": [
#     {"name": "python", "last_used_year": 2021, "job_index": 0, "years_used": 2},
#     {"name": "excel", "last_used_year": 2021, "job_index": 0, "years_used": 2}
#   ],
#   "education": [
#     {"degree": "none", "field_of_study": null, "institution": null, "year": null}
#   ],
#   "jobs": [
#     {"title": "doing stuff", "company": "some company", "start_year": 2019,
#      "end_year": 2021, "is_current": false, "domain": "other", "work_type": "unknown"}
#   ],
#   "cover_letter_analysis": {
#     "word_count": 0, "mentions_role_title": false, "skills_mentioned": [],
#     "has_specific_example": false, "is_generic": false
#   },
#   "custom_answer_analysis": []
# }
