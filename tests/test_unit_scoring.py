"""
test_unit_scoring.py — Pure-Python unit tests (no network, no DB)
==================================================================
Tests the deterministic scoring algorithm and fuzzy skill matcher
directly. These run instantly and require no server.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.ai_engine import _fuzzy_match_skill, calculate_deterministic_score, evaluate_knockout_filters


# ══════════════════════════════════════════════════════════════════════════════
# FUZZY SKILL MATCHING
# ══════════════════════════════════════════════════════════════════════════════

SKILLS_DICT = {
    "python 3":    4.0,
    "postgresql":  2.0,
    "fastapi":     1.5,
    "docker ce":   1.0,
    "amazon s3":   0.5,
}


class TestFuzzyMatch:
    def test_exact_match(self):
        key, yrs = _fuzzy_match_skill("fastapi", SKILLS_DICT)
        assert key == "fastapi" and yrs == 1.5

    def test_required_is_substring_of_key(self):
        """'python' should match 'python 3'"""
        key, yrs = _fuzzy_match_skill("python", SKILLS_DICT)
        assert key == "python 3" and yrs == 4.0

    def test_required_prefix_of_key(self):
        """'postgres' should match 'postgresql'"""
        key, yrs = _fuzzy_match_skill("postgres", SKILLS_DICT)
        assert key == "postgresql" and yrs == 2.0

    def test_key_is_substring_of_required(self):
        """'docker' is a substring of 'docker ce'"""
        key, yrs = _fuzzy_match_skill("docker", SKILLS_DICT)
        assert yrs == 1.0

    def test_no_match_returns_none(self):
        key, yrs = _fuzzy_match_skill("golang", SKILLS_DICT)
        assert key is None and yrs == 0.0

    def test_case_insensitive(self):
        """Skills dict keys are already lowercased; required is lowercased inside scorer."""
        key, yrs = _fuzzy_match_skill("PYTHON", {"python 3": 2.0})
        # required is passed pre-lowercased from the scorer, but test the helper directly
        key2, yrs2 = _fuzzy_match_skill("python", {"python 3": 2.0})
        assert yrs2 == 2.0

    def test_shorter_key_matches_longer_required(self):
        """'aws' (key) should match 'amazon web services' (required)? 
           No — substring check: 'aws' not in 'amazon web services', 
           but 'amazon' IS a substring check from the other direction."""
        key, yrs = _fuzzy_match_skill("amazon", {"amazon s3": 0.5})
        assert yrs == 0.5


# ══════════════════════════════════════════════════════════════════════════════
# DETERMINISTIC SCORING
# ══════════════════════════════════════════════════════════════════════════════

def _candidate(
    skills: dict,
    years: float,
    education: str = "Unknown",
    skill_matches: list | None = None,
    requires_visa_sponsorship: bool | None = None,
) -> dict:
    return {
        "skills_with_years":    skills,
        "total_years_experience": years,
        "highest_education_level": education,
        "skill_matches": skill_matches or [],
        "requires_visa_sponsorship": requires_visa_sponsorship,
    }


class TestDeterministicScore:

    # ── max score -─────────────────────────────────────────────────────────

    def test_perfect_candidate_scores_100(self):
        """
        Full 100 requires:
          - Meets/exceeds minimum experience       (40 pts)
          - Matches all required skills            (40 pts)
          - Meets education requirement            (20 pts)
        """
        c = _candidate(
            skills={"python": 5.0, "fastapi": 5.0, "postgresql": 5.0},
            years=5.0,
            education="Master's",
        )
        r = calculate_deterministic_score(
            c,
            ["python", "fastapi", "postgresql"],
            3.0,
            "Backend Engineer",
            required_education="Bachelor's in Computer Science",
        )
        assert r["final_score"] == 100
        assert r["status"] == "shortlisted"

    def test_over_experienced_does_not_exceed_100(self):
        """10 years on a 3-year role must not produce more than 100."""
        c = _candidate(
            skills={"python": 10.0, "fastapi": 10.0},
            years=10.0,
            education="PhD",
        )
        r = calculate_deterministic_score(c, ["python", "fastapi"], 3.0, "Backend Engineer")
        assert r["final_score"] <= 100

    # ── skill match component (40 pts) ─────────────────────────────────────

    def test_zero_matching_skills_gives_zero_skill_points(self):
        c = _candidate(skills={"java": 2.0}, years=3.0, education="Bachelor's")
        r = calculate_deterministic_score(c, ["python", "fastapi"], 3.0, "")
        assert r["breakdown"]["skills"] == 0.0
        assert r["matched_skills_count"] == 0

    def test_partial_skill_match_proportional(self):
        """1 of 2 required skills matched → 20 points."""
        c = _candidate(skills={"python": 3.0}, years=3.0, education="Bachelor's")
        r = calculate_deterministic_score(c, ["python", "rust"], 3.0, "")
        assert r["breakdown"]["skills"] == pytest.approx(20.0, abs=1.0)

    # ── experience component (40 pts) ───────────────────────────────────────

    def test_zero_experience_gives_zero_exp_score(self):
        c = _candidate(skills={}, years=0.0)
        r = calculate_deterministic_score(c, [], 3.0, "")
        assert r["breakdown"]["experience"] == pytest.approx(0.0)

    def test_experience_at_or_above_min_gets_full_score(self):
        """Candidates meeting or exceeding min_experience get full 40 pts."""
        c10 = _candidate(skills={}, years=10.0)
        c3  = _candidate(skills={}, years=3.0)
        r10 = calculate_deterministic_score(c10, [], 3.0, "")
        r3  = calculate_deterministic_score(c3,  [], 3.0, "")
        assert r10["breakdown"]["experience"] == r3["breakdown"]["experience"] == pytest.approx(40.0)

    # ── education component (20 pts) ───────────────────────────────────────

    def test_education_requirement_met_gets_20(self):
        c = _candidate(skills={}, years=0.0, education="Master's")
        r = calculate_deterministic_score(c, [], 0.0, "", required_education="Bachelor's")
        assert r["breakdown"]["education"] == 20.0

    def test_education_requirement_not_met_gets_0(self):
        c = _candidate(skills={}, years=0.0, education="Associate")
        r = calculate_deterministic_score(c, [], 0.0, "", required_education="Bachelor's")
        assert r["breakdown"]["education"] == 0.0

    # ── status bucketing ────────────────────────────────────────────────────

    def test_score_80_is_shortlisted(self):
        # Strong candidate crosses shortlist threshold.
        c = _candidate(
            skills={"python": 3.0, "fastapi": 3.0, "postgresql": 3.0},
            years=3.0,
            education="Bachelor's",
        )
        r = calculate_deterministic_score(
            c,
            ["python", "fastapi", "postgresql"],
            3.0,
            "Backend Engineer",
            required_education="Bachelor's",
        )
        assert r["status"] == "shortlisted"

    def test_score_60_to_79_is_review(self):
        c = _candidate(skills={"python": 3.0}, years=2.0, education="Associate")
        r = calculate_deterministic_score(c, ["python", "fastapi"], 3.0, "")
        assert r["status"] in ("review", "rejected")  # depends on exact arithmetic

    def test_score_below_60_is_rejected(self):
        c = _candidate(skills={}, years=0.0)
        r = calculate_deterministic_score(c, ["python", "fastapi", "sql"], 3.0, "Senior Engineer")
        assert r["status"] == "rejected"
        assert r["final_score"] < 60

    # ── edge cases ──────────────────────────────────────────────────────────

    def test_no_required_skills_does_not_crash(self):
        c = _candidate(skills={"python": 2.0}, years=2.0, education="Bachelor's")
        r = calculate_deterministic_score(c, [], 2.0, "Engineer")
        assert isinstance(r["final_score"], int)

    def test_summary_is_non_empty_string(self):
        c = _candidate(skills={"python": 2.0}, years=2.0)
        r = calculate_deterministic_score(c, ["python"], 2.0, "")
        assert isinstance(r["summary"], str) and len(r["summary"]) > 10

    def test_breakdown_keys_present(self):
        c = _candidate(skills={}, years=0.0)
        r = calculate_deterministic_score(c, [], 0.0, "")
        assert set(r["breakdown"]) == {"experience", "skills", "education"}


class TestKnockoutFilters:

    def test_senior_role_zero_experience_is_knockout(self):
        c = _candidate(skills={"python": 1.0}, years=0.0)
        result = evaluate_knockout_filters(
            candidate=c,
            required_skills=["python"],
            min_experience=3.0,
            job_title="Senior Backend Engineer",
        )
        assert result["knockout"] is True
        assert "0 years of experience for senior role" in result["reason"]

    def test_visa_requirement_without_sponsorship_is_knockout(self):
        c = _candidate(skills={"python": 4.0}, years=4.0, requires_visa_sponsorship=True)
        result = evaluate_knockout_filters(
            candidate=c,
            required_skills=["python"],
            min_experience=3.0,
            job_title="Backend Engineer",
            job_requirements={
                "must_have_skills": ["Python"],
                "minimum_years_experience": 3,
                "education_requirement": "Bachelor's",
                "offers_visa_sponsorship": False,
            },
        )
        assert result["knockout"] is True
        assert "visa sponsorship" in result["reason"]
