"""
Unit and integration tests for FastAPI backend routes and PADER REST endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from app import app, DEFAULT_SAMPLE_PATH


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "pharmavigil-regulatory-engine"


def test_cors_rejects_untrusted_credentialed_origin(client):
    response = client.options(
        "/api/auth/me",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_generate_rejects_arbitrary_local_file_path(client, tmp_path):
    outside_file = tmp_path / "private.csv"
    outside_file.write_text("safety_report_id,adverse_event\n1,Example", encoding="utf-8")
    # Login first since generate now requires auth
    login = client.post("/api/auth/login", json={"username": "doctor@pharmavigil.org", "password": "doctor123"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    response = client.post("/api/generate", json={"file_path": str(outside_file), "llm_provider": "mock"}, headers=headers)
    assert response.status_code == 400
    assert "uploaded through /api/upload" in response.json()["detail"]


def test_sample_data_endpoint(client):
    # Login first since sample-data now requires auth
    login = client.post("/api/auth/login", json={"username": "analyst@pharmavigil.org", "password": "analyst123"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    response = client.get("/api/sample-data", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "total_rows" in data
    assert data["total_cases"] > 0
    assert "reporting_period" in data
    assert "top_reactions" in data


def test_generate_report_pipeline(client):
    # Login first since generate now requires auth
    login = client.post("/api/auth/login", json={"username": "analyst@pharmavigil.org", "password": "analyst123"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    
    payload = {
        "llm_provider": "mock",
        "model_name": "mock-model-v1",
        "reviewer_name": "Test Reviewer, MD"
    }
    response = client.post("/api/generate", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    report_id = data["report_id"]
    assert report_id.startswith("PADER-")
    assert data["report_status"] == "DRAFT_PENDING_REVIEW"
    assert data["evaluation"]["required_sections_present"] == 8
    assert data["evaluation"]["automated_evaluation_status"] == "PASS"

    # Test report retrieval
    get_res = client.get(f"/api/reports/{report_id}", headers=headers)
    assert get_res.status_code == 200

    # Test markdown retrieval
    md_res = client.get(f"/api/reports/{report_id}/markdown", headers=headers)
    assert md_res.status_code == 200
    assert "# Periodic Adverse Drug Experience Report" in md_res.text


def test_human_review_sign_off(client):
    # Login as analyst to generate draft
    analyst_login = client.post("/api/auth/login", json={
        "username": "analyst@pharmavigil.org",
        "password": "analyst123",
    })
    analyst_headers = {"Authorization": f"Bearer {analyst_login.json()['token']}"}
    
    # First generate draft
    gen_res = client.post("/api/generate", json={"llm_provider": "mock"}, headers=analyst_headers)
    assert gen_res.status_code == 200
    report_id = gen_res.json()["report_id"]

    # Submit Human Approval as doctor
    rev_payload = {
        "decision": "APPROVED",
        "reviewer_name": "Dr. Sarah Connor, Chief Medical Officer",
        "notes": "Verified all 15-day alert tables and MedDRA counts."
    }
    login = client.post("/api/auth/login", json={
        "username": "doctor@pharmavigil.org",
        "password": "doctor123",
    })
    assert login.status_code == 200
    rev_res = client.post(
        f"/api/reports/{report_id}/review",
        json=rev_payload,
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert rev_res.status_code == 200
    rev_data = rev_res.json()
    assert rev_data["new_status"] == "HUMAN_APPROVED"
    assert rev_data["is_human_approved"] is True
    assert rev_data["review_record"]["reviewer_name"] == login.json()["user"]["full_name"]


def test_root_backend_status(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "service" in data
    assert data["docs_url"] == "/docs"
    assert data["health_check"] == "/api/health"


def test_serve_dashboard_html(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "GenAR PADER Regulatory Report Engine" in response.text
    assert "<!DOCTYPE html>" in response.text
