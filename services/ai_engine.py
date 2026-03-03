import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
import json
import os
import asyncio
import concurrent.futures
import time
import re
from dotenv import dotenv_values
from pathlib import Path
from typing import Dict, Any, List, Optional

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
            "type": "NUMBER",
            "description": "Calculated total years of professional working experience from date ranges. Return a decimal when needed (e.g., 0.5, 1.5). Return 0 only if none.",
        },
        "skills": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {
                        "type": "STRING",
                        "description": "The canonical skill name (e.g. 'Python', 'React', 'AWS').",
                    },
                    "years": {
                        "type": "NUMBER",
                        "description": "Estimated years of experience with this skill inferred from job date ranges. Use 0.5 for less than 1 year. Never exceed total_years_experience.",
                    },
                },
                "required": ["name", "years"],
            },
            "description": "All explicitly mentioned skills with estimated years of experience per skill.",
        },
        "highest_education_level": {
            "type": "STRING",
            "description": "Highest degree earned. Must be exactly one of: 'High School', 'Bachelors', 'Masters', 'PhD', or 'None'.",
        },
        "job_titles": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "List of all professional job titles held by the candidate.",
        },
        "requires_sponsorship": {
            "type": "BOOLEAN",
            "description": "True if the resume explicitly mentions needing a visa, OPT, CPT, or sponsorship. False otherwise.",
        },
    },
    "required": [
        "total_years_experience",
        "skills",
        "highest_education_level",
        "job_titles",
        "requires_sponsorship",
    ],
}


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

async def extract_candidate_facts(
    resume_text: str,
    job_requirements: Optional[Dict[str, Any]] = None,
    fail_on_unavailable: bool = True,
) -> Dict[str, Any]:
    """
    LEVEL 2: Grounded Resume Verification
    
    Single-pass factual extraction from a resume.
    AI performs extraction only (no evaluation/judgment).
    """
    print("🤖 Sending resume to Gemini for strict fact extraction...")
    await rate_limiter.wait_if_needed()
    model = _get_model()
    if model is None:
        if fail_on_unavailable:
            reason = get_ai_unavailable_reason() or "AI extraction service is unavailable"
            raise AIServiceUnavailableError(reason)
        return {
            "name": "Unknown Candidate",
            "email": "unknown@error.com",
            "phone": "",
            "total_years_experience": 0.0,
            "highest_education_level": "None",
            "job_titles": [],
            "skills": [],
            "skills_with_years": {},
            "skill_matches": [],
            "requires_sponsorship": False,
            "requires_visa_sponsorship": False,
        }

    normalized_requirements = normalize_job_requirements(job_requirements)
    required_skills = normalized_requirements.get("must_have_skills", [])

    prompt = f"""
    You are a strict, objective data extraction system for an Applicant Tracking System (ATS).
    Your ONLY job is to read the following resume text and extract the facts exactly as requested.

    RULES:
    1. Do not evaluate the candidate or make hiring decisions.
    2. Do not infer or guess skills not explicitly written in the text.
    3. Calculate total_years_experience strictly from the date ranges provided.
     3a. Use decimal years for partial experience (e.g., 0.5, 1.5) instead of rounding down.
    4. For each skill, estimate years by summing the date ranges of jobs where that skill was used.
       If no dates are available, use 1.0. Never exceed total_years_experience for any single skill.
    5. Use 0.5 for skills used less than 1 year.

    RAW RESUME TEXT:
    {resume_text[:12000]}
    """

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
        extracted = json.loads(json_text)

        try:
            total_years_experience = float(extracted.get("total_years_experience") or 0.0)
        except (TypeError, ValueError):
            total_years_experience = 0.0

        extracted_skills = extracted.get("skills") or []
        if not isinstance(extracted_skills, list):
            extracted_skills = []

        # Build skills_with_years from structured {name, years} objects.
        # Gracefully handle legacy plain-string responses from the API.
        skills_with_years: Dict[str, float] = {}
        skills: List[str] = []
        for item in extracted_skills:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                try:
                    years = float(item.get("years") or 1.0)
                except (TypeError, ValueError):
                    years = 1.0
            else:
                name = str(item).strip()
                years = 1.0
            if name:
                skills.append(name)
                skills_with_years[name] = max(0.5, years)  # floor at 0.5

        highest_education_level = str(extracted.get("highest_education_level") or "None").strip() or "None"

        extracted_job_titles = extracted.get("job_titles") or []
        if not isinstance(extracted_job_titles, list):
            extracted_job_titles = []
        job_titles = [str(title).strip() for title in extracted_job_titles if str(title).strip()]

        requires_sponsorship = bool(extracted.get("requires_sponsorship", False))
        extracted_skill_set = {skill.lower() for skill in skills}
        skill_matches = [
            {
                "skill": skill,
                "matched": skill.lower() in extracted_skill_set,
            }
            for skill in required_skills
        ]

        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", resume_text)
        phone_match = re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", resume_text)
        name = "Unknown Candidate"
        first_line = (resume_text or "").splitlines()[0].strip() if resume_text else ""
        if first_line and len(first_line.split()) <= 6 and "@" not in first_line:
            name = first_line

        data = {
            "name": name,
            "email": email_match.group(0).lower() if email_match else "unknown@error.com",
            "phone": phone_match.group(0).strip() if phone_match else "",
            "total_years_experience": float(total_years_experience),
            "highest_education_level": highest_education_level,
            "job_titles": job_titles,
            "skills": skills,
            "skills_with_years": skills_with_years,
            "skill_matches": skill_matches,
            "requires_sponsorship": requires_sponsorship,
            "requires_visa_sponsorship": requires_sponsorship,
        }

        print("✅ Vertex AI Fact Extraction Successful")
        return data

    except Exception as e:
        print(f"❌ VERTEX AI EXTRACTION FAILED: {str(e)}")
        return {
            "name": "Unknown Candidate",
            "email": "unknown@error.com",
            "phone": "",
            "total_years_experience": 0.0,
            "highest_education_level": "None",
            "job_titles": [],
            "skills": [],
            "skills_with_years": {},
            "skill_matches": [],
            "requires_sponsorship": False,
            "requires_visa_sponsorship": False,
        }


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

def extract_candidate_facts_sync(resume_text: str) -> Dict[str, Any]:
    """Synchronous wrapper around extract_candidate_facts."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(extract_candidate_facts(resume_text))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: asyncio.run(extract_candidate_facts(resume_text)))
        return future.result()
