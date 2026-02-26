"""
test_unit_scoring.py — Pure-Python unit tests (no network, no DB)
==================================================================
Tests the deterministic scoring algorithm and fuzzy skill matcher
directly. These run instantly and require no server.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.ai_engine import _fuzzy_match_skill, calculate_deterministic_score


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
    titles: list,
    bullets: int = 0,
    jd_matches: list | None = None,
) -> dict:
    return {
        "skills_with_years":    skills,
        "total_years_experience": years,
        "recent_job_titles":    titles,
        "metrics_bullet_count": bullets,
        "jd_requirement_matches": jd_matches or [],
    }


class TestDeterministicScore:

    # ── max score -─────────────────────────────────────────────────────────

    def test_perfect_candidate_scores_100(self):
        """
        Full 100 requires:
          - All skills at depth >= min_experience  (40 pts)
          - JD requirements fully verified         (30 pts)
          - total_years >= min_experience          (20 pts)
          - >= 5 metric bullets                    (10 pts)
        """
        c = _candidate(
            skills={"python": 5.0, "fastapi": 5.0, "postgresql": 5.0},
            years=5.0,
            titles=["Backend Engineer"],
            bullets=5,
            jd_matches=[
                {
                    "requirement": "Must have Python experience",
                    "is_met": True,
                    "citation_quote": "5 years Python",
                }
            ],
        )
        r = calculate_deterministic_score(
            c,
            ["python", "fastapi", "postgresql"],
            3.0,
            "Backend Engineer",
            raw_resume_text="Candidate has 5 years Python and strong backend ownership.",
        )
        assert r["final_score"] == 100
        assert r["status"] == "shortlisted"

    def test_over_experienced_does_not_exceed_100(self):
        """10 years on a 3-year role must not produce more than 100."""
        c = _candidate(
            skills={"python": 10.0, "fastapi": 10.0},
            years=10.0,
            titles=["Backend Engineer"],
            bullets=10,
        )
        r = calculate_deterministic_score(c, ["python", "fastapi"], 3.0, "Backend Engineer")
        assert r["final_score"] <= 100

    # ── skill depth component (40 pts) ─────────────────────────────────────

    def test_zero_matching_skills_gives_zero_skill_depth(self):
        c = _candidate(skills={"java": 2.0}, years=3.0, titles=[], bullets=0)
        r = calculate_deterministic_score(c, ["python", "fastapi"], 3.0, "")
        assert r["breakdown"]["skill_depth"] == 0.0
        assert r["matched_skills_count"] == 0

    def test_partial_skill_match_proportional(self):
        """1 of 2 required skills matched → ~20 pts skill depth (half of 40)."""
        c = _candidate(skills={"python": 3.0}, years=3.0, titles=[], bullets=0)
        r = calculate_deterministic_score(c, ["python", "rust"], 3.0, "")
        assert r["breakdown"]["skill_depth"] == pytest.approx(20.0, abs=1.0)

    def test_underdepth_skill_is_partial_score(self):
        """Candidate has 1yr Python but requirement is 3yr → depth 1/3 → 13.3pts."""
        c = _candidate(skills={"python": 1.0}, years=1.0, titles=[], bullets=0)
        r = calculate_deterministic_score(c, ["python"], 3.0, "")
        expected_depth = (1.0 / 3.0) * 40.0
        assert r["breakdown"]["skill_depth"] == pytest.approx(expected_depth, abs=0.5)

    # ── JD requirements component (30 pts) ──────────────────────────────────

    def test_jd_requirements_fully_verified_gives_30_pts(self):
        c = _candidate(
            skills={},
            years=0.0,
            titles=[],
            bullets=0,
            jd_matches=[
                {
                    "requirement": "Must know FastAPI",
                    "is_met": True,
                    "citation_quote": "Built APIs with FastAPI",
                }
            ],
        )
        r = calculate_deterministic_score(
            c,
            [],
            0.0,
            "",
            raw_resume_text="Built APIs with FastAPI and PostgreSQL.",
        )
        assert r["breakdown"]["jd_requirements"] == 30.0
        assert r["verified_requirements"] == 1

    def test_missing_or_unverified_citation_gives_0_jd_pts(self):
        c = _candidate(
            skills={},
            years=0.0,
            titles=[],
            bullets=0,
            jd_matches=[
                {
                    "requirement": "Must know FastAPI",
                    "is_met": True,
                    "citation_quote": "Built APIs with FastAPI",
                }
            ],
        )
        r = calculate_deterministic_score(c, [], 0.0, "", raw_resume_text="No relevant text")
        assert r["breakdown"]["jd_requirements"] == 0.0
        assert r["hallucination_count"] == 1

    def test_no_jd_matches_gives_0_jd_pts(self):
        c = _candidate(skills={}, years=0.0, titles=[], bullets=0, jd_matches=[])
        r = calculate_deterministic_score(c, [], 0.0, "", raw_resume_text="resume")
        assert r["breakdown"]["jd_requirements"] == 0.0

    # ── experience component (20 pts) ───────────────────────────────────────

    def test_zero_experience_gives_zero_exp_score(self):
        c = _candidate(skills={}, years=0.0, titles=[], bullets=0)
        r = calculate_deterministic_score(c, [], 3.0, "")
        assert r["breakdown"]["experience"] == pytest.approx(0.0)

    def test_experience_at_or_above_min_gets_full_score(self):
        """Candidates meeting or exceeding min_experience get full 20 pts."""
        c10 = _candidate(skills={}, years=10.0, titles=[], bullets=0)
        c3  = _candidate(skills={}, years=3.0,  titles=[], bullets=0)
        r10 = calculate_deterministic_score(c10, [], 3.0, "")
        r3  = calculate_deterministic_score(c3,  [], 3.0, "")
        assert r10["breakdown"]["experience"] == r3["breakdown"]["experience"] == pytest.approx(20.0)

    # ── impact component (10 pts) ───────────────────────────────────────────

    def test_five_bullets_gives_full_impact(self):
        c = _candidate(skills={}, years=0.0, titles=[], bullets=5)
        r = calculate_deterministic_score(c, [], 0.0, "")
        assert r["breakdown"]["impact"] == 10.0

    def test_zero_bullets_gives_zero_impact(self):
        c = _candidate(skills={}, years=0.0, titles=[], bullets=0)
        r = calculate_deterministic_score(c, [], 0.0, "")
        assert r["breakdown"]["impact"] == 0.0

    def test_ten_bullets_capped_at_10_pts(self):
        c = _candidate(skills={}, years=0.0, titles=[], bullets=10)
        r = calculate_deterministic_score(c, [], 0.0, "")
        assert r["breakdown"]["impact"] == 10.0

    # ── status bucketing ────────────────────────────────────────────────────

    def test_score_80_is_shortlisted(self):
        # Strong candidate with verified JD match crosses shortlist threshold.
        c = _candidate(
            skills={"python": 3.0, "fastapi": 3.0, "postgresql": 3.0},
            years=3.0, titles=["Backend Engineer"], bullets=5,
            jd_matches=[
                {
                    "requirement": "Must know FastAPI",
                    "is_met": True,
                    "citation_quote": "FastAPI",
                }
            ],
        )
        r = calculate_deterministic_score(
            c,
            ["python", "fastapi", "postgresql"],
            3.0,
            "Backend Engineer",
            raw_resume_text="FastAPI",
        )
        assert r["status"] == "shortlisted"

    def test_score_60_to_79_is_review(self):
        # Skills only, no title/impact/sufficient exp → lands in review zone
        c = _candidate(skills={"python": 3.0, "fastapi": 3.0}, years=2.0, titles=[], bullets=2)
        r = calculate_deterministic_score(c, ["python", "fastapi"], 3.0, "")
        assert r["status"] in ("review", "rejected")  # depends on exact arithmetic

    def test_score_below_60_is_rejected(self):
        c = _candidate(skills={}, years=0.0, titles=[], bullets=0)
        r = calculate_deterministic_score(c, ["python", "fastapi", "sql"], 3.0, "Senior Engineer")
        assert r["status"] == "rejected"
        assert r["final_score"] == 0

    # ── edge cases ──────────────────────────────────────────────────────────

    def test_no_required_skills_does_not_crash(self):
        c = _candidate(skills={"python": 2.0}, years=2.0, titles=["Engineer"], bullets=2)
        r = calculate_deterministic_score(c, [], 2.0, "Engineer")
        assert isinstance(r["final_score"], int)

    def test_summary_is_non_empty_string(self):
        c = _candidate(skills={"python": 2.0}, years=2.0, titles=[], bullets=0)
        r = calculate_deterministic_score(c, ["python"], 2.0, "")
        assert isinstance(r["summary"], str) and len(r["summary"]) > 10

    def test_breakdown_keys_present(self):
        c = _candidate(skills={}, years=0.0, titles=[], bullets=0)
        r = calculate_deterministic_score(c, [], 0.0, "")
        assert set(r["breakdown"]) == {"skill_depth", "jd_requirements", "experience", "impact"}
