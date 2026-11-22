"""
Automated Agentic Security Verification Tests.
Verifies all patches:
1. Registration privilege escalation prevention
2. Authenticated doctor provisioning
3. IDOR prevention on verification requests
4. Path traversal / absolute server path masking
5. SSRF prevention on LLM endpoint
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from app import app
from src.auth import register_user, create_verification_request, get_db_connection


@pytest.fixture
def client():
    return TestClient(app)


def test_public_registration_rejects_doctor(client):
    """Verify that anonymous registration cannot create a doctor account."""
    res = client.post("/api/auth/register", json={
        "username": f"attacker_{uuid.uuid4().hex[:8]}",
        "password": "strongPassword123",
        "full_name": "Rogue Doctor",
        "role": "doctor"
    })
    assert res.status_code == 403
    assert "Public self-registration is limited" in res.json()["detail"]


def test_public_registration_allows_analyst(client):
    """Verify that legitimate analysts can still self-register."""
    res = client.post("/api/auth/register", json={
        "username": f"analyst_{uuid.uuid4().hex[:8]}",
        "password": "strongPassword123",
        "full_name": "Legit Analyst",
        "role": "analyst"
    })
    assert res.status_code == 200
    assert "token" in res.json()
    assert res.json()["user"]["role"] == "analyst"


def test_authenticated_doctor_can_provision_doctor(client):
    """Verify that an existing authenticated doctor can provision a new doctor."""
    login = client.post("/api/auth/login", json={
        "username": "doctor@pharmavigil.org",
        "password": "doctor123"
    })
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post("/api/auth/register", json={
        "username": f"newdoc_{uuid.uuid4().hex[:8]}",
        "password": "strongPassword123",
        "full_name": "Dr. Sub Doctor, MD",
        "role": "doctor",
        "medical_license": "MED-VALID-999"
    }, headers=headers)

    assert res.status_code == 200
    assert res.json()["user"]["role"] == "doctor"
    assert res.json()["user"]["medical_license"] == "MED-VALID-999"


def test_idor_protection_on_assigned_verification_requests(client):
    """Verify that Doctor B cannot respond to a request assigned to Doctor A."""
    # Seed Doctor A and Doctor B
    doc_a = register_user(
        username=f"doc_a_{uuid.uuid4().hex[:6]}",
        password="password12345",
        full_name="Doctor Alpha",
        role="doctor"
    )
    doc_b = register_user(
        username=f"doc_b_{uuid.uuid4().hex[:6]}",
        password="password12345",
        full_name="Doctor Beta",
        role="doctor"
    )

    vr = create_verification_request(
        dataset_name="proprietary_trial.csv",
        stored_path="/tmp/outputs/secret_file.csv",
        total_cases=50,
        submitted_by="Lead Analyst",
        assigned_doctor_id=doc_a["id"],
        assigned_doctor_name=doc_a["full_name"]
    )

    # Doctor B attempts to respond to Doctor A's request
    login_b = client.post("/api/auth/login", json={
        "username": doc_b["username"],
        "password": "password12345"
    })
    token_b = login_b.json()["token"]

    tamper_res = client.post(
        f"/api/verification-requests/{vr['request_id']}/respond",
        json={"decision": "APPROVED", "notes": "Tampered by Doctor B"},
        headers={"Authorization": f"Bearer {token_b}"}
    )
    assert tamper_res.status_code == 403
    assert "assigned to a different physician" in tamper_res.json()["detail"]

    # Doctor A legitimately responds
    login_a = client.post("/api/auth/login", json={
        "username": doc_a["username"],
        "password": "password12345"
    })
    token_a = login_a.json()["token"]

    legit_res = client.post(
        f"/api/verification-requests/{vr['request_id']}/respond",
        json={"decision": "APPROVED", "notes": "Approved by Doctor A"},
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert legit_res.status_code == 200
    assert legit_res.json()["request"]["doctor_name"] == "Doctor Alpha"


def test_stored_path_masking(client):
    """Verify that stored_path exposes only the filename and never full internal server directory paths."""
    vr = create_verification_request(
        dataset_name="masked_path_test.csv",
        stored_path="C:\\Users\\secret_admin\\outputs\\uploaded_dataset_123.csv",
        total_cases=10,
        submitted_by="Analyst"
    )

    res = client.get("/api/verification-requests")
    assert res.status_code == 200
    requests = res.json()["requests"]
    matched = next((r for r in requests if r["request_id"] == vr["request_id"]), None)
    assert matched is not None
    assert matched["stored_path"] == "uploaded_dataset_123.csv"
    assert "Users" not in matched["stored_path"]
    assert "secret_admin" not in matched["stored_path"]


def test_ssrf_protection_on_cloud_metadata(client):
    """Verify that SSRF targeting cloud metadata is blocked."""
    res = client.post("/api/generate", json={
        "llm_provider": "openai",
        "api_key": "dummy_test_key",
        "base_url": "http://169.254.169.254/latest/meta-data/"
    })
    assert res.status_code == 400
    assert "cloud metadata" in res.json()["detail"].lower()
