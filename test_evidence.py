"""
Tests for the Phase 3 evidence and context engineering layer.

All tests use in-memory mock AnalysisResult fixtures — the real dataset
is never imported or committed.
"""

import pytest
from src.models import AnalysisResult
from src.evidence_models import (
    EvidenceItem, EvidenceType, AggregationLevel, SectionContextPacket,
)
from src.evidence_collector import collect_evidence
from src.context_builder import ContextBuilder
from src.report_config import PADER_CONFIG


# ---------------------------------------------------------------------------
# Fixtures — minimal Phase 2 AnalysisResult mocks
# ---------------------------------------------------------------------------

def _ar(analysis_id, name, value, **kw):
    """Shorthand mock AnalysisResult."""
    return AnalysisResult(
        analysis_id=analysis_id,
        analysis_name=name,
        metric=kw.get("metric", "mock"),
        value=value,
        methodology=kw.get("methodology", "mock"),
        case_level=kw.get("case_level", True),
        source_fields=kw.get("source_fields", []),
    )


@pytest.fixture
def mock_analysis_results():
    """Return a dict of mock AnalysisResults keyed by analysis_id."""
    return {
        "period": _ar("period_001", "Reporting Period",
                       {"start_date": "2024-12-27", "end_date": "2025-12-26"}),
        "volume": _ar("vol_001", "Case Volume",
                       {"total_cases": 10, "serious_cases": 9,
                        "non_serious_cases": 1, "serious_pct": 90.0,
                        "non_serious_pct": 10.0}),
        "age": _ar("demo_age_001", "Age Distribution",
                    {"counts": {"65+": 6, "18-64": 3, "Unknown": 1},
                     "percentages": {"65+": 60, "18-64": 30, "Unknown": 10}}),
        "sex": _ar("demo_sex_001", "Sex Distribution",
                    {"counts": {"Female": 5, "Male": 5},
                     "percentages": {"Female": 50, "Male": 50}}),
        "country": _ar("demo_country_001", "Country",
                        {"counts": {"US": 5, "UK": 3, "FR": 2},
                         "percentages": {"US": 50, "UK": 30, "FR": 20}}),
        "reactions": _ar("rx_001", "Top Reactions",
                          {"Headache": 5, "Nausea": 3}, case_level=False),
        "serious_reactions": _ar("rx_002", "Top Serious Reactions",
                                  {"Headache": 4, "Nausea": 2}, case_level=False),
        "outcomes": _ar("out_001", "Outcomes", {"recovered": 6, "unknown": 4},
                         case_level=False),
        "trends": _ar("trend_001", "Monthly Trends",
                       {"2025-01": 3, "2025-02": 4, "2025-03": 3}),
        "alerts": _ar("alert_001", "Alerts",
                       {"total_alerts": 9, "serious_alerts": 9}),
        "history": _ar("hist_001", "History",
                        "No history-of-actions data was provided.",
                        case_level=False),
        "expectedness": _ar("exp_001", "Expectedness",
                             "OUT OF SCOPE / NOT DETERMINABLE FROM SUPPLIED DATA",
                             case_level=False),
        "case_index": _ar("idx_001", "Case Index",
                           [{"safetyreportid": "C1", "reactions": "Headache",
                             "serious": "Yes", "date": "20250101", "country": "US"}]),
    }


@pytest.fixture
def all_evidence(mock_analysis_results):
    r = mock_analysis_results
    return collect_evidence(
        period=r["period"], volume=r["volume"], age=r["age"],
        sex=r["sex"], country=r["country"], reactions=r["reactions"],
        serious_reactions=r["serious_reactions"], outcomes=r["outcomes"],
        trends=r["trends"], alerts=r["alerts"], history=r["history"],
        expectedness=r["expectedness"], case_index=r["case_index"],
    )


# ---------------------------------------------------------------------------
# Evidence schema tests
# ---------------------------------------------------------------------------

class TestEvidenceSchema:
    def test_evidence_items_are_created(self, all_evidence):
        assert len(all_evidence) > 0
        assert all(isinstance(e, EvidenceItem) for e in all_evidence)

    def test_evidence_ids_unique(self, all_evidence):
        ids = [e.evidence_id for e in all_evidence]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_every_item_has_analysis_id(self, all_evidence):
        for e in all_evidence:
            assert e.analysis_id, f"{e.evidence_id} missing analysis_id"

    def test_fact_vs_observation_vs_not_available(self, all_evidence):
        types_found = {e.evidence_type for e in all_evidence}
        assert EvidenceType.FACT in types_found
        assert EvidenceType.NOT_AVAILABLE in types_found

    def test_history_is_not_available(self, all_evidence):
        hist = [e for e in all_evidence if e.evidence_id == "EV_HISTORY"]
        assert len(hist) == 1
        assert hist[0].evidence_type == EvidenceType.NOT_AVAILABLE
        assert "no history" in str(hist[0].value).lower()

    def test_expectedness_is_not_available(self, all_evidence):
        exp = [e for e in all_evidence if e.evidence_id == "EV_EXPECTEDNESS"]
        assert len(exp) == 1
        assert exp[0].evidence_type == EvidenceType.NOT_AVAILABLE
        assert "out of scope" in str(exp[0].value).lower()


# ---------------------------------------------------------------------------
# Evidence-to-analysis traceability tests
# ---------------------------------------------------------------------------

class TestTraceability:
    def test_case_total_traces_to_vol_001(self, all_evidence):
        ev = [e for e in all_evidence if e.evidence_id == "EV_CASE_TOTAL"]
        assert len(ev) == 1
        assert ev[0].analysis_id == "vol_001"
        assert ev[0].value == 10

    def test_period_traces_to_period_001(self, all_evidence):
        starts = [e for e in all_evidence if e.evidence_id == "EV_PERIOD_START"]
        assert len(starts) == 1
        assert starts[0].analysis_id == "period_001"
        assert starts[0].value == "2024-12-27"

    def test_most_common_reaction_observation(self, all_evidence):
        obs = [e for e in all_evidence if e.evidence_id == "EV_MOST_COMMON_REACTION"]
        assert len(obs) == 1
        assert obs[0].evidence_type == EvidenceType.OBSERVATION
        assert obs[0].value["reaction"] == "Headache"
        assert obs[0].analysis_id == "rx_001"

    def test_alert_serious_methodology_and_source_fields(self, all_evidence):
        ev = [e for e in all_evidence if e.evidence_id == "EV_ALERT_SERIOUS"]
        assert len(ev) == 1
        assert ev[0].analysis_id == "alert_001"
        assert ev[0].methodology == "Count of cases where fulfillexpeditecriteria is true AND serious is true"
        assert set(ev[0].source_fields) == {"fulfillexpeditecriteria", "serious"}



# ---------------------------------------------------------------------------
# Context builder & section dependency tests
# ---------------------------------------------------------------------------

class TestContextBuilder:
    def test_validation_passes(self, all_evidence):
        builder = ContextBuilder(PADER_CONFIG, all_evidence)
        errors = builder.validate()
        assert errors == [], f"Validation errors: {errors}"

    def test_all_packets_built(self, all_evidence):
        builder = ContextBuilder(PADER_CONFIG, all_evidence)
        packets = builder.build_all_packets()
        assert len(packets) == len(PADER_CONFIG.sections)
        for p in packets:
            assert isinstance(p, SectionContextPacket)

    def test_narrative_summary_gets_correct_evidence(self, all_evidence):
        builder = ContextBuilder(PADER_CONFIG, all_evidence)
        narrative_cfg = [s for s in PADER_CONFIG.sections
                         if s.section_name == "Narrative Summary"][0]
        packet = builder.build_section_packet(narrative_cfg)

        # Should contain evidence from period_001, vol_001, rx_001
        analysis_ids_in_packet = {e.analysis_id for e in packet.evidence}
        assert "period_001" in analysis_ids_in_packet
        assert "vol_001" in analysis_ids_in_packet
        assert "rx_001" in analysis_ids_in_packet
        # Should NOT contain unrelated evidence
        assert "idx_001" not in analysis_ids_in_packet
        assert "hist_001" not in analysis_ids_in_packet

    def test_case_listing_only_gets_index(self, all_evidence):
        builder = ContextBuilder(PADER_CONFIG, all_evidence)
        listing_cfg = [s for s in PADER_CONFIG.sections
                       if s.section_name == "Case Listing"][0]
        packet = builder.build_section_packet(listing_cfg)

        analysis_ids_in_packet = {e.analysis_id for e in packet.evidence}
        assert analysis_ids_in_packet == {"idx_001"}

    def test_history_section_gets_only_history(self, all_evidence):
        builder = ContextBuilder(PADER_CONFIG, all_evidence)
        hist_cfg = [s for s in PADER_CONFIG.sections
                    if s.section_name == "History of Actions"][0]
        packet = builder.build_section_packet(hist_cfg)

        assert len(packet.evidence) == 1
        assert packet.evidence[0].evidence_id == "EV_HISTORY"

    def test_context_packet_has_grounding_instructions(self, all_evidence):
        builder = ContextBuilder(PADER_CONFIG, all_evidence)
        packets = builder.build_all_packets()
        for p in packets:
            assert len(p.grounding_instructions) > 0
            assert any("ONLY" in i or "only" in i.lower()
                       for i in p.grounding_instructions)

    def test_no_raw_dataframe_in_packets(self, all_evidence):
        """Ensure no pandas DataFrame leaks into any context packet."""
        import pandas as pd
        builder = ContextBuilder(PADER_CONFIG, all_evidence)
        packets = builder.build_all_packets()
        for p in packets:
            for e in p.evidence:
                assert not isinstance(e.value, pd.DataFrame), \
                    f"Raw DataFrame found in {e.evidence_id}"

    def test_validation_catches_missing_analysis(self):
        """If evidence is missing a required analysis_id, validation fails."""
        incomplete_evidence = [
            EvidenceItem(
                evidence_id="EV_TEST",
                analysis_id="period_001",
                section="Reporting Period",
                metric="test",
                value="test",
                aggregation_level="case",
                methodology="test",
            )
        ]
        builder = ContextBuilder(PADER_CONFIG, incomplete_evidence)
        errors = builder.validate()
        assert len(errors) > 0
        assert any("vol_001" in e for e in errors)

    def test_validation_catches_duplicate_evidence_ids(self, all_evidence):
        """Duplicate evidence_ids should be flagged."""
        duped = all_evidence + [all_evidence[0]]
        builder = ContextBuilder(PADER_CONFIG, duped)
        errors = builder.validate()
        assert any("Duplicate" in e for e in errors)


# ---------------------------------------------------------------------------
# Report config tests
# ---------------------------------------------------------------------------

class TestReportConfig:
    def test_pader_has_expected_sections(self):
        names = {s.section_name for s in PADER_CONFIG.sections}
        assert "Narrative Summary" in names
        assert "Reaction Analysis" in names
        assert "Case Listing" in names
        assert "History of Actions" in names

    def test_every_section_has_required_ids(self):
        for sec in PADER_CONFIG.sections:
            assert len(sec.required_analysis_ids) > 0, \
                f"Section '{sec.section_name}' has no required_analysis_ids"
