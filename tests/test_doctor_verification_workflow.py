"""
Unit tests for Doctor Selection and Verification Request Queue Workflow.
"""

import unittest
import tempfile
from pathlib import Path

from src.auth import (
    init_auth_db, register_user, authenticate_user,
    get_registered_doctors, create_verification_request,
    list_verification_requests, get_verification_request,
    update_verification_request_decision
)


class TestDoctorVerificationWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_pharmavigil.db"
        init_auth_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_seeded_doctor(self):
        doctors = get_registered_doctors(self.db_path)
        self.assertGreaterEqual(len(doctors), 1)
        doc = doctors[0]
        self.assertIn("doctor", doc["role"])
        self.assertTrue(doc["full_name"].startswith("Dr."))
        self.assertIsNotNone(doc["medical_license"])

    def test_new_doctor_registration_and_listing(self):
        # Register a new doctor
        new_doc = register_user(
            username="dr.jones@hospital.org",
            password="securePassword123",
            full_name="Dr. Indiana Jones, MD",
            role="doctor",
            medical_license="MED-CA-998877",
            specialty="Neuropharmacology",
            affiliation="Metropolitan General Hospital",
            db_path=self.db_path
        )
        self.assertEqual(new_doc["role"], "doctor")
        self.assertEqual(new_doc["medical_license"], "MED-CA-998877")

        # Verify new doctor appears in registered doctors list
        doctors = get_registered_doctors(self.db_path)
        doctor_names = [d["full_name"] for d in doctors]
        self.assertIn("Dr. Indiana Jones, MD", doctor_names)

    def test_create_and_list_verification_request(self):
        doctors = get_registered_doctors(self.db_path)
        target_doc = doctors[0]

        # Analyst submits dataset for doctor review
        vr = create_verification_request(
            dataset_name="sample_atorvastatin.csv",
            stored_path="/tmp/uploaded_atorvastatin.csv",
            total_cases=1024,
            serious_cases=500,
            serious_pct=48.8,
            expedited_alerts=25,
            submitted_by="Alex Chen, MS",
            assigned_doctor_id=target_doc["id"],
            assigned_doctor_name=target_doc["full_name"],
            assigned_doctor_license=target_doc["medical_license"],
            db_path=self.db_path
        )

        self.assertIsNotNone(vr["request_id"])
        self.assertEqual(vr["status"], "PENDING_DOCTOR_REVIEW")
        self.assertEqual(vr["assigned_doctor_name"], target_doc["full_name"])

        # Fetch pending requests for that doctor
        doc_reqs = list_verification_requests(doctor_id=target_doc["id"], db_path=self.db_path)
        self.assertTrue(any(r["request_id"] == vr["request_id"] for r in doc_reqs))

    def test_doctor_request_changes(self):
        doctors = get_registered_doctors(self.db_path)
        target_doc = doctors[0]

        vr = create_verification_request(
            dataset_name="sample_batch.csv",
            total_cases=100,
            serious_cases=10,
            expedited_alerts=2,
            submitted_by="Alex Chen, MS",
            assigned_doctor_id=target_doc["id"],
            assigned_doctor_name=target_doc["full_name"],
            db_path=self.db_path
        )

        # Doctor reviews and requests clinical changes
        updated = update_verification_request_decision(
            request_id=vr["request_id"],
            decision="NEEDS_REVISION",
            doctor_user=target_doc,
            notes="Please re-verify hepatic failure causality for cases 12 and 15.",
            db_path=self.db_path
        )

        self.assertEqual(updated["status"], "NEEDS_REVISION")
        self.assertEqual(updated["doctor_decision"], "NEEDS_REVISION")
        self.assertIn("hepatic failure", updated["doctor_notes"])
        self.assertEqual(updated["doctor_name"], target_doc["full_name"])


if __name__ == "__main__":
    unittest.main()
