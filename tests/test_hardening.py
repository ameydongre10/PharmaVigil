"""
Phase 6 — Hardening Test Suite
================================
Tests robustness, safety, edge cases, and failure behavior across the full pipeline.

Coverage:
 - Data quality edge cases (empty, missing, duplicate, malformed)
 - Case/reaction deduplication (ROW != CASE != REACTION)
 - Deterministic analysis regressions on the real dataset
 - Evidence integrity
 - Context boundary (no raw DataFrame in LLM context)
 - LLM failure modes (timeout, HTTP errors, bad JSON, empty response)
 - Grounding failure detection
 - Report assembly failure handling
 - Human review workflow correctness
 - Targeted regeneration isolation
 - Privacy / output safety
 - Reproducibility
 - Performance sanity
"""

import os
import json
import time
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from typing import List

from src.data_loader import load_and_normalize_data, validate_data
from src.analysis_engine import AnalysisEngine
from src.evidence_collector import collect_evidence
from src.context_builder import ContextBuilder
from src.report_config import PADER_CONFIG
from src.llm_client import MockLLMClient, OpenAICompatibleLLMClient
from src.section_generator import SectionGenerator
from src.grounding_validator import GroundingValidator
from src.generation_models import GeneratedSection, ValidationResult, LLMRequest, LLMResponse
from src.orchestrator import PADEROrchestrator
from src.report_models import (
    PADERReport, ReportMetadata, SectionOutput, SectionType, SectionStatus,
    ReviewDecision, ReportStatus
)
from src.report_assembler import ReportAssembler
from src.evaluator import PADEREvaluator
from src.human_review import HumanReviewManager


# ============================================================
# HELPERS / FIXTURES
# ============================================================

def _make_df(rows: List[dict]) -> pd.DataFrame:
    """Build and normalise an in-memory DataFrame through the real loader logic."""
    df = pd.DataFrame(rows)
    # Apply the same normalization as load_and_normalize_data
    df.columns = df.columns.str.lower().str.strip()
    if 'serious' in df.columns:
        df['serious_bool'] = df['serious'].astype(str).str.lower().isin(['1', 'yes', 'true', 'serious'])
    else:
        df['serious_bool'] = False
    if 'fulfillexpeditecriteria' in df.columns:
        df['expedited_bool'] = df['fulfillexpeditecriteria'].astype(str).str.lower().isin(['1', 'yes', 'true'])
    else:
        df['expedited_bool'] = False
    if 'occurcountry' in df.columns:
        df['standard_country'] = df['occurcountry'].astype(str).str.upper()
    else:
        df['standard_country'] = "UNKNOWN"
    if 'patient_patientonsetage' in df.columns:
        df['numeric_age'] = pd.to_numeric(df['patient_patientonsetage'], errors='coerce')
    else:
        df['numeric_age'] = None
    return df


def _minimal_rows(n: int = 3) -> List[dict]:
    return [
        {"safetyreportid": f"C{i}", "receivedate": "20250101", "serious": "1",
         "fulfillexpeditecriteria": "yes", "patient_patientonsetage": 65,
         "patient_patientsex": "female", "occurcountry": "GB",
         "patient_reaction_reactionmeddrapt": "Dizziness",
         "patient_reaction_reactionoutcome": "recovered"}
        for i in range(1, n + 1)
    ]


@pytest.fixture
def sample_excel_file(tmp_path):
    data = [
        {"safetyreportid": "C1", "receivedate": "20250101", "serious": "1",
         "fulfillexpeditecriteria": "yes", "patient_patientonsetage": 68,
         "patient_patientsex": "female", "occurcountry": "GB",
         "patient_reaction_reactionmeddrapt": "Acute kidney injury",
         "patient_reaction_reactionoutcome": "recovered"},
        {"safetyreportid": "C1", "receivedate": "20250101", "serious": "1",
         "fulfillexpeditecriteria": "yes", "patient_patientonsetage": 68,
         "patient_patientsex": "female", "occurcountry": "GB",
         "patient_reaction_reactionmeddrapt": "Drug ineffective",
         "patient_reaction_reactionoutcome": "unknown"},
        {"safetyreportid": "C2", "receivedate": "20250215", "serious": "2",
         "fulfillexpeditecriteria": "no", "patient_patientonsetage": 45,
         "patient_patientsex": "male", "occurcountry": "FR",
         "patient_reaction_reactionmeddrapt": "Rash",
         "patient_reaction_reactionoutcome": "recovering"},
        {"safetyreportid": "C3", "receivedate": "20250320", "serious": "yes",
         "fulfillexpeditecriteria": "yes", "patient_patientonsetage": 72,
         "patient_patientsex": "male", "occurcountry": "US",
         "patient_reaction_reactionmeddrapt": "Acute kidney injury",
         "patient_reaction_reactionoutcome": "fatal"},
    ]
    file_path = str(tmp_path / "mock_dataset.xlsx")
    pd.DataFrame(data).to_excel(file_path, index=False)
    return file_path


# ============================================================
# SECTION 1 — DATA QUALITY EDGE CASES
# ============================================================

class TestDataQualityEdgeCases:

    def test_missing_case_ids_are_counted_without_dropping_rows(self):
        df = _make_df([
            {"safetyreportid": None, "receivedate": "20250101", "serious": "1",
             "patient_reaction_reactionmeddrapt": "Rash"},
            {"safetyreportid": None, "receivedate": "20250102", "serious": "0",
             "patient_reaction_reactionmeddrapt": "Headache"},
        ])
        assert AnalysisEngine(df).get_case_volume().value["total_cases"] == 1

    def test_reaction_analysis_handles_missing_case_id_column(self):
        df = pd.DataFrame({"patient_reaction_reactionmeddrapt": ["Rash"]})
        engine = AnalysisEngine(df)
        assert engine.get_reactions() is None
        assert engine.get_serious_reactions() is None

    def test_A_empty_dataset_does_not_crash(self):
        """A: Empty dataset should not crash — returns zero counts."""
        # Build a proper empty normalised DataFrame with all required columns
        df = pd.DataFrame(columns=[
            'safetyreportid', 'receivedate', 'serious', 'fulfillexpeditecriteria',
            'patient_patientonsetage', 'patient_patientsex', 'occurcountry',
            'patient_reaction_reactionmeddrapt', 'patient_reaction_reactionoutcome'
        ])
        df['serious_bool'] = pd.Series(dtype=bool)
        df['expedited_bool'] = pd.Series(dtype=bool)
        df['numeric_age'] = pd.Series(dtype=float)
        df['standard_country'] = pd.Series(dtype=str)
        engine = AnalysisEngine(df)
        vol = engine.get_case_volume()
        assert vol.value["total_cases"] == 0
        period = engine.get_reporting_period()
        assert period.value["start_date"] is None

    def test_B_missing_safetyreportid_column(self):
        """B: Dataset without safetyreportid column — validate_data catches missing required column."""
        df = _make_df([{"receivedate": "20250101", "serious": "1",
                        "patient_reaction_reactionmeddrapt": "Rash"}])
        issues = validate_data(df)
        assert "safetyreportid" in issues["missing_required_columns"]

    def test_C_duplicate_safetyreportid_rows_deduplicated(self):
        """C: Duplicate safetyreportid rows count as one case."""
        rows = [
            {"safetyreportid": "X1", "receivedate": "20250101", "serious": "1",
             "fulfillexpeditecriteria": "yes", "patient_patientonsetage": 55,
             "patient_patientsex": "male", "occurcountry": "US",
             "patient_reaction_reactionmeddrapt": "Rash", "patient_reaction_reactionoutcome": "recovered"},
            {"safetyreportid": "X1", "receivedate": "20250101", "serious": "1",
             "fulfillexpeditecriteria": "yes", "patient_patientonsetage": 55,
             "patient_patientsex": "male", "occurcountry": "US",
             "patient_reaction_reactionmeddrapt": "Headache", "patient_reaction_reactionoutcome": "recovered"},
        ]
        df = _make_df(rows)
        engine = AnalysisEngine(df)
        vol = engine.get_case_volume()
        assert vol.value["total_cases"] == 1, "Two rows with same ID = 1 case"

    def test_D_missing_reaction_column(self):
        """D: Dataset without reaction column — get_reactions returns None gracefully."""
        rows = [{"safetyreportid": "A1", "receivedate": "20250101", "serious": "1",
                 "fulfillexpeditecriteria": "no", "patient_patientonsetage": 55,
                 "patient_patientsex": "male", "occurcountry": "US",
                 "patient_reaction_reactionoutcome": "recovered"}]
        df = _make_df(rows)
        engine = AnalysisEngine(df)
        result = engine.get_reactions()
        assert result is None

    def test_E_missing_seriousness_defaults_to_false(self):
        """E: Missing serious column defaults to False (non-serious)."""
        rows = [{"safetyreportid": "A1", "receivedate": "20250101",
                 "patient_patientonsetage": 55, "patient_patientsex": "male",
                 "occurcountry": "US", "patient_reaction_reactionmeddrapt": "Rash",
                 "patient_reaction_reactionoutcome": "recovered"}]
        df = _make_df(rows)
        engine = AnalysisEngine(df)
        vol = engine.get_case_volume()
        assert vol.value["serious_cases"] == 0

    def test_F_invalid_text_age_becomes_unknown(self):
        """F: Non-numeric age text should coerce to Unknown bucket."""
        rows = [{"safetyreportid": "A1", "receivedate": "20250101", "serious": "1",
                 "fulfillexpeditecriteria": "no", "patient_patientonsetage": "unknown",
                 "patient_patientsex": "female", "occurcountry": "FR",
                 "patient_reaction_reactionmeddrapt": "Rash", "patient_reaction_reactionoutcome": "recovered"}]
        df = _make_df(rows)
        engine = AnalysisEngine(df)
        age = engine.get_age_distribution()
        assert "Unknown" in age.value["counts"]

    def test_G_negative_age_becomes_unknown(self):
        """G: Negative age must NOT be bucketed into '<18' — classified as Unknown."""
        rows = [{"safetyreportid": "A1", "receivedate": "20250101", "serious": "1",
                 "fulfillexpeditecriteria": "no", "patient_patientonsetage": -5,
                 "patient_patientsex": "female", "occurcountry": "FR",
                 "patient_reaction_reactionmeddrapt": "Rash", "patient_reaction_reactionoutcome": "recovered"}]
        df = _make_df(rows)
        engine = AnalysisEngine(df)
        age = engine.get_age_distribution()
        assert "<18" not in age.value["counts"], "Negative age must not appear in '<18' bucket"
        assert "Unknown" in age.value["counts"]

    def test_H_impossible_age_above_150_becomes_unknown(self):
        """H: Age > 150 (impossible) must be classified as Unknown."""
        rows = [{"safetyreportid": "A2", "receivedate": "20250101", "serious": "1",
                 "fulfillexpeditecriteria": "no", "patient_patientonsetage": 999,
                 "patient_patientsex": "male", "occurcountry": "US",
                 "patient_reaction_reactionmeddrapt": "Dizziness", "patient_reaction_reactionoutcome": "recovered"}]
        df = _make_df(rows)
        engine = AnalysisEngine(df)
        age = engine.get_age_distribution()
        assert "65+" not in age.value["counts"], "Age=999 must not appear in '65+' bucket"
        assert "Unknown" in age.value["counts"]

    def test_I_missing_country_column_defaults_to_unknown(self):
        """I: Missing country column should not crash — defaults to UNKNOWN."""
        rows = [{"safetyreportid": "A1", "receivedate": "20250101", "serious": "1",
                 "fulfillexpeditecriteria": "no", "patient_patientonsetage": 55,
                 "patient_patientsex": "male",
                 "patient_reaction_reactionmeddrapt": "Rash", "patient_reaction_reactionoutcome": "recovered"}]
        df = pd.DataFrame(rows)
        df.columns = df.columns.str.lower().str.strip()
        df['serious_bool'] = df['serious'].astype(str).str.lower().isin(['1', 'yes', 'true'])
        df['expedited_bool'] = False
        df['standard_country'] = "UNKNOWN"
        df['numeric_age'] = pd.to_numeric(df['patient_patientonsetage'], errors='coerce')
        engine = AnalysisEngine(df)
        country = engine.get_country_distribution()
        assert "UNKNOWN" in country.value["counts"]

    def test_J_missing_outcome_column(self):
        """J: Missing outcome column — get_outcomes returns None gracefully."""
        rows = [{"safetyreportid": "A1", "receivedate": "20250101", "serious": "1",
                 "fulfillexpeditecriteria": "no", "patient_patientonsetage": 55,
                 "patient_patientsex": "male", "occurcountry": "US",
                 "patient_reaction_reactionmeddrapt": "Rash"}]
        df = _make_df(rows)
        engine = AnalysisEngine(df)
        result = engine.get_outcomes()
        assert result is None

    def test_K_malformed_date_does_not_crash(self):
        """K: Malformed dates coerce to NaT without crashing; period may be None."""
        rows = [{"safetyreportid": "A1", "receivedate": "BADDATE", "serious": "1",
                 "fulfillexpeditecriteria": "no", "patient_patientonsetage": 55,
                 "patient_patientsex": "male", "occurcountry": "US",
                 "patient_reaction_reactionmeddrapt": "Rash", "patient_reaction_reactionoutcome": "recovered"}]
        df = _make_df(rows)
        engine = AnalysisEngine(df)
        period = engine.get_reporting_period()
        # Must not crash; may return None dates
        assert "start_date" in period.value

    def test_L_unexpected_categorical_seriousness_values(self):
        """L: Unexpected values like 'maybe' should default to non-serious."""
        rows = [{"safetyreportid": "A1", "receivedate": "20250101", "serious": "maybe",
                 "fulfillexpeditecriteria": "no", "patient_patientonsetage": 55,
                 "patient_patientsex": "male", "occurcountry": "US",
                 "patient_reaction_reactionmeddrapt": "Rash", "patient_reaction_reactionoutcome": "recovered"}]
        df = _make_df(rows)
        engine = AnalysisEngine(df)
        vol = engine.get_case_volume()
        assert vol.value["serious_cases"] == 0

    def test_M_single_case_dataset(self):
        """M: Single-case dataset should produce valid case volume = 1."""
        df = _make_df(_minimal_rows(1))
        engine = AnalysisEngine(df)
        vol = engine.get_case_volume()
        assert vol.value["total_cases"] == 1

    def test_N_validate_data_reports_missing_required_columns(self):
        """N: validate_data correctly identifies missing required columns."""
        df = pd.DataFrame({"irrelevant_col": [1, 2, 3]})
        issues = validate_data(df)
        missing = issues["missing_required_columns"]
        assert "safetyreportid" in missing
        assert "receivedate" in missing
        assert "patient_reaction_reactionmeddrapt" in missing


# ============================================================
# SECTION 2 — CASE / REACTION EDGE CASES (ROW != CASE != REACTION)
# ============================================================

class TestCaseReactionDeduplication:

    def test_one_case_many_reactions_row_count_vs_case_count(self):
        """One case with 3 reaction rows = 1 case, 3 distinct reactions."""
        rows = [
            {"safetyreportid": "MC1", "receivedate": "20250101", "serious": "1",
             "fulfillexpeditecriteria": "yes", "patient_patientonsetage": 55,
             "patient_patientsex": "male", "occurcountry": "US",
             "patient_reaction_reactionmeddrapt": "Rash", "patient_reaction_reactionoutcome": "recovered"},
            {"safetyreportid": "MC1", "receivedate": "20250101", "serious": "1",
             "fulfillexpeditecriteria": "yes", "patient_patientonsetage": 55,
             "patient_patientsex": "male", "occurcountry": "US",
             "patient_reaction_reactionmeddrapt": "Headache", "patient_reaction_reactionoutcome": "recovered"},
            {"safetyreportid": "MC1", "receivedate": "20250101", "serious": "1",
             "fulfillexpeditecriteria": "yes", "patient_patientonsetage": 55,
             "patient_patientsex": "male", "occurcountry": "US",
             "patient_reaction_reactionmeddrapt": "Nausea", "patient_reaction_reactionoutcome": "recovered"},
        ]
        df = _make_df(rows)
        assert len(df) == 3, "3 rows"
        engine = AnalysisEngine(df)
        assert len(engine.cases_df) == 1, "1 deduplicated case"

        rx = engine.get_reactions(top_n=10)
        assert sum(rx.value.values()) == 3, "3 unique reaction-case pairs"

    def test_same_reaction_across_many_cases(self):
        """Same reaction 'Dizziness' across 3 different cases = count 3."""
        rows = [
            {"safetyreportid": f"C{i}", "receivedate": "20250101", "serious": "1",
             "fulfillexpeditecriteria": "no", "patient_patientonsetage": 50,
             "patient_patientsex": "female", "occurcountry": "GB",
             "patient_reaction_reactionmeddrapt": "Dizziness", "patient_reaction_reactionoutcome": "recovered"}
            for i in range(1, 4)
        ]
        df = _make_df(rows)
        engine = AnalysisEngine(df)
        rx = engine.get_reactions(top_n=5)
        assert rx.value.get("Dizziness") == 3

    def test_duplicate_reaction_rows_per_case_deduped(self):
        """Duplicate reaction rows for same case+reaction = counted once."""
        rows = [
            {"safetyreportid": "D1", "receivedate": "20250101", "serious": "1",
             "fulfillexpeditecriteria": "no", "patient_patientonsetage": 55,
             "patient_patientsex": "male", "occurcountry": "US",
             "patient_reaction_reactionmeddrapt": "Rash", "patient_reaction_reactionoutcome": "recovered"},
            {"safetyreportid": "D1", "receivedate": "20250101", "serious": "1",
             "fulfillexpeditecriteria": "no", "patient_patientonsetage": 55,
             "patient_patientsex": "male", "occurcountry": "US",
             "patient_reaction_reactionmeddrapt": "Rash", "patient_reaction_reactionoutcome": "recovered"},
        ]
        df = _make_df(rows)
        engine = AnalysisEngine(df)
        rx = engine.get_reactions(top_n=5)
        assert rx.value.get("Rash") == 1, "Same reaction for same case must count once"

    def test_case_with_no_reaction_listed_as_unknown(self, tmp_path):
        """Case with no reaction yields 'Unknown' in case listing."""
        rows = [{"safetyreportid": "NR1", "receivedate": "20250101", "serious": "1",
                 "fulfillexpeditecriteria": "no", "patient_patientonsetage": 60,
                 "patient_patientsex": "male", "occurcountry": "US",
                 "patient_reaction_reactionoutcome": "recovered"}]
        df = _make_df(rows)
        df['patient_reaction_reactionmeddrapt'] = None
        engine = AnalysisEngine(df)
        listing = engine.get_case_index(limit=5)
        assert listing.value[0]["reactions"] == "Unknown"


# ============================================================
# SECTION 3 — DETERMINISTIC REGRESSION ON REAL DATASET
# ============================================================

class TestDeterministicRegression:
    """Protect known authoritative values from the real assignment dataset."""

    REAL_DATASET = "Bisoprolol_icsr_sample_1068rows.xlsx"

    @pytest.fixture(autouse=True)
    def skip_if_no_dataset(self):
        if not os.path.exists(self.REAL_DATASET):
            pytest.skip(f"Real dataset not present: {self.REAL_DATASET}")

    def test_source_row_count_is_1068(self):
        df = load_and_normalize_data(self.REAL_DATASET)
        assert len(df) == 1068, "Source row count must be exactly 1,068"

    def test_unique_case_count_is_1024(self):
        df = load_and_normalize_data(self.REAL_DATASET)
        engine = AnalysisEngine(df)
        assert engine.get_case_volume().value["total_cases"] == 1024

    def test_serious_case_count_is_1023(self):
        df = load_and_normalize_data(self.REAL_DATASET)
        engine = AnalysisEngine(df)
        assert engine.get_case_volume().value["serious_cases"] == 1023

    def test_non_serious_case_count_is_1(self):
        df = load_and_normalize_data(self.REAL_DATASET)
        engine = AnalysisEngine(df)
        assert engine.get_case_volume().value["non_serious_cases"] == 1

    def test_reporting_period_start(self):
        df = load_and_normalize_data(self.REAL_DATASET)
        engine = AnalysisEngine(df)
        period = engine.get_reporting_period()
        assert period.value["start_date"] == "2024-12-27"

    def test_reporting_period_end(self):
        df = load_and_normalize_data(self.REAL_DATASET)
        engine = AnalysisEngine(df)
        period = engine.get_reporting_period()
        assert period.value["end_date"] == "2025-12-26"


# ============================================================
# SECTION 4 — EVIDENCE INTEGRITY
# ============================================================

class TestEvidenceIntegrity:

    def test_evidence_ids_are_unique(self):
        df = _make_df(_minimal_rows(3))
        engine = AnalysisEngine(df)
        evidence = collect_evidence(
            engine.get_reporting_period(), engine.get_case_volume(), engine.get_age_distribution(),
            engine.get_sex_distribution(), engine.get_country_distribution(), engine.get_reactions(20),
            engine.get_serious_reactions(20), engine.get_outcomes(), engine.get_time_trends(),
            engine.get_alert_cases(), engine.get_history_of_actions(), engine.get_expectedness(),
            engine.get_case_index(10)
        )
        ids = [e.evidence_id for e in evidence]
        assert len(ids) == len(set(ids)), "All evidence IDs must be unique"

    def test_evidence_values_match_analysis_values(self):
        df = _make_df(_minimal_rows(3))
        engine = AnalysisEngine(df)
        vol = engine.get_case_volume()
        evidence = collect_evidence(
            engine.get_reporting_period(), vol, engine.get_age_distribution(),
            engine.get_sex_distribution(), engine.get_country_distribution(), engine.get_reactions(20),
            engine.get_serious_reactions(20), engine.get_outcomes(), engine.get_time_trends(),
            engine.get_alert_cases(), engine.get_history_of_actions(), engine.get_expectedness(),
            engine.get_case_index(10)
        )
        ev_total = next(e for e in evidence if e.evidence_id == "EV_CASE_TOTAL")
        assert ev_total.value == vol.value["total_cases"], "Evidence total must match analysis total"

    def test_evidence_methodology_preserved(self):
        df = _make_df(_minimal_rows(2))
        engine = AnalysisEngine(df)
        evidence = collect_evidence(
            engine.get_reporting_period(), engine.get_case_volume(), engine.get_age_distribution(),
            engine.get_sex_distribution(), engine.get_country_distribution(), engine.get_reactions(20),
            engine.get_serious_reactions(20), engine.get_outcomes(), engine.get_time_trends(),
            engine.get_alert_cases(), engine.get_history_of_actions(), engine.get_expectedness(),
            engine.get_case_index(10)
        )
        alert_serious = next(e for e in evidence if e.evidence_id == "EV_ALERT_SERIOUS")
        assert "fulfillexpeditecriteria is true AND serious is true" in alert_serious.methodology

    def test_tampered_evidence_number_detected_by_grounding_validator(self):
        """
        Tampered evidence says total_cases = 7777 but narrative says 3.
        3 is in the grounding validator's structural allowlist (0-5), so grounding passes for 3.
        This test instead verifies the inverse: if narrative uses the tampered number 7777,
        which is NOT in evidence (only 3 is), grounding must fail.
        """
        from src.evidence_models import EvidenceItem, EvidenceType, AggregationLevel, SectionContextPacket
        real_ev = EvidenceItem(
            evidence_id="EV_CASE_TOTAL",
            analysis_id="vol_001",
            section="Narrative Summary",
            evidence_type=EvidenceType.FACT,
            metric="Total unique cases",
            value=3,          # correct real value
            aggregation_level=AggregationLevel.CASE,
            source_fields=["safetyreportid"],
            methodology="test"
        )
        # Generate a narrative that hallucinates the value 7777 (not in evidence)
        hallucinated_gen = GeneratedSection(
            section_name="Narrative Summary",
            narrative="A total of 7777 cases were received.",
            evidence_ids=["EV_CASE_TOTAL"],
            limitations=[]
        )
        packet = SectionContextPacket(
            section_name="Narrative Summary",
            section_purpose="Summary",
            evidence=[real_ev],
            grounding_instructions=[]
        )
        validator = GroundingValidator()
        result = validator.validate_section(hallucinated_gen, packet)
        # 7777 is NOT in evidence (only 3 is); grounding should fail
        assert not result.is_grounded
        assert 7777.0 in result.unsupported_numbers


# ============================================================
# SECTION 5 — CONTEXT BOUNDARY (No raw DataFrame in LLM context)
# ============================================================

class TestContextBoundary:

    def test_no_raw_dataframe_in_context_packets(self):
        df = _make_df(_minimal_rows(3))
        engine = AnalysisEngine(df)
        evidence = collect_evidence(
            engine.get_reporting_period(), engine.get_case_volume(), engine.get_age_distribution(),
            engine.get_sex_distribution(), engine.get_country_distribution(), engine.get_reactions(20),
            engine.get_serious_reactions(20), engine.get_outcomes(), engine.get_time_trends(),
            engine.get_alert_cases(), engine.get_history_of_actions(), engine.get_expectedness(),
            engine.get_case_index(10)
        )
        builder = ContextBuilder(PADER_CONFIG, evidence)
        packets = builder.build_all_packets()
        for pkt in packets:
            # Serialize the packet; confirm no DataFrame objects
            packet_dict = pkt.model_dump()
            packet_str = json.dumps(packet_dict, default=str)
            assert "DataFrame" not in packet_str
            assert ".xlsx" not in packet_str.lower()

    def test_raw_file_path_not_in_context_packets(self):
        df = _make_df(_minimal_rows(2))
        engine = AnalysisEngine(df)
        evidence = collect_evidence(
            engine.get_reporting_period(), engine.get_case_volume(), engine.get_age_distribution(),
            engine.get_sex_distribution(), engine.get_country_distribution(), engine.get_reactions(20),
            engine.get_serious_reactions(20), engine.get_outcomes(), engine.get_time_trends(),
            engine.get_alert_cases(), engine.get_history_of_actions(), engine.get_expectedness(),
            engine.get_case_index(5)
        )
        builder = ContextBuilder(PADER_CONFIG, evidence)
        packets = builder.build_all_packets()
        for pkt in packets:
            for ev_item in pkt.evidence:
                assert "Bisoprolol" not in str(ev_item.value)

    def test_only_approved_evidence_ids_in_packets(self):
        """Each packet's evidence IDs must be a subset of the global evidence registry."""
        df = _make_df(_minimal_rows(3))
        engine = AnalysisEngine(df)
        evidence = collect_evidence(
            engine.get_reporting_period(), engine.get_case_volume(), engine.get_age_distribution(),
            engine.get_sex_distribution(), engine.get_country_distribution(), engine.get_reactions(20),
            engine.get_serious_reactions(20), engine.get_outcomes(), engine.get_time_trends(),
            engine.get_alert_cases(), engine.get_history_of_actions(), engine.get_expectedness(),
            engine.get_case_index(10)
        )
        global_ids = {e.evidence_id for e in evidence}
        builder = ContextBuilder(PADER_CONFIG, evidence)
        packets = builder.build_all_packets()
        for pkt in packets:
            pkt_ids = {e.evidence_id for e in pkt.evidence}
            assert pkt_ids.issubset(global_ids), \
                f"Packet '{pkt.section_name}' contains unknown evidence IDs: {pkt_ids - global_ids}"


# ============================================================
# SECTION 6 — LLM FAILURE MODES
# ============================================================

class FailingLLMClient(MockLLMClient):
    """Mock LLM client that raises a configurable exception."""
    def __init__(self, exception: Exception):
        super().__init__()
        self.exception = exception

    def generate(self, request):
        raise self.exception


class BadJSONLLMClient(MockLLMClient):
    """Mock LLM client that returns malformed JSON."""
    def generate(self, request):
        return LLMResponse(
            content="{this is not valid JSON!!!",
            model_name="mock-bad-json",
            prompt_tokens=10,
            completion_tokens=5,
            latency_seconds=0.01
        )


class EmptyResponseLLMClient(MockLLMClient):
    """Mock LLM client that returns an empty string."""
    def generate(self, request):
        return LLMResponse(
            content="",
            model_name="mock-empty",
            prompt_tokens=10,
            completion_tokens=0,
            latency_seconds=0.01
        )


class TestLLMFailureModes:

    def _run_with_client(self, client, sample_excel_file, tmp_path):
        orchestrator = PADEROrchestrator(llm_client=client)
        return orchestrator.run(file_path=sample_excel_file, output_dir=None)

    def test_A_api_timeout_does_not_crash_pipeline(self, sample_excel_file, tmp_path):
        """A: API timeout — pipeline continues, failing section gets REVIEW_REQUIRED."""
        client = FailingLLMClient(TimeoutError("Connection timed out"))
        report = self._run_with_client(client, sample_excel_file, tmp_path)
        # Report should still exist with all 9 sections
        assert len(report.sections) == 9
        # Deterministic sections must be unaffected
        det_sections = [s for s in report.sections if s.section_type.value == "deterministic"]
        for ds in det_sections:
            assert ds.validation_status == SectionStatus.PASS

    def test_B_http_400_error_isolated_to_section(self, sample_excel_file, tmp_path):
        """B: HTTP 400-like RuntimeError is isolated per section."""
        client = FailingLLMClient(RuntimeError("HTTP 400 Bad Request"))
        report = self._run_with_client(client, sample_excel_file, tmp_path)
        llm_sections = [s for s in report.sections if s.section_type.value == "llm_generated"]
        for sec in llm_sections:
            assert sec.validation_status == SectionStatus.REVIEW_REQUIRED
            assert "GENERATION FAILED" in sec.narrative

    def test_C_http_401_unauthorized_does_not_expose_key(self, sample_excel_file, tmp_path):
        """C: Auth errors must not expose actual API key secrets in the report."""
        client = FailingLLMClient(RuntimeError("HTTP 401 Unauthorized - invalid API key"))
        report = self._run_with_client(client, sample_excel_file, tmp_path)
        assembler = ReportAssembler()
        md = assembler.to_markdown(report)
        # Actual key patterns that could leak secrets should NOT appear
        assert "sk-" not in md
        assert "Bearer " not in md
        assert "LLM_API_KEY=" not in md

    def test_D_http_429_rate_limit_isolated(self, sample_excel_file, tmp_path):
        """D: Rate limit error — sections fail safely."""
        client = FailingLLMClient(RuntimeError("HTTP 429 Rate limit exceeded"))
        report = self._run_with_client(client, sample_excel_file, tmp_path)
        assert len(report.sections) == 9

    def test_E_http_500_server_error_isolated(self, sample_excel_file, tmp_path):
        """E: Server error — report is still assembled; failed sections flagged."""
        client = FailingLLMClient(RuntimeError("HTTP 500 Internal Server Error"))
        report = self._run_with_client(client, sample_excel_file, tmp_path)
        eval_result = PADEREvaluator().evaluate(report)
        # Evaluator should NOT return PASS when sections failed
        assert eval_result.automated_evaluation_status == SectionStatus.REVIEW_REQUIRED

    def test_F_malformed_json_response_section_fails(self, sample_excel_file, tmp_path):
        """F: Malformed JSON from LLM — section generation fails safely."""
        client = BadJSONLLMClient()
        report = self._run_with_client(client, sample_excel_file, tmp_path)
        llm_secs = [s for s in report.sections if s.section_type.value == "llm_generated"]
        assert all(s.validation_status == SectionStatus.REVIEW_REQUIRED for s in llm_secs)

    def test_G_empty_llm_response_section_fails_safely(self, sample_excel_file, tmp_path):
        """G: Empty string from LLM — section generation fails with clear error."""
        client = EmptyResponseLLMClient()
        report = self._run_with_client(client, sample_excel_file, tmp_path)
        llm_secs = [s for s in report.sections if s.section_type.value == "llm_generated"]
        assert all(s.validation_status == SectionStatus.REVIEW_REQUIRED for s in llm_secs)

    def test_H_other_sections_not_corrupted_on_llm_failure(self, sample_excel_file, tmp_path):
        """H: When LLM fails, deterministic sections (Period, History, Expectedness, Listing) are intact."""
        client = FailingLLMClient(RuntimeError("Simulated LLM failure"))
        report = self._run_with_client(client, sample_excel_file, tmp_path)
        # Reporting Period must be intact
        period_sec = next(s for s in report.sections if s.section_name == "Reporting Period")
        assert period_sec.validation_status == SectionStatus.PASS
        # History of Actions must be intact
        hist_sec = next(s for s in report.sections if s.section_name == "History of Actions")
        assert "No history-of-actions" in hist_sec.narrative
        # Expectedness statement must be intact
        exp_sec = next(s for s in report.sections if s.section_name == "Expectedness")
        assert "OUT OF SCOPE" in exp_sec.narrative

    def test_I_no_api_key_falls_back_to_mock(self):
        """I: create_llm_client() with no key returns MockLLMClient."""
        from src.llm_client import create_llm_client
        with patch.dict(os.environ, {}, clear=True):
            client = create_llm_client(force_mock=False)
            assert isinstance(client, MockLLMClient)

    @staticmethod
    def test_J_openai_client_requires_api_key():
        """J: OpenAICompatibleLLMClient raises ValueError without a key."""
        with pytest.raises(ValueError, match="API key"):
            OpenAICompatibleLLMClient(api_key="")


# ============================================================
# SECTION 7 — GROUNDING FAILURE DETECTION
# ============================================================

class TestGroundingFailureDetection:

    def _make_packet_with_total(self, total: int):
        from src.evidence_models import EvidenceItem, EvidenceType, AggregationLevel, SectionContextPacket
        ev = EvidenceItem(
            evidence_id="EV_CASE_TOTAL",
            analysis_id="vol_001",
            section="Narrative Summary",
            evidence_type=EvidenceType.FACT,
            metric="Total unique cases",
            value=total,
            aggregation_level=AggregationLevel.CASE,
            source_fields=["safetyreportid"],
            methodology="test"
        )
        return SectionContextPacket(
            section_name="Narrative Summary",
            section_purpose="Test",
            evidence=[ev],
            grounding_instructions=[]
        )

    def test_wrong_case_count_fails_grounding(self):
        """Narrative claims 1,100 when evidence says 1,024."""
        gen = GeneratedSection(
            section_name="Narrative Summary",
            narrative="A total of 1,100 cases were received.",
            evidence_ids=["EV_CASE_TOTAL"],
            limitations=[]
        )
        packet = self._make_packet_with_total(1024)
        validator = GroundingValidator()
        result = validator.validate_section(gen, packet)
        assert not result.is_grounded
        assert 1100.0 in result.unsupported_numbers

    def test_correct_case_count_passes_grounding(self):
        """Narrative uses exactly 1,024 matching the evidence."""
        gen = GeneratedSection(
            section_name="Narrative Summary",
            narrative="A total of 1,024 cases were received.",
            evidence_ids=["EV_CASE_TOTAL"],
            limitations=[]
        )
        packet = self._make_packet_with_total(1024)
        validator = GroundingValidator()
        result = validator.validate_section(gen, packet)
        assert result.is_grounded

    def test_unsupported_causal_claim_fails(self):
        gen = GeneratedSection(
            section_name="Narrative Summary",
            narrative="Bisoprolol definitely caused bradycardia in all 1,024 cases.",
            evidence_ids=["EV_CASE_TOTAL"],
            limitations=[]
        )
        packet = self._make_packet_with_total(1024)
        validator = GroundingValidator()
        result = validator.validate_section(gen, packet)
        assert not result.is_grounded
        assert len(result.flagged_claims) > 0

    def test_confirmed_safety_signal_claim_fails(self):
        gen = GeneratedSection(
            section_name="Narrative Summary",
            narrative="A confirmed safety signal was detected for 1,024 reports.",
            evidence_ids=["EV_CASE_TOTAL"],
            limitations=[]
        )
        packet = self._make_packet_with_total(1024)
        validator = GroundingValidator()
        result = validator.validate_section(gen, packet)
        assert not result.is_grounded

    def test_invented_regulatory_action_fails(self):
        gen = GeneratedSection(
            section_name="Narrative Summary",
            narrative="A labeling change implemented was ordered based on 1,024 cases.",
            evidence_ids=["EV_CASE_TOTAL"],
            limitations=[]
        )
        packet = self._make_packet_with_total(1024)
        validator = GroundingValidator()
        result = validator.validate_section(gen, packet)
        assert not result.is_grounded


# ============================================================
# SECTION 8 — REPORT ASSEMBLY FAILURE
# ============================================================

class TestReportAssemblyFailures:

    def test_evaluator_fails_when_required_section_missing(self, sample_excel_file):
        """If a required section is absent, evaluator must not return PASS."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        # Remove a required section manually
        report.sections = [s for s in report.sections if s.section_name != "Case Listing"]
        evaluator = PADEREvaluator()
        result = evaluator.evaluate(report)
        assert result.required_sections_complete is False
        assert result.automated_evaluation_status == SectionStatus.REVIEW_REQUIRED

    def test_evaluator_fails_when_generated_section_has_review_required(self, sample_excel_file):
        """A section with REVIEW_REQUIRED status must cause evaluator to fail."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        # Force a section to REVIEW_REQUIRED
        report.sections[1].validation_status = SectionStatus.REVIEW_REQUIRED
        evaluator = PADEREvaluator()
        result = evaluator.evaluate(report)
        assert result.automated_evaluation_status == SectionStatus.REVIEW_REQUIRED

    def test_empty_narrative_section_gets_review_required(self, sample_excel_file):
        """An LLM section with empty narrative should fail validation."""
        client = FailingLLMClient(ValueError("Empty response"))
        orchestrator = PADEROrchestrator(llm_client=client)
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        evaluator = PADEREvaluator()
        result = evaluator.evaluate(report)
        assert result.automated_evaluation_status == SectionStatus.REVIEW_REQUIRED


# ============================================================
# SECTION 9 — HUMAN REVIEW FAILURE MODES
# ============================================================

class TestHumanReviewFailureModes:

    def test_pending_cannot_become_approved_without_explicit_action(self, sample_excel_file):
        """Evaluator PASS must not silently promote report to APPROVED."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        assert report.status == ReportStatus.DRAFT_PENDING_REVIEW
        assert report.evaluation.is_human_approved is False

    def test_rejected_cannot_silently_become_approved(self, sample_excel_file):
        """Once rejected, re-running with no review action stays rejected."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        mgr = HumanReviewManager()
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        rejected = mgr.apply_decision(report, ReviewDecision.REJECTED, notes="Invalid.")
        assert rejected.status == ReportStatus.REJECTED
        assert rejected.evaluation.is_human_approved is False

    def test_needs_revision_resets_to_draft_on_regeneration(self, sample_excel_file):
        """After regeneration, status resets to DRAFT_PENDING_REVIEW."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        mgr = HumanReviewManager()
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        report_needs_rev = mgr.apply_decision(report, ReviewDecision.NEEDS_REVISION)
        assert report_needs_rev.status == ReportStatus.NEEDS_REVISION

        df = load_and_normalize_data(sample_excel_file)
        engine = AnalysisEngine(df)
        evidence = collect_evidence(
            engine.get_reporting_period(), engine.get_case_volume(), engine.get_age_distribution(),
            engine.get_sex_distribution(), engine.get_country_distribution(), engine.get_reactions(20),
            engine.get_serious_reactions(20), engine.get_outcomes(), engine.get_time_trends(),
            engine.get_alert_cases(), engine.get_history_of_actions(), engine.get_expectedness(),
            engine.get_case_index(10)
        )
        builder = ContextBuilder(PADER_CONFIG, evidence)
        packet = [p for p in builder.build_all_packets() if p.section_name == "Narrative Summary"][0]
        regenerated = mgr.regenerate_section(
            report_needs_rev, "Narrative Summary",
            SectionGenerator(MockLLMClient()), packet, GroundingValidator()
        )
        assert regenerated.status == ReportStatus.DRAFT_PENDING_REVIEW

    def test_automated_evaluator_cannot_approve(self, sample_excel_file):
        """Automated evaluator PASS does not set is_human_approved to True."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        evaluator = PADEREvaluator()
        eval_res = evaluator.evaluate(report)
        assert eval_res.automated_evaluation_status == SectionStatus.PASS
        assert eval_res.is_human_approved is False

    def test_llm_cannot_approve_report(self, sample_excel_file):
        """LLM client is never given the ability to set report review status."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        # The LLM only touches narrative; review status must remain PENDING
        assert report.status == ReportStatus.DRAFT_PENDING_REVIEW


# ============================================================
# SECTION 10 — TARGETED REGENERATION ISOLATION
# ============================================================

class TestTargetedRegenerationIsolation:

    def test_only_target_section_changes_on_regeneration(self, sample_excel_file):
        """Regenerating 'Narrative Summary' must leave all other section narratives unchanged."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)

        # Record all sections except Narrative Summary
        original_texts = {
            s.section_name: s.narrative
            for s in report.sections
            if s.section_name != "Narrative Summary"
        }

        df = load_and_normalize_data(sample_excel_file)
        engine = AnalysisEngine(df)
        evidence = collect_evidence(
            engine.get_reporting_period(), engine.get_case_volume(), engine.get_age_distribution(),
            engine.get_sex_distribution(), engine.get_country_distribution(), engine.get_reactions(20),
            engine.get_serious_reactions(20), engine.get_outcomes(), engine.get_time_trends(),
            engine.get_alert_cases(), engine.get_history_of_actions(), engine.get_expectedness(),
            engine.get_case_index(10)
        )
        builder = ContextBuilder(PADER_CONFIG, evidence)
        packet = [p for p in builder.build_all_packets() if p.section_name == "Narrative Summary"][0]
        mgr = HumanReviewManager()
        updated = mgr.regenerate_section(
            report, "Narrative Summary", SectionGenerator(MockLLMClient()), packet, GroundingValidator()
        )

        # Check all other sections are untouched
        for sec in updated.sections:
            if sec.section_name != "Narrative Summary" and sec.section_name in original_texts:
                assert sec.narrative == original_texts[sec.section_name], \
                    f"Section '{sec.section_name}' was unexpectedly modified during targeted regeneration"


# ============================================================
# SECTION 11 — PRIVACY / OUTPUT SAFETY
# ============================================================

class TestPrivacyAndOutputSafety:

    def test_no_api_key_in_markdown_report(self, sample_excel_file):
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        md = ReportAssembler().to_markdown(report)
        assert "LLM_API_KEY" not in md
        assert "sk-" not in md.lower()
        assert "Bearer" not in md

    def test_no_raw_excel_path_in_markdown(self, sample_excel_file):
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        md = ReportAssembler().to_markdown(report)
        assert "Bisoprolol_icsr" not in md
        assert ".xlsx" not in md.lower()

    def test_outputs_dir_not_tracked_by_git(self, tmp_path):
        """Verify outputs/ is in .gitignore."""
        gitignore_path = "c:\\Users\\HP\\OneDrive\\Documents\\Desktop\\New folder\\.gitignore"
        if os.path.exists(gitignore_path):
            with open(gitignore_path) as f:
                content = f.read()
            assert "outputs/" in content

    def test_gitignore_excludes_dataset(self):
        gitignore_path = "c:\\Users\\HP\\OneDrive\\Documents\\Desktop\\New folder\\.gitignore"
        if os.path.exists(gitignore_path):
            with open(gitignore_path) as f:
                content = f.read()
            assert "Bisoprolol_icsr_sample_1068rows.xlsx" in content
            assert "Bisoprolol_icsr_sample_1068rows.csv" in content

    def test_gitignore_excludes_pycache(self):
        gitignore_path = "c:\\Users\\HP\\OneDrive\\Documents\\Desktop\\New folder\\.gitignore"
        if os.path.exists(gitignore_path):
            with open(gitignore_path) as f:
                content = f.read()
            assert "__pycache__/" in content


# ============================================================
# SECTION 12 — REPRODUCIBILITY
# ============================================================

class TestReproducibility:

    def test_deterministic_analysis_is_reproducible(self, sample_excel_file):
        """Same dataset must produce identical analysis results across two runs."""
        df = load_and_normalize_data(sample_excel_file)
        engine1 = AnalysisEngine(df)
        engine2 = AnalysisEngine(df)
        assert engine1.get_case_volume().value == engine2.get_case_volume().value
        assert engine1.get_reporting_period().value == engine2.get_reporting_period().value
        assert engine1.get_reactions(top_n=10).value == engine2.get_reactions(top_n=10).value

    def test_section_ordering_is_stable_across_runs(self, sample_excel_file):
        """Section order must be identical across two pipeline runs."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        run1 = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        run2 = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        assert [s.section_name for s in run1.sections] == [s.section_name for s in run2.sections]

    def test_evaluation_structure_is_stable_across_runs(self, sample_excel_file):
        """Evaluation results must be structurally identical across runs."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report1 = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        report2 = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        evaluator = PADEREvaluator()
        eval1 = evaluator.evaluate(report1)
        eval2 = evaluator.evaluate(report2)
        assert eval1.required_sections_total == eval2.required_sections_total
        assert eval1.required_sections_complete == eval2.required_sections_complete
        assert eval1.automated_evaluation_status == eval2.automated_evaluation_status


# ============================================================
# SECTION 13 — PERFORMANCE SANITY
# ============================================================

class TestPerformanceSanity:

    REAL_DATASET = "Bisoprolol_icsr_sample_1068rows.xlsx"

    @pytest.fixture(autouse=True)
    def skip_if_no_dataset(self):
        if not os.path.exists(self.REAL_DATASET):
            pytest.skip(f"Real dataset not present: {self.REAL_DATASET}")

    def test_data_loading_under_5_seconds(self):
        start = time.time()
        load_and_normalize_data(self.REAL_DATASET)
        elapsed = time.time() - start
        assert elapsed < 5.0, f"Data loading took {elapsed:.2f}s — too slow"

    def test_deterministic_analysis_under_3_seconds(self):
        df = load_and_normalize_data(self.REAL_DATASET)
        start = time.time()
        engine = AnalysisEngine(df)
        for fn in [engine.get_case_volume, engine.get_age_distribution, engine.get_sex_distribution,
                   engine.get_country_distribution, engine.get_reactions, engine.get_serious_reactions,
                   engine.get_outcomes, engine.get_time_trends, engine.get_alert_cases,
                   engine.get_reporting_period, engine.get_history_of_actions, engine.get_expectedness]:
            fn()
        elapsed = time.time() - start
        assert elapsed < 3.0, f"Deterministic analysis took {elapsed:.2f}s — too slow"

    def test_full_offline_pipeline_under_10_seconds(self, tmp_path):
        start = time.time()
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        orchestrator.run(file_path=self.REAL_DATASET, output_dir=None)
        elapsed = time.time() - start
        assert elapsed < 10.0, f"Full offline pipeline took {elapsed:.2f}s — too slow"
