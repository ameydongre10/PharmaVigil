"""
Comprehensive End-to-End Tests for:
1. Dataset Upload & Custom Dataset Analysis
2. Doctor Human Verification System
3. Authentication & Role-Based Access Control (RBAC)
4. Verification Backend Validation & Security Checks
"""

import io
from pathlib import Path
import pytest
import uuid
from fastapi.testclient import TestClient
from app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_custom_dataset_upload_and_analysis(client, tmp_path):
    """Requirement 1: Upload new CSV/Excel datasets and analyze the uploaded dataset instead of default."""
    csv_content = """safety_report_id,received_date,serious,alert,occur_country,age,gender,adverse_event,medicinal_product
AMOX-001,2024-01-15,1,1,USA,45,Male,Anaphylactic reaction,Amoxicillin
AMOX-002,2024-01-20,0,0,USA,32,Female,Rash,Amoxicillin
AMOX-003,2024-02-10,1,1,FRA,58,Female,Urticaria,Amoxicillin
AMOX-004,2024-02-18,0,0,DEU,27,Male,Nausea,Amoxicillin
"""
    file_bytes = io.BytesIO(csv_content.encode("utf-8"))
    upload_res = client.post(
        "/api/upload",
        files={"file": ("amoxicillin_study.csv", file_bytes, "text/csv")}
    )
    assert upload_res.status_code == 200
    up_data = upload_res.json()
    assert up_data["status"] == "success"
    assert up_data["total_cases"] == 4
    assert up_data["serious_cases"] == 2
    assert up_data["serious_percentage"] == 50.0
    assert up_data["expedited_alerts"] == 2
    assert up_data["top_reactions"]["Rash"] == 1
    assert up_data["top_reactions"]["Anaphylactic reaction"] == 1

    # Verify /api/sample-data returns the active uploaded dataset summary
    summary_res = client.get("/api/sample-data")
    assert summary_res.status_code == 200
    summary_data = summary_res.json()
    assert summary_data["total_cases"] == 4
    assert summary_data["serious_cases"] == 2

    # Generate PADER report from the uploaded dataset
    gen_res = client.post("/api/generate", json={
        "file_path": up_data["stored_path"],
        "llm_provider": "mock"
    })
    assert gen_res.status_code == 200
    gen_data = gen_res.json()
    assert gen_data["product_name"] == "AMOXICILLIN"
    assert "PADER-AMOXICILLIN-" in gen_data["report_id"]

    # Verify structured tables inside report reflect the 4 cases
    report = gen_data["report"]
    summary_sec = next(s for s in report["sections"] if s["section_name"] == "Summary Analysis of Cases")
    vol_table = summary_sec["structured_tables"]["volume"]
    assert vol_table["total_cases"] == 4
    assert vol_table["serious_cases"] == 2
    assert vol_table["serious_pct"] == 50.0

    # Reset active dataset back to bundled benchmark
    reset_res = client.post("/api/dataset/reset")
    assert reset_res.status_code == 200
    reset_summary = client.get("/api/sample-data").json()
    assert reset_summary["total_cases"] == 1024


def test_authentication_and_rbac(client):
    """Requirement 3: Secure login/register authentication with role-based access."""
    # Register Doctor with license
    doc_reg = client.post("/api/auth/register", json={
        f"username": f"dr_watson_{uuid.uuid4().hex[:6]}",
        "password": "securepassword123",
        "full_name": "Dr. John Watson, MD",
        "role": "doctor",
        "medical_license": "GMC-994821",
        "specialty": "Clinical Safety",
        "affiliation": "St. Marys Hospital"
    })
    assert doc_reg.status_code == 200
    doc_data = doc_reg.json()
    assert doc_data["status"] == "success"
    assert doc_data["user"]["role"] == "doctor"
    assert doc_data["user"]["medical_license"] == "GMC-994821"
    doc_token = doc_data["token"]

    # Register Analyst (non-doctor)
    ana_reg = client.post("/api/auth/register", json={
        f"username": f"analyst_bob_{uuid.uuid4().hex[:6]}",
        "password": "securepassword123",
        "full_name": "Bob Analyst",
        "role": "analyst"
    })
    assert ana_reg.status_code == 200
    assert ana_reg.json()["user"]["role"] == "analyst"

    # Test /api/auth/me
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {doc_token}"})
    assert me_res.status_code == 200
    assert me_res.json()["user"]["username"].startswith("dr_watson_")

    # Test Pre-seeded Demo Accounts
    doc_login = client.post("/api/auth/login", json={
        "username": "doctor@pharmavigil.org",
        "password": "doctor123"
    })
    assert doc_login.status_code == 200
    assert doc_login.json()["user"]["role"] == "doctor"
    assert doc_login.json()["user"]["medical_license"] == "MED-PV-849201"

    ana_login = client.post("/api/auth/login", json={
        "username": "analyst@pharmavigil.org",
        "password": "analyst123"
    })
    assert ana_login.status_code == 200
    assert ana_login.json()["user"]["role"] == "analyst"

    # Invalid login test
    bad_login = client.post("/api/auth/login", json={
        "username": "doctor@pharmavigil.org",
        "password": "wrongpassword"
    })
    assert bad_login.status_code == 401


def test_registration_rejects_short_password(client):
    response = client.post("/api/auth/register", json={
        "username": f"short_{uuid.uuid4().hex[:8]}",
        "password": "123",
        "full_name": "Example User",
        "role": "analyst",
    })
    assert response.status_code == 422


def test_doctor_verification_and_database_audit(client):
    """Requirements 2 & 4: Doctor Human Verification clearly associated and validated by backend/database."""
    # Generate draft
    gen_res = client.post("/api/generate", json={"llm_provider": "mock"})
    assert gen_res.status_code == 200
    report_id = gen_res.json()["report_id"]

    # Login as Doctor
    login_res = client.post("/api/auth/login", json={
        "username": "doctor@pharmavigil.org",
        "password": "doctor123"
    })
    token = login_res.json()["token"]

    # Submit Doctor Verification
    rev_payload = {
        "decision": "APPROVED",
        "notes": "All expedited 15-day alerts and MedDRA preferred terms clinically validated."
    }
    rev_res = client.post(
        f"/api/reports/{report_id}/review",
        json=rev_payload,
        headers={"Authorization": f"Bearer {token}"}
    )
    assert rev_res.status_code == 200
    rev_data = rev_res.json()
    assert rev_data["new_status"] == "HUMAN_APPROVED"
    assert rev_data["is_human_approved"] is True

    # Verification record checks
    rec = rev_data["review_record"]
    assert rec["doctor_license"] == "MED-PV-849201"
    assert rec["reviewer_name"] == "Dr. Eleanor Vance, MD"
    assert rec["verification_id"].startswith("VERIF-")
    assert len(rec["signature_hash"]) == 64 # SHA-256

    # Verify retrievable from database via verification endpoint
    verif_res = client.get(f"/api/reports/{report_id}/verification")
    assert verif_res.status_code == 200
    v_info = verif_res.json()
    assert v_info["verified"] is True
    assert v_info["verification"]["doctor_name"] == "Dr. Eleanor Vance, MD"
    assert v_info["verification"]["signature_hash"] == rec["signature_hash"]

    # Verify Markdown export contains official doctor sign-off section
    md_res = client.get(f"/api/reports/{report_id}/markdown")
    assert md_res.status_code == 200
    assert "## Human Review & Medical Verification Sign-Off" in md_res.text
    assert "MED-PV-849201" in md_res.text
    assert rec["signature_hash"] in md_res.text


def test_verification_validation_blocks_unauthorized_access(client):
    """Requirement 4: Verification cannot simply be marked as verified without doctor authorization."""
    # Generate draft
    gen_res = client.post("/api/generate", json={"llm_provider": "mock"})
    assert gen_res.status_code == 200
    report_id = gen_res.json()["report_id"]

    # 1. Unauthenticated spoof attempt with arbitrary name -> 401 Unauthorized
    spoof_res = client.post(f"/api/reports/{report_id}/review", json={
        "decision": "APPROVED",
        "reviewer_name": "Unverified User",
        "notes": "Attempting unauthorized bypass"
    })
    assert spoof_res.status_code == 401

    # A known doctor's display name is not authentication and cannot be used
    # to impersonate the seeded doctor account.
    known_doctor_spoof = client.post(f"/api/reports/{report_id}/review", json={
        "decision": "APPROVED",
        "reviewer_name": "Dr. Eleanor Vance, MD",
        "notes": "Impersonation attempt",
    })
    assert known_doctor_spoof.status_code == 401

    # 2. Authenticated Analyst (non-doctor) attempt -> 403 Forbidden
    ana_login = client.post("/api/auth/login", json={
        "username": "analyst@pharmavigil.org",
        "password": "analyst123"
    })
    ana_token = ana_login.json()["token"]

    ana_rev = client.post(
        f"/api/reports/{report_id}/review",
        json={"decision": "APPROVED", "notes": "Analyst signing off"},
        headers={"Authorization": f"Bearer {ana_token}"}
    )
    assert ana_rev.status_code == 403
    assert "Only authenticated medical professionals with the Doctor/Verifier role" in ana_rev.json()["detail"]


def test_excel_dataset_upload_and_analysis(client):
    """Requirement 1: Verify Excel (.xlsx) dataset upload and processing."""
    import pandas as pd
    df = pd.DataFrame([
        {
            "safety_report_id": "EX-001",
            "received_date": "2024-03-01",
            "serious": 1,
            "alert": 1,
            "occur_country": "CAN",
            "age": 60,
            "gender": "Female",
            "adverse_event": "Dyspnoea",
            "medicinal_product": "Cefalexin"
        },
        {
            "safety_report_id": "EX-002",
            "received_date": "2024-03-05",
            "serious": 0,
            "alert": 0,
            "occur_country": "USA",
            "age": 30,
            "gender": "Male",
            "adverse_event": "Headache",
            "medicinal_product": "Cefalexin"
        }
    ])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)

    upload_res = client.post(
        "/api/upload",
        files={"file": ("cefalexin_study.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert upload_res.status_code == 200
    up_data = upload_res.json()
    assert up_data["status"] == "success"
    assert up_data["total_cases"] == 2
    assert up_data["serious_cases"] == 1
    assert up_data["serious_percentage"] == 50.0
    client.post("/api/dataset/reset")


def test_upload_rejects_file_over_limit(client):
    oversized = io.BytesIO(b"x" * (25 * 1024 * 1024 + 1))
    response = client.post(
        "/api/upload",
        files={"file": ("large.csv", oversized, "text/csv")},
    )
    assert response.status_code == 413
    assert "25 MiB" in response.json()["detail"]


def test_upload_storage_name_is_not_client_controlled(client):
    csv_content = "safety_report_id,adverse_event\nSAFE-001,Rash\n"
    response = client.post(
        "/api/upload",
        files={"file": ("../../same.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    assert response.status_code == 200
    stored_path = Path(response.json()["stored_path"]).resolve()
    assert stored_path.parent == (Path(__file__).resolve().parents[1] / "outputs").resolve()
    assert stored_path.name != "same.csv"
    # Reset back to benchmark dataset
    client.post("/api/dataset/reset")


def test_upload_validation_errors(client):
    """Tests strict validation and meaningful errors for upload edge cases."""
    # 1. Invalid file type (.pdf)
    res_pdf = client.post("/api/upload", files={"file": ("trial.pdf", io.BytesIO(b"%PDF-1.4 header"), "application/pdf")})
    assert res_pdf.status_code == 400
    assert "Invalid file type" in res_pdf.json()["detail"]

    # 2. Empty dataset (0 bytes)
    res_empty = client.post("/api/upload", files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")})
    assert res_empty.status_code == 400
    assert "Empty dataset" in res_empty.json()["detail"]

    # 3. Malformed CSV (unclosed quote error)
    res_malformed = client.post("/api/upload", files={"file": ("malformed.csv", io.BytesIO(b"col1,col2\n\"unclosed quote,123"), "text/csv")})
    assert res_malformed.status_code == 400
    assert "Malformed CSV file" in res_malformed.json()["detail"] or "Error tokenizing" in res_malformed.json()["detail"]

    # 4. Missing required ICSR fields (unrelated data schema)
    res_groceries = client.post("/api/upload", files={"file": ("groceries.csv", io.BytesIO(b"item,price,quantity\nApple,1.5,10\nBanana,0.8,20"), "text/csv")})
    assert res_groceries.status_code == 400
    assert "Missing required ICSR fields" in res_groceries.json()["detail"]


def test_no_silent_fallback_on_missing_dataset(client):
    """Requirement: Never silently fall back to default dataset when a custom dataset was specified."""
    res = client.post("/api/generate", json={"file_path": "non_existent_study_dataset.csv", "llm_provider": "mock"})
    assert res.status_code == 404
    assert "not found on the server" in res.json()["detail"]


def test_dataset_persistence_and_reset(client):
    """Requirement: Uploaded dataset becomes and remains active until explicitly reset."""
    csv_data = """case_number,event_date,serious_case,alert_case,country,patient_age,patient_sex,preferred_term,drug_name
CASE-901,2024-04-01,1,1,FRA,42,Female,Steven-Johnson syndrome,Lamotrigine
CASE-902,2024-04-05,0,0,DEU,35,Male,Pruritus,Lamotrigine
"""
    upload_res = client.post("/api/upload", files={"file": ("lamotrigine_safety.csv", io.BytesIO(csv_data.encode()), "text/csv")})
    assert upload_res.status_code == 200
    up_data = upload_res.json()
    assert up_data["total_cases"] == 2
    assert up_data["is_custom_dataset"] is True

    # Check sample-data endpoint returns this active uploaded dataset
    sample_res = client.get("/api/sample-data")
    assert sample_res.status_code == 200
    s_data = sample_res.json()
    assert s_data["total_cases"] == 2
    assert s_data["is_custom_dataset"] is True
    assert "lamotrigine" in s_data["dataset_name"].lower()

    # Generate report and verify report uses the custom dataset
    gen_res = client.post("/api/generate", json={"llm_provider": "mock"})
    assert gen_res.status_code == 200
    g_data = gen_res.json()
    assert g_data["is_custom_dataset"] is True
    assert "lamotrigine" in g_data["dataset_analyzed"].lower()
    assert g_data["product_name"] == "LAMOTRIGINE"

    # Reset back to reference benchmark
    reset_res = client.post("/api/dataset/reset")
    assert reset_res.status_code == 200
    sample_after_reset = client.get("/api/sample-data").json()
    assert sample_after_reset["is_custom_dataset"] is False
    assert sample_after_reset["total_cases"] == 1024
