"""
test_isolation.py — Multi-tenant data isolation tests
======================================================
Verifies that Company A cannot read, modify or delete Company B's data.
Uses the `tenant_a` and `tenant_b` session-scoped fixtures from conftest.py.
"""

import io
import zipfile
import pytest


def _headers(tenant):
    return {"Authorization": f"Bearer {tenant['token']}"}


def _make_minimal_zip() -> bytes:
    """A ZIP with a single placeholder file (not a real PDF — just for endpoint testing)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("dummy.pdf", b"%PDF-1.4 placeholder")
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# BULK-SCREEN JOB ISOLATION  (in-memory job tracker)
# ══════════════════════════════════════════════════════════════════════════════

class TestJobTrackerIsolation:

    @pytest.fixture(scope="class")
    def job_id_a(self, client, tenant_a):
        """Submit a bulk-screen from tenant A and return the tracking job_id."""
        r = client.post(
            "/api/bulk-screen",
            headers=_headers(tenant_a),
            files={"resumes_zip": ("test.zip", _make_minimal_zip(), "application/zip")},
            data={
                "job_title":       "Test Engineer",
                "job_description": "Test job for isolation testing",
                "min_experience":  "1",
                "required_skills": "Python",
            },
        )
        assert r.status_code == 200, r.text
        return r.json()["job_id"]

    def test_tenant_a_can_see_own_job(self, client, tenant_a, job_id_a):
        r = client.get(
            f"/api/job/{job_id_a}",
            headers=_headers(tenant_a),
        )
        assert r.status_code == 200

    def test_tenant_b_cannot_see_tenant_a_job(self, client, tenant_b, job_id_a):
        """Tenant B must get 403 when accessing Tenant A's job tracker entry."""
        r = client.get(
            f"/api/job/{job_id_a}",
            headers=_headers(tenant_b),
        )
        assert r.status_code == 403

    def test_unauthenticated_cannot_see_any_job(self, client, job_id_a):
        r = client.get(f"/api/job/{job_id_a}")
        assert r.status_code in (401, 403)

    def test_tenant_a_bulk_jobs_list_excludes_tenant_b_jobs(self, client, tenant_a, tenant_b):
        """GET /api/jobs must only return jobs belonging to the authenticated tenant."""
        # Submit a job from B
        client.post(
            "/api/bulk-screen",
            headers=_headers(tenant_b),
            files={"resumes_zip": ("b.zip", _make_minimal_zip(), "application/zip")},
            data={
                "job_title": "B Job", "job_description": "b",
                "min_experience": "1", "required_skills": "Java",
            },
        )
        jobs_a = client.get("/api/jobs", headers=_headers(tenant_a)).json()["jobs"]
        jobs_b = client.get("/api/jobs", headers=_headers(tenant_b)).json()["jobs"]

        ids_a = {j["id"] for j in jobs_a}
        ids_b = {j["id"] for j in jobs_b}
        assert ids_a.isdisjoint(ids_b), "Job IDs must not overlap across tenants"


# ══════════════════════════════════════════════════════════════════════════════
# APPLICANT ISOLATION
# ══════════════════════════════════════════════════════════════════════════════

class TestApplicantIsolation:

    def test_applicants_list_only_returns_own_company(self, client, tenant_a, tenant_b):
        """If both tenants have applicants, each must see only their own."""
        r_a = client.get("/applicants/", headers=_headers(tenant_a))
        r_b = client.get("/applicants/", headers=_headers(tenant_b))
        assert r_a.status_code == 200
        assert r_b.status_code == 200

        ids_a = {a["id"] for a in r_a.json()}
        ids_b = {b["id"] for b in r_b.json()}
        assert ids_a.isdisjoint(ids_b), "Applicant IDs must not overlap across tenants"

    def test_tenant_b_cannot_delete_tenant_a_applicant(self, client, tenant_a, tenant_b):
        """Attempting to DELETE an applicant that belongs to another tenant must fail."""
        applicants_a = client.get(
            "/applicants/", headers=_headers(tenant_a)
        ).json()
        if not applicants_a:
            pytest.skip("Tenant A has no applicants yet — run pipeline test first")

        victim_id = applicants_a[0]["id"]
        r = client.delete(
            f"/applicants/{victim_id}",
            headers=_headers(tenant_b),
        )
        # Must be forbidden (403) or not found (404) — never 204 success
        assert r.status_code in (403, 404), (
            f"Tenant B should not be able to delete Tenant A's applicant "
            f"(got {r.status_code})"
        )

    def test_tenant_b_cannot_update_tenant_a_applicant_status(self, client, tenant_a, tenant_b):
        applicants_a = client.get(
            "/applicants/", headers=_headers(tenant_a)
        ).json()
        if not applicants_a:
            pytest.skip("Tenant A has no applicants yet — run pipeline test first")

        victim_id = applicants_a[0]["id"]
        r = client.put(
            f"/applicants/{victim_id}/status",
            headers=_headers(tenant_b),
            json={"status": "shortlisted"},
        )
        assert r.status_code in (403, 404)
