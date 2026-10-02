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
    assert data["service"] == "pader-regulatory-engine"


def test_sample_data_endpoint(client):
    response = client.get("/api/sample-data")
    assert response.status_code == 200
    data = response.json()
    assert "total_rows" in data
    assert data["total_cases"] > 0
    assert "reporting_period" in data
    assert "top_reactions" in data


def test_generate_report_pipeline(client):
    payload = {
        "llm_provider": "mock",
        "model_name": "mock-model-v1",
        "reviewer_name": "Test Reviewer, MD"
    }
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    report_id = data["report_id"]
    assert report_id.startswith("PADER-")
    assert data["report_status"] == "DRAFT_PENDING_REVIEW"
    assert data["evaluation"]["required_sections_present"] == 8
    assert data["evaluation"]["automated_evaluation_status"] == "PASS"

    # Test report retrieval
    get_res = client.get(f"/api/reports/{report_id}")
    assert get_res.status_code == 200

    # Test markdown retrieval
    md_res = client.get(f"/api/reports/{report_id}/markdown")
    assert md_res.status_code == 200
    assert "# Periodic Adverse Drug Experience Report" in md_res.text


def test_human_review_sign_off(client):
    # First generate draft
    gen_res = client.post("/api/generate", json={"llm_provider": "mock"})
    assert gen_res.status_code == 200
    report_id = gen_res.json()["report_id"]

    # Submit Human Approval
    rev_payload = {
        "decision": "APPROVED",
        "reviewer_name": "Dr. Sarah Connor, Chief Medical Officer",
        "notes": "Verified all 15-day alert tables and MedDRA counts."
    }
    rev_res = client.post(f"/api/reports/{report_id}/review", json=rev_payload)
    assert rev_res.status_code == 200
    rev_data = rev_res.json()
    assert rev_data["new_status"] == "HUMAN_APPROVED"
    assert rev_data["is_human_approved"] is True
    assert rev_data["review_record"]["reviewer_name"] == "Dr. Sarah Connor, Chief Medical Officer"


def test_serve_dashboard_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "GenAR PADER Regulatory Report Engine" in response.text
    assert "<!DOCTYPE html>" in response.text
