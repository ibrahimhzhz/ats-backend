import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
import json
import os
import asyncio
import concurrent.futures
import time
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
credentials_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
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

# --- 3. LEVEL 1: JD REQUIREMENT EXTRACTION (Grounded) ---

async def extract_jd_requirements(jd_text: str) -> List[str]:
    """
    LEVEL 1: Rule-Based JD Extraction
    
    Extracts verbatim requirement sentences from a Job Description.
    These will be used in Level 2 for grounded verification.
    
    Returns:
        List of exact, verbatim requirement sentences from the JD.
    """
    print("📋 Extracting JD requirements (Level 1: Grounded Extraction)...")
    await rate_limiter.wait_if_needed()
    model = _get_model()
    if model is None:
        return []

    prompt = f"""
    You are a strict compliance parser. Extract every single sentence from the provided 
    Job Description that contains a hard requirement (look for verbs like 'require', 
    'must', 'need', 'should have', 'experience with', 'knowledge of', 'proficiency in').

    CRITICAL CONSTRAINT: You must extract the exact, verbatim sentence. Do not summarize. 
    Do not interpret. Do not rephrase. Copy-paste the exact sentence as it appears.

    JOB DESCRIPTION:
    {jd_text[:8000]}

    Return a strict JSON array of strings. Each string is an exact requirement sentence.
    Example: ["Candidate must have 3+ years of Python experience.", "Bachelor's degree in Computer Science required."]
    
    Return ONLY the JSON array. No markdown, no explanation.
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
        requirements = json.loads(json_text)
        
        # Validate it's a list of strings
        if not isinstance(requirements, list):
            print(f"⚠️ AI returned non-list: {type(requirements)}")
            return []
        
        # Filter to only strings
        requirements = [str(req) for req in requirements if req and isinstance(req, str)]
        
        print(f"✅ Extracted {len(requirements)} JD requirements")
        return requirements

    except Exception as e:
        print(f"❌ JD REQUIREMENT EXTRACTION FAILED: {str(e)}")
        return []


# --- 4. LEVEL 2: GROUNDED RESUME VERIFICATION ---

async def extract_candidate_facts(
    resume_text: str,
    jd_requirements: List[str] = None,
    fail_on_unavailable: bool = True,
) -> Dict[str, Any]:
    """
    LEVEL 2: Grounded Resume Verification
    
    Single-pass fact extraction with optional JD requirement matching.
    If jd_requirements are provided, the AI must provide verbatim citation quotes.
    """
    print("🤖 Sending resume to Gemini for fact extraction (single pass)...")
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
            "recent_job_titles": [],
            "skills_with_years": {},
            "metrics_bullet_count": 0,
        }

    # Base extraction fields
    base_schema = """
    {{
        "name": "Full Name or Unknown",
        "email": "email@example.com",
        "phone": "number or empty string",
        "total_years_experience": 3.5,
        "recent_job_titles": ["Software Engineer", "Junior Developer"],
        "skills_with_years": {{"Python": 3.5, "SQL": 1.0, "Docker": 0.5}},
        "metrics_bullet_count": 4"""
    
    # Add requirement matching if JD requirements provided
    if jd_requirements and len(jd_requirements) > 0:
        req_schema = """,
        "jd_requirement_matches": [
            {{
                "requirement": "exact requirement sentence",
                "is_met": true,
                "citation_quote": "exact verbatim text from resume proving this requirement"
            }}
        ]"""
        full_schema = base_schema + req_schema + "\n    }"
        
        requirements_section = f"""
    
    JD REQUIREMENTS TO VERIFY:
    {json.dumps(jd_requirements, indent=2)}
    
    REQUIREMENT MATCHING RULES (CRITICAL):
    - For EACH requirement in the list above, you must add an entry to "jd_requirement_matches"
    - If the candidate meets the requirement based on their resume, set "is_met": true
    - CRITICAL CONSTRAINT: If "is_met" is true, you MUST provide an exact, verbatim 
      copy-pasted string from the resume in "citation_quote". This should be the 
      specific sentence or phrase that proves they meet the requirement.
    - If no exact text evidence exists in the resume, "is_met" must be false and 
      "citation_quote" must be null
    - Do NOT summarize or paraphrase the citation - it must be word-for-word from the resume
    """
    else:
        full_schema = base_schema + "\n    }"
        requirements_section = ""

    prompt = f"""
    You are a precise data extraction AI. Your ONLY job is to extract factual
    data from a resume. Do NOT evaluate, score, or judge the candidate.

    RESUME TEXT:
    {resume_text[:12000]}
    {requirements_section}

    Return a SINGLE valid JSON object with EXACTLY this structure and no other keys:
    {full_schema}

    EXTRACTION RULES — follow strictly:
    1. total_years_experience: Calculate from employment date ranges if present. Float. 0.0 if none found.
    2. recent_job_titles: List every job title string found in the resume. Empty list [] if none.
    3. skills_with_years: Map each distinct technical skill to estimated years of experience (float).
       Derive from employment dates. If duration is unclear, use 0.5 as the minimum for any mentioned skill.
       Use the exact skill name as written in the resume.
    4. metrics_bullet_count: Count the number of bullet points or sentence fragments that contain
       at least one quantitative element — a number, %, $, revenue figure, growth rate, or similar.
    5. Return ONLY the JSON object. No prose, no markdown, no explanation.
    """

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(
                prompt,
                generation_config=GenerationConfig(
                    temperature=0.0,  # Maximum determinism for consistent scoring
                    response_mime_type="application/json"
                )
            )
        )
        json_text = clean_json_string(response.text)
        data = json.loads(json_text)

        # --- Type sanitization — never trust LLM types blindly ---
        data["total_years_experience"] = float(data.get("total_years_experience") or 0)
        data["recent_job_titles"] = data.get("recent_job_titles") or []
        if not isinstance(data["recent_job_titles"], list):
            data["recent_job_titles"] = []
        data["skills_with_years"] = data.get("skills_with_years") or {}
        if not isinstance(data["skills_with_years"], dict):
            data["skills_with_years"] = {}
        # Ensure all skill year values are floats
        data["skills_with_years"] = {
            k: float(v) for k, v in data["skills_with_years"].items()
        }
        data["metrics_bullet_count"] = int(data.get("metrics_bullet_count") or 0)
        data.setdefault("name", "Unknown Candidate")
        data.setdefault("email", "unknown@error.com")
        data.setdefault("phone", "")
        
        # Sanitize JD requirement matches if present
        if "jd_requirement_matches" in data:
            matches = data.get("jd_requirement_matches") or []
            if not isinstance(matches, list):
                matches = []
            # Ensure each match has required fields
            sanitized_matches = []
            for match in matches:
                if isinstance(match, dict):
                    sanitized_matches.append({
                        "requirement": str(match.get("requirement", "")),
                        "is_met": bool(match.get("is_met", False)),
                        "citation_quote": match.get("citation_quote")  # Can be None
                    })
            data["jd_requirement_matches"] = sanitized_matches

        print("✅ Vertex AI Fact Extraction Successful")
        return data

    except Exception as e:
        print(f"❌ VERTEX AI EXTRACTION FAILED: {str(e)}")
        return {
            "name": "Unknown Candidate",
            "email": "unknown@error.com",
            "phone": "",
            "total_years_experience": 0.0,
            "recent_job_titles": [],
            "skills_with_years": {},
            "metrics_bullet_count": 0,
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
) -> Dict[str, Any]:
    """
    LEVEL 3: Python Anti-Hallucination & Deterministic Scoring
    
    Deterministic, bias-free scoring algorithm.
    LLM extracted the facts; Python does the math and verifies citations.

    Weights:
      Skill Depth         40 pts  (depth per required skill, capped by min_experience)
      JD Requirements     30 pts  (grounded requirement matching with citation verification)
      Experience          20 pts  (capped at min_experience + 2 years)
      Impact              10 pts  (quantitative bullet points, 5+ = full marks)
    Total:               100 pts
    """
    skills_with_years: Dict[str, float] = candidate.get("skills_with_years") or {}
    total_years_experience: float = float(candidate.get("total_years_experience") or 0)
    metrics_bullet_count: int = int(candidate.get("metrics_bullet_count") or 0)
    jd_requirement_matches: List[Dict] = candidate.get("jd_requirement_matches") or []

    # Normalise skill keys to lowercase once
    candidate_skills_lower: Dict[str, float] = {
        k.lower(): v for k, v in skills_with_years.items()
    }
    required_skills_lower: List[str] = [s.lower() for s in required_skills]

    # ── 1. Skill Depth Score (40 pts) ────────────────────────────────────
    skill_depth_parts: List[float] = []
    matched_skills: List[str] = []
    effective_min = max(min_experience, 1.0)  # avoid division by zero

    for req_skill in required_skills_lower:
        matched_key, candidate_yrs = _fuzzy_match_skill(req_skill, candidate_skills_lower)
        if matched_key is not None:
            depth = min(1.0, candidate_yrs / effective_min)
            skill_depth_parts.append(depth)
            matched_skills.append(req_skill)
        else:
            skill_depth_parts.append(0.0)

    avg_depth = (
        sum(skill_depth_parts) / len(skill_depth_parts)
        if skill_depth_parts else 0.0
    )
    skill_depth_points = avg_depth * 40.0
    matched_skills_count = len(matched_skills)

    # ── 2. JD Requirements Score (30 pts) with Anti-Hallucination ────────
    # LEVEL 3: Python verifies citation quotes exist in resume text
    jd_requirements_points = 0.0
    verified_requirements = 0
    total_requirements = len(jd_requirement_matches)
    hallucination_count = 0
    
    if total_requirements > 0 and raw_resume_text:
        # Normalize resume text for comparison (preserve essential content)
        normalized_resume = " ".join(raw_resume_text.split()).lower()
        
        for match in jd_requirement_matches:
            is_met = match.get("is_met", False)
            citation_quote = match.get("citation_quote")
            
            if is_met and citation_quote:
                # ANTI-HALLUCINATION CHECK: Verify citation exists in resume
                normalized_citation = " ".join(str(citation_quote).split()).lower()
                
                if normalized_citation in normalized_resume:
                    # Citation verified - requirement truly met
                    verified_requirements += 1
                else:
                    # HALLUCINATION DETECTED: AI claimed evidence that doesn't exist
                    hallucination_count += 1
                    print(f"⚠️ HALLUCINATION DETECTED: Citation not found in resume")
            elif is_met and not citation_quote:
                # AI said requirement is met but provided no evidence - reject
                hallucination_count += 1
        
        # Calculate score: percentage of verified requirements
        jd_requirements_points = (verified_requirements / total_requirements) * 30.0
        print(f"📊 JD Requirements: {verified_requirements}/{total_requirements} verified ({hallucination_count} hallucinations blocked)")

    # ── 3. Experience Score (20 pts) ─────────────────────────────────────
    # Simple logic: meet or exceed min_experience = full marks
    # Below requirement = proportionally reduced
    if total_years_experience >= min_experience:
        experience_points = 20.0
    else:
        # Proportional scoring for candidates below requirement
        experience_points = (total_years_experience / max(min_experience, 1.0)) * 20.0

    # ── 4. Impact Score (10 pts) ─────────────────────────────────────────
    # 5 or more quantitative bullets = full marks
    impact_points = min(10.0, (metrics_bullet_count / 5.0) * 10.0)

    # ── Final Score ───────────────────────────────────────────────────────
    raw = skill_depth_points + jd_requirements_points + experience_points + impact_points
    final_score = int(round(raw))

    # ── Status Bucketing ─────────────────────────────────────────────────
    if final_score >= 80:
        status = "shortlisted"
    elif final_score >= 60:
        status = "review"
    else:
        status = "rejected"

    # ── Python-Generated Summary (no LLM) ────────────────────────────────
    # Generate natural language candidate description
    candidate_name = candidate.get("name", "Candidate")
    
    # Build skill description from matched skills
    if matched_skills_count > 0:
        skill_list = ", ".join(matched_skills[:3])  # Show top 3 matched skills
        more_skills = f" and {matched_skills_count - 3} more" if matched_skills_count > 3 else ""
        skills_desc = f"Proficient in {skill_list}{more_skills}"
    else:
        skills_desc = "Limited match with required technical skills"
    
    # Build experience description
    exp_desc = f"with {total_years_experience:.1f} years of professional experience"
    
    # Build performance/impact description
    if metrics_bullet_count >= 5:
        impact_desc = "Strong track record of measurable achievements and quantifiable impact"
    elif metrics_bullet_count >= 3:
        impact_desc = "Demonstrates results-oriented approach with documented achievements"
    elif metrics_bullet_count >= 1:
        impact_desc = "Shows some evidence of measurable contributions"
    else:
        impact_desc = "Limited quantifiable achievements documented"
    
    # Build JD requirements description
    if total_requirements > 0:
        req_percentage = (verified_requirements / total_requirements) * 100
        if req_percentage >= 80:
            jd_desc = "Meets most job requirements"
        elif req_percentage >= 50:
            jd_desc = "Partially meets job requirements"
        else:
            jd_desc = "Limited alignment with specific job requirements"
    else:
        jd_desc = ""
    
    # Combine into natural 2-3 line summary
    summary_parts = [f"{skills_desc} {exp_desc}.", impact_desc + "."]
    if jd_desc:
        summary_parts.append(jd_desc + ".")
    
    summary = " ".join(summary_parts)

    return {
        "final_score": final_score,
        "status": status,
        "summary": summary,
        "matched_skills_count": matched_skills_count,
        "matched_skills": matched_skills,
        "verified_requirements": verified_requirements,
        "total_requirements": total_requirements,
        "hallucination_count": hallucination_count,
        "breakdown": {
            "skill_depth": round(skill_depth_points, 1),
            "jd_requirements": round(jd_requirements_points, 1),
            "experience": round(experience_points, 1),
            "impact": round(impact_points, 1),
        },
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
