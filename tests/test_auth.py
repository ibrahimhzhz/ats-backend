"""
test_auth.py — Authentication endpoint tests
=============================================
Covers: register, login, /me, duplicate guards, token validation.
Requires the server to be running on http://localhost:8001.
"""

import uuid
import pytest


def _unique_creds(suffix=""):
    uid   = uuid.uuid4().hex[:8]
    return {
        "email":        f"auth_test_{suffix}_{uid}@testmail.example.com",
        "password":     "TestPass123!",
        "company_name": f"AuthTestCo_{suffix}_{uid}",
    }


# ══════════════════════════════════════════════════════════════════════════════
# REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════

class TestRegister:

    def test_register_new_user_returns_201(self, client):
        r = client.post("/auth/register", json=_unique_creds("new"))
        assert r.status_code == 201
        body = r.json()
        assert "email" in body
        assert "company_id" in body

    def test_register_duplicate_email_returns_409(self, client):
        creds = _unique_creds("dupemail")
        client.post("/auth/register", json=creds)  # first
        r = client.post("/auth/register", json={    # second — same email
            "email":        creds["email"],
            "password":     "Different1!",
            "company_name": f"OtherCo_{uuid.uuid4().hex[:6]}",
        })
        assert r.status_code == 409
        assert "email" in r.json()["detail"].lower()

    def test_register_duplicate_company_name_returns_409(self, client):
        creds = _unique_creds("dupcname")
        client.post("/auth/register", json=creds)  # first register
        r = client.post("/auth/register", json={    # same company, diff email
            "email":        f"other_{uuid.uuid4().hex[:8]}@testmail.example.com",
            "password":     "TestPass123!",
            "company_name": creds["company_name"],
        })
        assert r.status_code == 409
        assert "company" in r.json()["detail"].lower()

    def test_register_missing_fields_returns_422(self, client):
        r = client.post("/auth/register", json={"email": "nopassword@testmail.example.com"})
        assert r.status_code == 422

    def test_register_returns_no_password_hash(self, client):
        """Hashed password must never be exposed in the response."""
        creds = _unique_creds("nopwhash")
        r = client.post("/auth/register", json=creds)
        assert r.status_code == 201
        body = r.json()
        assert "hashed_password" not in body
        assert "password" not in body


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def registered_user(client):
    creds = _unique_creds("login")
    client.post("/auth/register", json=creds)
    return creds


class TestLogin:

    def test_login_valid_credentials_returns_200(self, client, registered_user):
        r = client.post(
            "/auth/login",
            data={"username": registered_user["email"], "password": registered_user["password"]},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_login_wrong_password_returns_401(self, client, registered_user):
        r = client.post(
            "/auth/login",
            data={"username": registered_user["email"], "password": "WRONGPASS!"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 401

    def test_login_unknown_email_returns_401(self, client):
        r = client.post(
            "/auth/login",
            data={"username": "nobody@nowhere.example.com", "password": "anything"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 401

    def test_login_returns_jwt_with_3_segments(self, client, registered_user):
        r = client.post(
            "/auth/login",
            data={"username": registered_user["email"], "password": registered_user["password"]},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token = r.json()["access_token"]
        assert len(token.split(".")) == 3, "JWT must have header.payload.signature"


# ══════════════════════════════════════════════════════════════════════════════
# /auth/me
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def auth_token(client, registered_user):
    r = client.post(
        "/auth/login",
        data={"username": registered_user["email"], "password": registered_user["password"]},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return r.json()["access_token"]


class TestMe:

    def test_me_with_valid_token_returns_200(self, client, auth_token, registered_user):
        r = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == registered_user["email"]
        assert "company_id" in body

    def test_me_without_token_returns_401(self, client):
        r = client.get("/auth/me")
        assert r.status_code == 401

    def test_me_with_garbage_token_returns_401(self, client):
        r = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer this.is.garbage"},
        )
        assert r.status_code == 401

    def test_me_response_omits_sensitive_fields(self, client, auth_token):
        r = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        body = r.json()
        assert "hashed_password" not in body
        assert "password" not in body


# ══════════════════════════════════════════════════════════════════════════════
# TOKEN REQUIRED ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

class TestTokenRequired:

    def test_bulk_screen_requires_auth(self, client):
        r = client.post("/api/bulk-screen", data={})
        assert r.status_code in (401, 403, 422)

    def test_get_jobs_requires_auth(self, client):
        r = client.get("/api/jobs")
        assert r.status_code in (401, 403)

    def test_get_applicants_requires_auth(self, client):
        r = client.get("/applicants/")
        assert r.status_code in (401, 403)
