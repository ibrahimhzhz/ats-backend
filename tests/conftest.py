"""
conftest.py — Shared pytest fixtures
=====================================
Registers two isolated tenants at the start of the session and
tears them down (users + companies) once all tests have finished.

Both tenants are available via the `tenant_a` and `tenant_b` fixtures.
Each returns a dict:
    {
        "token":      str,   # Bearer JWT
        "email":      str,
        "company_id": int,
    }
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from database import Base, get_db
import models

# ─── isolated in-memory test database ─────────────────────────────────────────
TEST_DATABASE_URL = "sqlite:///:memory:"

_test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
_TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


def _override_get_db():
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── helpers ──────────────────────────────────────────────────────────────────

def _register_and_login(client: TestClient, suffix: str) -> dict:
    """Create a unique company + user, then log in and return the auth dict."""
    uid   = uuid.uuid4().hex[:8]
    email = f"test_{suffix}_{uid}@testmail.example.com"
    pw    = "TestPass123!"
    cname = f"TestCo_{suffix}_{uid}"

    r = client.post("/auth/register", json={
        "email":        email,
        "password":     pw,
        "company_name": cname,
    })
    assert r.status_code == 201, f"Register failed: {r.text}"

    r = client.post(
        "/auth/login",
        data={"username": email, "password": pw},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, f"Login failed: {r.text}"
    token = r.json()["access_token"]

    r = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    company_id = r.json()["company_id"]

    return {"token": token, "email": email, "company_id": company_id}


def _auth_headers(tenant: dict) -> dict:
    return {"Authorization": f"Bearer {tenant['token']}"}


# ─── session-scoped fixtures ───────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    # Create all tables in the isolated in-memory database
    Base.metadata.create_all(bind=_test_engine)
    # Override the DB dependency so the app uses the test DB, not ats.db
    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as test_client:
        yield test_client

    # Teardown: drop all tables and remove the override
    Base.metadata.drop_all(bind=_test_engine)
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def tenant_a(client):
    return _register_and_login(client, "A")


@pytest.fixture(scope="session")
def tenant_b(client):
    return _register_and_login(client, "B")


# Re-export the helper so individual test modules can use it
@pytest.fixture(scope="session")
def auth_headers():
    """Returns a callable: auth_headers(tenant) → dict."""
    return _auth_headers
