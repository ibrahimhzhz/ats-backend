"""
test_pipeline.py — End-to-end bulk screening pipeline tests
=============================================================
Creates real PDFs with known content, uploads as a ZIP, polls until
completion, then asserts on scores, statuses and deduplication.

Requires:
  - Server running on http://localhost:8001
  - fpdf2 package (already installed via generate_resumes.py)
  - PyMuPDF (fitz) for the server-side PDF parser
"""

import io
import time
import zipfile
import pytest
import requests
from fpdf import FPDF

BASE_URL = "http://localhost:8001"
POLL_TIMEOUT = 120   # seconds
POLL_INTERVAL = 2    # seconds


# ══════════════════════════════════════════════════════════════════════════════
# PDF FACTORY
# ══════════════════════════════════════════════════════════════════════════════

def _make_pdf(content: str) -> bytes:
    """Generate a single-page PDF whose text layer contains `content`."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    # FPDF.multi_cell handles long strings; replace unicode bullets that latin-1 can't encode
    safe = content.replace("\u2022", "-").replace("\u2013", "-").replace("\u2019", "'")
    pdf.multi_cell(0, 6, safe)
    return bytes(pdf.output())


# Known test resumes -─────────────────────────────────────────────────────────

_PERFECT_CV = """
Name: Alice Perfectcandidate
Email: alice.perfect@pipeline-test.example.com
Phone: +1-555-0001

PROFESSIONAL EXPERIENCE

Senior Backend Engineer — TechCorp (2019 – 2024)  [5 years]
- Reduced API latency by 40% through query optimisation
- Increased system throughput by 3x using async workers
- Achieved 99.9% uptime SLA across 12 microservices
- Migrated legacy monolith to FastAPI, cutting deploy time by 60%
- Saved $120,000/yr by consolidating cloud infrastructure

Backend Engineer — StartupXYZ (2017 – 2019)  [2 years]

TECHNICAL SKILLS
Python: 7 years
FastAPI: 5 years
PostgreSQL: 5 years
Docker: 4 years
AWS: 3 years
"""

_EXPERIENCE_KNOCKOUT_CV = """
Name: Bob Rookie
Email: bob.rookie@pipeline-test.example.com
Phone: +1-555-0002

EDUCATION
B.Sc. Computer Science — 2024

TECHNICAL SKILLS
Python: 6 months
FastAPI: 3 months
"""

_SKILL_KNOCKOUT_CV = """
Name: Carol Designer
Email: carol.designer@pipeline-test.example.com
Phone: +1-555-0003

PROFESSIONAL EXPERIENCE
Graphic Designer — DesignStudio (2018 – 2024)  [6 years]
- Designed 200+ marketing assets
- Led rebrand increasing engagement by 35%

TECHNICAL SKILLS
Photoshop: 6 years
Illustrator: 6 years
Figma: 4 years
"""

_GOOD_CV = """
Name: Dave Engineer
Email: dave.engineer@pipeline-test.example.com
Phone: +1-555-0004

PROFESSIONAL EXPERIENCE
Backend Developer — MidCo (2020 – 2024)  [4 years]
- Improved database query speed by 25%
- Built REST APIs serving 50k requests/day

TECHNICAL SKILLS
Python: 4 years
FastAPI: 3 years
PostgreSQL: 2 years
Docker: 1 year
"""

# Duplicate of Alice — same email → should be deduplicated if same job run twice
_DUPLICATE_CV = _PERFECT_CV.replace("Alice Perfectcandidate", "Alice Duplicate")


# ZIP builder ─────────────────────────────────────────────────────────────────

def _build_zip(cvs: dict) -> bytes:
    """cvs = {filename: pdf_text_content}. Returns ZIP bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in cvs.items():
            zf.writestr(name, _make_pdf(content))
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _headers(tenant):
    return {"Authorization": f"Bearer {tenant['token']}"}


def _submit_screening(tenant, zip_bytes, job_title="Backend Engineer",
                       min_exp=3, skills="Python,FastAPI,PostgreSQL"):
    r = requests.post(
        f"{BASE_URL}/api/bulk-screen",
        headers=_headers(tenant),
        files={"resumes_zip": ("resumes.zip", zip_bytes, "application/zip")},
        data={
            "job_title":       job_title,
            "job_description": "Looking for an experienced backend engineer.",
            "min_experience":  str(min_exp),
            "required_skills": skills,
        },
    )
    assert r.status_code == 200, f"Submission failed: {r.text}"
    return r.json()["job_id"]


def _poll_until_done(tenant, job_id) -> dict:
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        r = requests.get(
            f"{BASE_URL}/api/job/{job_id}",
            headers=_headers(tenant),
        )
        assert r.status_code == 200
        job = r.json()
        if job["status"] == "completed":
            return job
        if job["status"] == "failed":
            pytest.fail(f"Pipeline job failed: {job.get('error')}")
        time.sleep(POLL_INTERVAL)
    pytest.fail(f"Pipeline job did not complete within {POLL_TIMEOUT}s")


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestPipelineEndToEnd:
    """
    Uploads 4 known CVs and verifies the pipeline handles each correctly.
    This hits Vertex AI (costs real API calls) — so it's the expensive test.
    """

    @pytest.fixture(scope="class")
    def pipeline_result(self, tenant_a):
        zip_bytes = _build_zip({
            "alice_perfect.pdf":             _PERFECT_CV,
            "bob_experience_knockout.pdf":   _EXPERIENCE_KNOCKOUT_CV,
            "carol_skill_knockout.pdf":      _SKILL_KNOCKOUT_CV,
            "dave_good.pdf":                 _GOOD_CV,
        })
        job_id = _submit_screening(tenant_a, zip_bytes)
        return _poll_until_done(tenant_a, job_id)

    # ── stats ────────────────────────────────────────────────────────────────

    def test_all_four_resumes_processed(self, pipeline_result):
        assert pipeline_result["results"]["total_processed"] == 4

    def test_two_candidates_knocked_out(self, pipeline_result):
        """Bob (experience) and Carol (skills) should both be knocked out."""
        assert pipeline_result["results"]["knocked_out"] >= 2

    def test_two_candidates_scored(self, pipeline_result):
        assert pipeline_result["results"]["scored"] >= 1

    # ── individual candidates ─────────────────────────────────────────────────

    def _find(self, results, email_fragment):
        for c in results["all_candidates"]:
            if email_fragment in (c.get("email") or "").lower():
                return c
        return None

    def test_perfect_cv_scores_high(self, pipeline_result):
        alice = self._find(pipeline_result["results"], "alice.perfect")
        assert alice is not None, "Alice not found in results"
        assert alice["match_score"] >= 70, (
            f"Alice should score high, got {alice['match_score']}"
        )

    def test_perfect_cv_is_shortlisted_or_review(self, pipeline_result):
        alice = self._find(pipeline_result["results"], "alice.perfect")
        assert alice is not None
        assert alice["status"] in ("shortlisted", "review"), (
            f"Alice should be shortlisted/review, got {alice['status']}"
        )

    def test_experience_knockout_is_rejected(self, pipeline_result):
        bob = self._find(pipeline_result["results"], "bob.rookie")
        assert bob is not None
        assert bob["status"] == "rejected"
        assert bob["match_score"] == 0

    def test_skill_knockout_is_rejected(self, pipeline_result):
        carol = self._find(pipeline_result["results"], "carol.designer")
        assert carol is not None
        assert carol["status"] == "rejected"
        assert carol["match_score"] == 0

    def test_good_cv_has_positive_score(self, pipeline_result):
        dave = self._find(pipeline_result["results"], "dave.engineer")
        assert dave is not None
        assert dave["match_score"] > 0

    def test_candidates_sorted_by_score_descending(self, pipeline_result):
        scores = [c["match_score"] for c in pipeline_result["results"]["all_candidates"]]
        assert scores == sorted(scores, reverse=True), "Candidates must be sorted by score"

    # ── breakdown present ─────────────────────────────────────────────────────

    def test_scored_candidates_have_breakdown(self, pipeline_result):
        for c in pipeline_result["results"]["all_candidates"]:
            if c["status"] != "rejected" or c["match_score"] > 0:
                assert c.get("breakdown") is not None, (
                    f"Candidate {c['name']} should have a breakdown dict"
                )

    def test_breakdown_components_sum_to_final_score(self, pipeline_result):
        for c in pipeline_result["results"]["all_candidates"]:
            bd = c.get("breakdown")
            if not bd:
                continue
            total = sum(bd.values())
            assert abs(total - c["match_score"]) <= 1, (
                f"Breakdown {bd} sums to {total}, but match_score={c['match_score']}"
            )

    # ── skills stored as dict ─────────────────────────────────────────────────

    def test_skills_stored_as_dict_not_list(self, pipeline_result):
        for c in pipeline_result["results"]["all_candidates"]:
            skills = c.get("skills", {})
            assert isinstance(skills, dict), (
                f"skills for {c['name']} should be a dict, got {type(skills)}"
            )

    # ── criteria echoed back ──────────────────────────────────────────────────

    def test_criteria_echoed_in_results(self, pipeline_result):
        criteria = pipeline_result["results"].get("criteria", {})
        assert criteria.get("job_title") == "Backend Engineer"
        assert criteria.get("min_experience") == 3.0
        assert "Python" in criteria.get("required_skills", [])


# ══════════════════════════════════════════════════════════════════════════════
# DEDUPLICATION TEST  (second run on same job with same email)
# ══════════════════════════════════════════════════════════════════════════════

class TestDeduplication:
    """
    Submit Alice twice in the same job → second submission should be skipped.
    """

    def test_duplicate_email_is_skipped(self, tenant_a):
        # Two PDFs, both with the same email (alice.perfect)
        zip_bytes = _build_zip({
            "alice_v1.pdf": _PERFECT_CV,
            "alice_v2.pdf": _DUPLICATE_CV,   # same email, different name
        })
        job_id = _submit_screening(tenant_a, zip_bytes,
                                    job_title="Dedup Test", min_exp=1, skills="Python")
        result = _poll_until_done(tenant_a, job_id)
        assert result["results"]["duplicates_skipped"] >= 1, (
            "One of the two Alice submissions should have been deduplicated"
        )
        assert result["results"]["total_processed"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# SUBMISSION VALIDATION TESTS  (no AI calls needed)
# ══════════════════════════════════════════════════════════════════════════════

class TestSubmissionValidation:

    def test_empty_zip_returns_400(self, tenant_a):
        empty_zip = _build_zip({})  # ZIP with no files
        r = requests.post(
            f"{BASE_URL}/api/bulk-screen",
            headers=_headers(tenant_a),
            files={"resumes_zip": ("empty.zip", empty_zip, "application/zip")},
            data={
                "job_title": "Test", "job_description": "test",
                "min_experience": "1", "required_skills": "Python",
            },
        )
        assert r.status_code == 400
        assert "no pdf" in r.json()["detail"].lower()

    def test_non_zip_file_returns_400(self, tenant_a):
        r = requests.post(
            f"{BASE_URL}/api/bulk-screen",
            headers=_headers(tenant_a),
            files={"resumes_zip": ("notazip.zip", b"this is not a zip", "application/zip")},
            data={
                "job_title": "Test", "job_description": "test",
                "min_experience": "1", "required_skills": "Python",
            },
        )
        assert r.status_code == 400
        assert "invalid zip" in r.json()["detail"].lower()

    def test_missing_required_fields_returns_422(self, tenant_a):
        r = requests.post(
            f"{BASE_URL}/api/bulk-screen",
            headers=_headers(tenant_a),
            files={"resumes_zip": ("r.zip", _build_zip({"a.pdf": "hello"}), "application/zip")},
            data={},  # missing job_description, min_experience, required_skills
        )
        assert r.status_code == 422
