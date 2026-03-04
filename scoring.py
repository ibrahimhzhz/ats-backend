# scoring.py
# Pure scoring functions and constants for the ATS scoring engine.
# No database, ORM, or external service dependencies — plain Python only.

from __future__ import annotations
from datetime import date

# ==============================================================================
# CONSTANTS — single source of truth for all scoring logic
# ==============================================================================

CURRENT_YEAR = 2026

SCORE_WEIGHTS = {
    "experience": 25,
    "skills": 35,
    "education": 15,
    "role_level": 10,
    "application_quality": 15,
}

DEGREE_RANK = {
    "none": 0,
    "high school": 1,
    "associate": 2,
    "bachelor": 3,
    "master": 4,
    "phd": 5,
}

SENIORITY_LEVELS = {
    "intern": 0, "trainee": 0,
    "junior": 1, "entry": 1, "entry-level": 1,
    "associate": 1,
    "mid": 2, "intermediate": 2, "mid-level": 2,
    "senior": 3, "sr": 3,
    "lead": 4, "tech lead": 4, "team lead": 4,
    "principal": 5, "staff": 5,
    "manager": 5, "engineering manager": 5,
    "director": 6, "head": 6,
    "vp": 7, "vice president": 7,
    "c-level": 8, "cto": 8, "ceo": 8, "coo": 8,
}

FIELD_RELEVANCE = {
    "engineering": {
        "computer science": 1.0,
        "software engineering": 1.0,
        "computer engineering": 1.0,
        "data science": 0.95,
        "information technology": 0.9,
        "information systems": 0.85,
        "mathematics": 0.85,
        "statistics": 0.8,
        "physics": 0.75,
        "electrical engineering": 0.7,
        "business": 0.4,
        "other": 0.5,
    },
    "product": {
        "computer science": 0.9,
        "business": 0.85,
        "product management": 1.0,
        "information technology": 0.8,
        "psychology": 0.7,
        "design": 0.75,
        "other": 0.5,
    },
    "design": {
        "design": 1.0,
        "fine arts": 0.9,
        "human computer interaction": 1.0,
        "computer science": 0.7,
        "psychology": 0.75,
        "other": 0.4,
    },
    "marketing": {
        "marketing": 1.0,
        "business": 0.9,
        "communications": 0.85,
        "psychology": 0.75,
        "data science": 0.7,
        "other": 0.4,
    },
    "finance": {
        "finance": 1.0,
        "accounting": 0.95,
        "economics": 0.9,
        "mathematics": 0.85,
        "business": 0.8,
        "statistics": 0.75,
        "other": 0.35,
    },
}

SKILL_ALIASES = {
    "react": ["reactjs", "react.js", "react js", "react native"],
    "node": ["nodejs", "node.js", "node js"],
    "postgres": ["postgresql", "postgres", "pg", "psql"],
    "k8s": ["kubernetes", "k8s", "kube"],
    "ml": ["machine learning", "artificial intelligence", "ai/ml"],
    "aws": ["amazon web services", "amazon aws", "aws cloud"],
    "gcp": ["google cloud", "google cloud platform", "google cloud services"],
    "js": ["javascript", "vanilla js", "vanilla javascript"],
    "ts": ["typescript"],
    "py": ["python", "python3", "python 3"],
    "tf": ["tensorflow", "tensor flow"],
    "torch": ["pytorch", "torch"],
    "mongo": ["mongodb", "mongo db"],
    "redis": ["redis cache", "redis db"],
    "docker": ["docker container", "containerization"],
    "vue": ["vuejs", "vue.js", "vue js"],
    "angular": ["angularjs", "angular.js", "angular js"],
}


# ==============================================================================
# PURE HELPER FUNCTIONS
# ==============================================================================

def normalize_skill(skill: str) -> str:
    """
    Lowercases and strips the skill string then checks it against
    SKILL_ALIASES. Returns the canonical key if matched, otherwise
    returns the cleaned original string.
    """
    cleaned = skill.lower().strip()
    for canonical, aliases in SKILL_ALIASES.items():
        if cleaned == canonical or cleaned in aliases:
            return canonical
    return cleaned


def extract_seniority_level(title: str) -> int:
    """
    Maps a job title string to a numeric seniority level using
    SENIORITY_LEVELS. Checks each keyword against the lowercased title.
    Returns 2 (mid-level) as the default if no keyword matches.
    """
    if not title:
        return 2
    title_lower = title.lower()
    for keyword, level in SENIORITY_LEVELS.items():
        if keyword in title_lower:
            return level
    return 2


def score_experience(
    total_years: int,
    required_years: int,
    extracted_jobs: list,
    required_domain: str | None = None,
    overqualification_penalty: bool = False,
) -> dict:
    """
    Returns:
    {
        "total_exp_score": int,   # out of 15
        "domain_exp_score": int,  # out of 10
        "total": int              # out of 25
    }
    """
    delta = total_years - required_years

    if total_years == 0 and required_years >= 3:
        total_exp_score = 0
    elif delta < -3:
        total_exp_score = 0
    elif delta < -2:
        total_exp_score = 4
    elif delta < -1:
        total_exp_score = 8
    elif delta < 0:
        total_exp_score = 11
    elif delta == 0:
        total_exp_score = 15
    elif delta <= 3:
        total_exp_score = 15
    elif delta <= 5:
        total_exp_score = 13
    else:
        total_exp_score = 8 if overqualification_penalty else 15

    if not required_domain or not extracted_jobs:
        domain_exp_score = 10
    else:
        domain_years = sum(
            (job.get("end_year") or CURRENT_YEAR) - job.get("start_year", CURRENT_YEAR)
            for job in extracted_jobs
            if job.get("domain", "").lower() == required_domain.lower()
            and job.get("start_year")
        )
        if domain_years >= required_years:
            domain_exp_score = 10
        elif domain_years >= required_years * 0.6:
            domain_exp_score = 7
        elif domain_years >= required_years * 0.3:
            domain_exp_score = 4
        else:
            domain_exp_score = 1

    return {
        "total_exp_score": total_exp_score,
        "domain_exp_score": domain_exp_score,
        "total": total_exp_score + domain_exp_score,
    }


def score_skills(
    skills_detailed: list,
    required_skills: list,
    nice_to_have_skills: list,
    job_seniority_level: int,
) -> dict:
    """
    Returns:
    {
        "required_score": int,        # out of 20
        "nice_to_have_score": int,    # out of 8
        "depth_recency_score": int,   # out of 7
        "total": int,                 # out of 35
        "matched_required": list,
        "missing_required": list,
    }
    """
    candidate_skill_map = {
        normalize_skill(s["name"]): s
        for s in (skills_detailed or [])
        if s.get("name")
    }
    normalized_required = [normalize_skill(s) for s in (required_skills or [])]
    normalized_nice = [normalize_skill(s) for s in (nice_to_have_skills or [])]

    matched_required = [s for s in normalized_required if s in candidate_skill_map]
    missing_required = [s for s in normalized_required if s not in candidate_skill_map]

    if normalized_required:
        required_score = round((len(matched_required) / len(normalized_required)) * 20)
    else:
        required_score = 20

    if normalized_nice:
        matched_nice = [s for s in normalized_nice if s in candidate_skill_map]
        nice_to_have_score = round((len(matched_nice) / len(normalized_nice)) * 8)
    else:
        nice_to_have_score = 8

    if not matched_required:
        depth_recency_score = 0
    else:
        total_weight = 0.0
        for skill_name in matched_required:
            skill = candidate_skill_map[skill_name]
            years_used = skill.get("years_used") or 0
            last_used_year = skill.get("last_used_year")

            if job_seniority_level >= 3:
                if years_used >= 4:
                    depth = 1.0
                elif years_used >= 2:
                    depth = 0.75
                else:
                    depth = 0.5
            else:
                if years_used >= 2:
                    depth = 1.0
                elif years_used >= 1:
                    depth = 0.85
                else:
                    depth = 0.65

            if last_used_year is None:
                recency = 0.7
            else:
                years_since = CURRENT_YEAR - last_used_year
                if years_since <= 1:
                    recency = 1.0
                elif years_since <= 3:
                    recency = 0.85
                elif years_since <= 5:
                    recency = 0.65
                else:
                    recency = 0.45

            total_weight += depth * recency

        ratio = total_weight / len(matched_required)
        depth_recency_score = round(ratio * 7)

    return {
        "required_score": required_score,
        "nice_to_have_score": nice_to_have_score,
        "depth_recency_score": depth_recency_score,
        "total": required_score + nice_to_have_score + depth_recency_score,
        "matched_required": matched_required,
        "missing_required": missing_required,
    }


def calculate_education_score(
    extracted_education: list,
    required_education: str,
    total_years_exp: int,
    job_department: str | None = None,
) -> dict:
    """
    Returns:
    {
        "degree_score": int,    # out of 10
        "field_score": int,     # out of 5
        "total": int            # out of 15
    }
    """
    if not extracted_education:
        if total_years_exp >= 8:
            return {"degree_score": 9, "field_score": 3, "total": 12}
        elif total_years_exp >= 5:
            return {"degree_score": 6, "field_score": 2, "total": 8}
        else:
            return {"degree_score": 0, "field_score": 0, "total": 0}

    best_edu = max(
        extracted_education,
        key=lambda e: DEGREE_RANK.get(e.get("degree", "none").lower(), 0)
    )

    required_education_clean = (required_education or "bachelor").lower()
    equiv_accepted = "equivalent" in required_education_clean
    req_key = required_education_clean.replace(
        "equivalent experience accepted", "bachelor"
    ).strip()
    req_rank = DEGREE_RANK.get(req_key, 3)
    cand_rank = DEGREE_RANK.get(best_edu.get("degree", "none").lower(), 0)

    if cand_rank >= req_rank:
        degree_score = 10
    elif equiv_accepted or cand_rank == 0:
        if total_years_exp >= 8:
            degree_score = 9
        elif total_years_exp >= 5:
            degree_score = 6
        elif total_years_exp >= 3:
            degree_score = 3
        else:
            degree_score = 0
    else:
        gap = req_rank - cand_rank
        if gap == 1:
            degree_score = 6
        elif gap == 2:
            degree_score = 2
        else:
            degree_score = 0

    field = (best_edu.get("field_of_study") or "other").lower()
    dept = (job_department or "engineering").lower()
    relevance_map = FIELD_RELEVANCE.get(dept, FIELD_RELEVANCE["engineering"])
    multiplier = relevance_map.get(field, relevance_map.get("other", 0.5))
    field_score = round(multiplier * 5)

    return {
        "degree_score": degree_score,
        "field_score": field_score,
        "total": degree_score + field_score,
    }


def calculate_application_quality_score(
    cover_letter: str | None,
    cover_letter_analysis: dict | None,
    portfolio_url: str | None,
    linkedin_url: str | None,
    custom_answer_analysis: list | None,
    require_cover_letter: bool = False,
    require_portfolio: bool = False,
    require_linkedin: bool = False,
    custom_questions: list | None = None,
) -> dict:
    """
    Returns:
    {
        "cover_letter_score": int,    # out of 5
        "portfolio_score": int,       # out of 3
        "linkedin_score": int,        # out of 2
        "custom_answers_score": int,  # out of 5
        "total": int                  # out of 15
    }
    Note: Takes plain values only — no ORM objects.
    """
    analysis = cover_letter_analysis or {}

    # Cover letter
    if require_cover_letter and cover_letter:
        word_count = analysis.get("word_count", 0)
        cl_score = 0
        if word_count >= 200:
            cl_score += 2
        elif word_count >= 100:
            cl_score += 1
        if analysis.get("mentions_role_title"):
            cl_score += 1
        if analysis.get("has_specific_example"):
            cl_score += 1
        if not analysis.get("is_generic"):
            cl_score += 1
        cover_letter_score = min(cl_score, 5)
    elif require_cover_letter and not cover_letter:
        cover_letter_score = 0
    else:
        cover_letter_score = 5

    # Portfolio
    if require_portfolio and portfolio_url:
        if "github.com" in portfolio_url:
            portfolio_score = 3
        else:
            portfolio_score = 2
    elif require_portfolio and not portfolio_url:
        portfolio_score = 0
    else:
        portfolio_score = 3

    # LinkedIn
    if require_linkedin:
        linkedin_score = 2 if linkedin_url else 0
    else:
        linkedin_score = 2

    # Custom answers
    questions = custom_questions or []
    answers = custom_answer_analysis or []

    if not questions:
        custom_answers_score = 5
    elif not answers:
        custom_answers_score = 0
    else:
        per_q = 5 / len(questions)
        total = 0.0
        for answer in answers:
            q_score = 0.0
            word_count = answer.get("word_count", 0)
            if word_count >= 80:
                q_score += per_q * 0.5
            elif word_count >= 30:
                q_score += per_q * 0.25
            if answer.get("is_relevant"):
                q_score += per_q * 0.3
            if answer.get("has_specific_example"):
                q_score += per_q * 0.2
            total += min(q_score, per_q)
        custom_answers_score = round(total)

    return {
        "cover_letter_score": cover_letter_score,
        "portfolio_score": portfolio_score,
        "linkedin_score": linkedin_score,
        "custom_answers_score": custom_answers_score,
        "total": cover_letter_score + portfolio_score + linkedin_score + custom_answers_score,
    }


# ==============================================================================
# ORCHESTRATION FUNCTIONS — wire pure helpers into the live pipeline
# ==============================================================================


def calculate_role_level_score(candidate_jobs: list, job_title: str) -> int:
    """
    Compare the seniority of the candidate's most recent role against the
    target job title.  Returns an integer 0-10.
    """
    if not candidate_jobs:
        return 5  # no data → neutral score

    current_job = next(
        (j for j in candidate_jobs if j.get("is_current")),
        candidate_jobs[0],
    )
    candidate_level = extract_seniority_level(current_job.get("title", ""))
    job_level = extract_seniority_level(job_title)
    delta = abs(candidate_level - job_level)

    if delta == 0:
        return 10
    elif delta == 1:
        return 8
    elif delta == 2:
        return 4
    else:
        return 0


def generate_candidate_signals(candidate_data: dict) -> list:
    """
    Produce a list of UI-ready signal badges from the extraction data.

    Each signal is a dict with keys: type, level, color, label.
    candidate_data should be the extraction result dict, optionally
    enriched with form-submission fields (linkedin_url, portfolio_url, etc.).
    """
    signals: list[dict] = []

    # ── Tenure stability ──────────────────────────────────────────────────
    avg_tenure = float(candidate_data.get("average_tenure_years") or 0)

    if avg_tenure >= 3:
        signals.append({
            "type": "stability", "level": "stable",
            "color": "green", "label": f"Avg tenure {avg_tenure:.1f}y",
        })
    elif avg_tenure >= 1.5:
        signals.append({
            "type": "stability", "level": "neutral",
            "color": "grey", "label": f"Avg tenure {avg_tenure:.1f}y",
        })
    else:
        signals.append({
            "type": "stability", "level": "unstable",
            "color": "yellow", "label": f"Short avg tenure {avg_tenure:.1f}y",
        })

    # ── Job-hopping ───────────────────────────────────────────────────────
    jobs = candidate_data.get("jobs") or []
    recent_jobs = [j for j in jobs if (j.get("start_year") or 0) >= CURRENT_YEAR - 2]
    if len(recent_jobs) >= 3:
        signals.append({
            "type": "job_hopping", "level": "warning",
            "color": "red", "label": "3+ jobs in last 2 years",
        })

    # ── Measurable impact ─────────────────────────────────────────────────
    if candidate_data.get("has_measurable_impact"):
        signals.append({
            "type": "measurable_impact", "level": "positive",
            "color": "green", "label": "Quantified achievements",
        })

    # ── Employment gap ────────────────────────────────────────────────────
    if candidate_data.get("employment_gaps"):
        signals.append({
            "type": "employment_gap", "level": "info",
            "color": "yellow", "label": "Employment gap detected",
        })

    # ── Resume completeness ───────────────────────────────────────────────
    completeness = sum([
        bool(candidate_data.get("has_contact_info")),
        bool(candidate_data.get("linkedin_url")),
        bool(candidate_data.get("has_measurable_impact")),
        bool(candidate_data.get("has_clear_job_titles")),
        not bool(candidate_data.get("employment_gaps")),
    ])
    color = "green" if completeness >= 4 else "yellow" if completeness >= 2 else "red"
    signals.append({
        "type": "completeness", "score": completeness, "max": 5,
        "color": color, "label": f"Resume completeness {completeness}/5",
    })

    return signals


def assign_bucket(score: int, has_hard_knockout: bool) -> str:
    """
    Map a total score + knockout flag to a pipeline bucket.
    Returns one of: "Rejected", "Shortlisted", "Needs Review".
    """
    if has_hard_knockout:
        return "Rejected"
    elif score >= 70:
        return "Shortlisted"
    elif score >= 45:
        return "Needs Review"
    else:
        return "Rejected"


# ── Bucket → legacy status mapping used by the Celery tasks ───────────────
_BUCKET_TO_STATUS = {
    "Rejected": "rejected",
    "Shortlisted": "shortlisted",
    "Needs Review": "review",
}


def bucket_to_status(bucket: str, has_hard_knockout: bool) -> str:
    """Convert an assign_bucket() return value to the legacy status string
    expected by _build_results_payload and the frontend.
    """
    if has_hard_knockout:
        return "knockout"
    return _BUCKET_TO_STATUS.get(bucket, "rejected")


def calculate_deterministic_score(
    candidate_data: dict,
    job_config: dict,
) -> tuple[int, dict]:
    """
    Orchestrate all five scoring components and return (total_score, breakdown).

    Parameters
    ----------
    candidate_data : dict
        The result of ``extract_candidate_facts()`` optionally enriched with
        form-submission fields (cover_letter, portfolio_url, linkedin_url).
    job_config : dict
        Job-level configuration built by the caller.  Expected keys::

            title, min_experience, required_skills, nice_to_have_skills,
            required_education, department, require_cover_letter,
            require_portfolio, require_linkedin, custom_questions

    Returns
    -------
    tuple[int, dict]
        (total_score clamped 0-100, score_breakdown dict)
    """
    # --- unpack candidate ---
    total_years = int(round(float(candidate_data.get("total_years_experience") or 0)))
    skills_detailed = candidate_data.get("skills_detailed") or []
    candidate_jobs = candidate_data.get("jobs") or []
    candidate_education = candidate_data.get("education") or []

    # --- unpack job ---
    job_title = job_config.get("title") or ""
    min_experience = int(job_config.get("min_experience") or 0)
    required_skills = job_config.get("required_skills") or []
    nice_to_have_skills = job_config.get("nice_to_have_skills") or []
    required_education = job_config.get("required_education") or "bachelor"
    department = job_config.get("department")
    require_cover_letter = bool(job_config.get("require_cover_letter"))
    require_portfolio = bool(job_config.get("require_portfolio"))
    require_linkedin = bool(job_config.get("require_linkedin"))
    custom_questions = job_config.get("custom_questions") or []

    # 1. Experience (25 pts)
    exp_result = score_experience(
        total_years=total_years,
        required_years=min_experience,
        extracted_jobs=candidate_jobs,
        required_domain=None,
        overqualification_penalty=False,
    )

    # 2. Skills (35 pts)
    job_seniority = extract_seniority_level(job_title)
    skills_result = score_skills(
        skills_detailed=skills_detailed,
        required_skills=required_skills,
        nice_to_have_skills=nice_to_have_skills,
        job_seniority_level=job_seniority,
    )

    # 3. Education (15 pts)
    edu_result = calculate_education_score(
        extracted_education=candidate_education,
        required_education=required_education,
        total_years_exp=total_years,
        job_department=department,
    )

    # 4. Role level fit (10 pts)
    role_level = calculate_role_level_score(
        candidate_jobs=candidate_jobs,
        job_title=job_title,
    )

    # 5. Application quality (15 pts)
    app_quality = calculate_application_quality_score(
        cover_letter=candidate_data.get("cover_letter"),
        cover_letter_analysis=candidate_data.get("cover_letter_analysis"),
        portfolio_url=candidate_data.get("portfolio_url"),
        linkedin_url=candidate_data.get("linkedin_url"),
        custom_answer_analysis=candidate_data.get("custom_answer_analysis"),
        require_cover_letter=require_cover_letter,
        require_portfolio=require_portfolio,
        require_linkedin=require_linkedin,
        custom_questions=custom_questions,
    )

    # --- assemble ---
    total_score = (
        exp_result["total"]
        + skills_result["total"]
        + edu_result["total"]
        + role_level
        + app_quality["total"]
    )
    total_score = max(0, min(100, total_score))

    score_breakdown = {
        "experience": {
            "total_exp": exp_result["total_exp_score"],
            "domain_exp": exp_result["domain_exp_score"],
            "total": exp_result["total"],
            "max": 25,
        },
        "skills": {
            "required": skills_result["required_score"],
            "nice_to_have": skills_result["nice_to_have_score"],
            "depth_recency": skills_result["depth_recency_score"],
            "total": skills_result["total"],
            "max": 35,
            "matched_required": skills_result["matched_required"],
            "missing_required": skills_result["missing_required"],
        },
        "education": {
            "degree": edu_result["degree_score"],
            "field_relevance": edu_result["field_score"],
            "total": edu_result["total"],
            "max": 15,
        },
        "role_level": {
            "total": role_level,
            "max": 10,
        },
        "application_quality": {
            "cover_letter": app_quality["cover_letter_score"],
            "portfolio": app_quality["portfolio_score"],
            "linkedin": app_quality["linkedin_score"],
            "custom_answers": app_quality["custom_answers_score"],
            "total": app_quality["total"],
            "max": 15,
        },
    }

    return total_score, score_breakdown


def evaluate_knockout_filters(
    candidate_data: dict,
    job_config: dict,
) -> list[dict]:
    """
    Evaluate hard and soft knockout conditions.

    Parameters
    ----------
    candidate_data : dict
        Extraction result dict (optionally enriched with form fields).
    job_config : dict
        Job-level configuration.  Expected keys::

            title, min_experience, required_skills, work_location_type,
            application_deadline, offers_visa_sponsorship,
            require_portfolio, require_linkedin

    Returns
    -------
    list[dict]
        Each element: {"type": str, "severity": "hard"|"soft", "reason": str}
    """
    flags: list[dict] = []

    jobs = candidate_data.get("jobs") or []
    total_years = float(candidate_data.get("total_years_experience") or 0)
    min_experience = float(job_config.get("min_experience") or 0)
    job_title = job_config.get("title") or ""

    # ── HARD knockouts ────────────────────────────────────────────────────
    requires_visa = (
        candidate_data.get("requires_visa_sponsorship")
        or candidate_data.get("requires_sponsorship")
    )
    if requires_visa is True and job_config.get("offers_visa_sponsorship") is False:
        flags.append({
            "type": "visa_sponsorship",
            "severity": "hard",
            "reason": "Candidate requires visa sponsorship but role does not offer it",
        })

    if total_years == 0 and min_experience >= 3:
        flags.append({
            "type": "insufficient_experience",
            "severity": "hard",
            "reason": (
                f"Candidate has 0 years experience, "
                f"role requires {int(min_experience)}"
            ),
        })

    deadline = job_config.get("application_deadline")
    if deadline is not None:
        try:
            if isinstance(deadline, str):
                from datetime import datetime as _dt
                deadline = _dt.fromisoformat(deadline).date()
            if date.today() > deadline:
                flags.append({
                    "type": "past_deadline",
                    "severity": "hard",
                    "reason": "Application submitted after the posting deadline",
                })
        except (TypeError, AttributeError, ValueError):
            pass

    if candidate_data.get("extractable_text") is False:
        flags.append({
            "type": "unreadable_resume",
            "severity": "hard",
            "reason": "Resume PDF could not be parsed — flagged for manual review",
        })

    # ── SOFT knockouts ────────────────────────────────────────────────────
    if total_years > min_experience + 5:
        flags.append({
            "type": "overqualified",
            "severity": "soft",
            "reason": (
                f"Candidate has {int(total_years)} years, "
                f"role requires {int(min_experience)}"
            ),
        })

    required_skills = job_config.get("required_skills") or []
    if required_skills:
        candidate_skills_normalized = {
            normalize_skill(s["name"])
            for s in (candidate_data.get("skills_detailed") or [])
            if s.get("name")
        }
        normalized_required = [normalize_skill(s) for s in required_skills]
        matched = [s for s in normalized_required if s in candidate_skills_normalized]
        match_rate = len(matched) / len(normalized_required) if normalized_required else 1.0
        if match_rate < 0.4:
            flags.append({
                "type": "skills_gap",
                "severity": "soft",
                "reason": (
                    f"Candidate matches only {round(match_rate * 100)}% "
                    f"of required skills"
                ),
            })

    work_location = job_config.get("work_location_type")
    if work_location == "On-site" and len(jobs) >= 2:
        recent_remote = sum(
            1 for j in jobs[:3]
            if (j.get("work_type") or "").lower() == "remote"
        )
        if recent_remote >= 2:
            flags.append({
                "type": "location_mismatch",
                "severity": "soft",
                "reason": "Recent roles are remote but position requires on-site",
            })

    if jobs:
        current_job = next((j for j in jobs if j.get("is_current")), jobs[0])
        candidate_level = extract_seniority_level(current_job.get("title", ""))
        job_level = extract_seniority_level(job_title)
        if abs(candidate_level - job_level) >= 2:
            flags.append({
                "type": "level_mismatch",
                "severity": "soft",
                "reason": "Candidate seniority level does not align with role requirements",
            })

    if job_config.get("require_portfolio") and not candidate_data.get("portfolio_url"):
        flags.append({
            "type": "missing_portfolio",
            "severity": "soft",
            "reason": "Portfolio URL required but not submitted",
        })

    if job_config.get("require_linkedin") and not candidate_data.get("linkedin_url"):
        flags.append({
            "type": "missing_linkedin",
            "severity": "soft",
            "reason": "LinkedIn URL required but not submitted",
        })

    return flags
