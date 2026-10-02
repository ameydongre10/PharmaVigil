"""
Integration and regression tests for Phase 5 End-to-End PADER Pipeline, Assembly, Evaluation, and Human Review.
All tests run offline using in-memory mock datasets and MockLLMClient.
"""

import os
import json
import pytest
import pandas as pd
from src.data_loader import load_and_normalize_data
from src.orchestrator import PADEROrchestrator
from src.llm_client import MockLLMClient
from src.report_models import (
    PADERReport, ReportMetadata, SectionOutput, SectionType, SectionStatus, ReviewDecision, ReportStatus
)
from src.report_assembler import ReportAssembler
from src.evaluator import PADEREvaluator
from src.human_review import HumanReviewManager
from src.context_builder import ContextBuilder
from src.section_generator import SectionGenerator
from src.grounding_validator import GroundingValidator
from src.report_config import PADER_CONFIG
from src.evidence_collector import collect_evidence
from src.analysis_engine import AnalysisEngine


@pytest.fixture
def sample_excel_file(tmp_path):
    """Creates a small mock Excel file for testing."""
    data = [
        {"safetyreportid": "C1", "receivedate": "20250101", "serious": "1", "fulfillexpeditecriteria": "yes",
         "patient_patientonsetage": 68, "patient_patientsex": "female", "occurcountry": "GB",
         "patient_reaction_reactionmeddrapt": "Acute kidney injury", "patient_reaction_reactionoutcome": "recovered"},
        {"safetyreportid": "C1", "receivedate": "20250101", "serious": "1", "fulfillexpeditecriteria": "yes",
         "patient_patientonsetage": 68, "patient_patientsex": "female", "occurcountry": "GB",
         "patient_reaction_reactionmeddrapt": "Drug ineffective", "patient_reaction_reactionoutcome": "unknown"},
        {"safetyreportid": "C2", "receivedate": "20250215", "serious": "2", "fulfillexpeditecriteria": "no",
         "patient_patientonsetage": 45, "patient_patientsex": "male", "occurcountry": "FR",
         "patient_reaction_reactionmeddrapt": "Rash", "patient_reaction_reactionoutcome": "recovering"},
        {"safetyreportid": "C3", "receivedate": "20250320", "serious": "yes", "fulfillexpeditecriteria": "yes",
         "patient_patientonsetage": 72, "patient_patientsex": "male", "occurcountry": "US",
         "patient_reaction_reactionmeddrapt": "Acute kidney injury", "patient_reaction_reactionoutcome": "fatal"},
    ]
    file_path = str(tmp_path / "mock_dataset.xlsx")
    pd.DataFrame(data).to_excel(file_path, index=False)
    return file_path


class TestEndToEndPipeline:
    def test_default_pipeline_starts_as_pending_review(self, sample_excel_file, tmp_path):
        """Rule A: A newly generated report starts as DRAFT_PENDING_REVIEW."""
        out_dir = str(tmp_path / "outputs")
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())

        report = orchestrator.run(
            file_path=sample_excel_file,
            output_dir=out_dir
        )

        assert isinstance(report, PADERReport)
        assert report.status == ReportStatus.DRAFT_PENDING_REVIEW
        assert report.evaluation.is_human_approved is False

    def test_evaluator_pass_does_not_auto_approve(self, sample_excel_file):
        """Rule B: Automated evaluator PASS does NOT change human review status to APPROVED."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)

        assert report.evaluation.automated_evaluation_status == SectionStatus.PASS
        assert report.status == ReportStatus.DRAFT_PENDING_REVIEW
        assert report.evaluation.is_human_approved is False

    def test_section_ordering_and_types(self, sample_excel_file):
        """Verify section ordering and separation of required sections from limitation notice."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)

        expected_sections = [
            ("Reporting Period", SectionType.DETERMINISTIC, True),
            ("Narrative Summary", SectionType.LLM_GENERATED, True),
            ("Summary Analysis of Cases", SectionType.LLM_GENERATED, True),
            ("Reaction Analysis", SectionType.LLM_GENERATED, True),
            ("15-Day Alert Reports", SectionType.LLM_GENERATED, True),
            ("Trends and Important Observations", SectionType.LLM_GENERATED, True),
            ("History of Actions", SectionType.DETERMINISTIC, True),
            ("Expectedness", SectionType.LIMITATION_STATEMENT, False),
            ("Case Listing", SectionType.DETERMINISTIC, True)
        ]

        assert len(report.sections) == len(expected_sections)
        for idx, (exp_name, exp_type, exp_req) in enumerate(expected_sections):
            actual_sec = report.sections[idx]
            assert actual_sec.section_name == exp_name
            assert actual_sec.section_type == exp_type
            assert actual_sec.is_required_by_assignment == exp_req


class TestReportAssembler:
    def test_markdown_rendering(self, sample_excel_file):
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)

        assembler = ReportAssembler()
        md = assembler.to_markdown(report)

        assert "# Periodic Adverse Drug Experience Report (PADER)" in md
        assert "## Table of Contents" in md
        assert "## 1. Reporting Period" in md
        assert "## 2. Narrative Summary" in md
        assert "## 7. History of Actions" in md
        assert "## Appendix: Expectedness (Limitation Notice)" in md
        assert "No history-of-actions data was provided." in md
        assert "OUT OF SCOPE / NOT DETERMINABLE FROM SUPPLIED DATA" in md


class TestHumanReviewWorkflow:
    def test_explicit_human_approval(self, sample_excel_file):
        """Rule C: Only an explicit human-review action can set HUMAN_APPROVED."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        mgr = HumanReviewManager()

        base_report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        assert base_report.status == ReportStatus.DRAFT_PENDING_REVIEW

        approved_report = mgr.apply_decision(
            report=base_report,
            decision=ReviewDecision.APPROVED,
            reviewer_name="Dr. J. Doe, Medical Reviewer",
            notes="All tables verified."
        )

        assert approved_report.status == ReportStatus.HUMAN_APPROVED
        assert approved_report.evaluation.is_human_approved is True
        assert approved_report.review_record.is_simulated is False

    def test_needs_revision_and_rejected_states(self, sample_excel_file):
        """Rules D & E: Reviewer can set NEEDS_REVISION or REJECTED."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        mgr = HumanReviewManager()

        base_report = orchestrator.run(file_path=sample_excel_file, output_dir=None)

        rev_report = mgr.apply_decision(base_report, ReviewDecision.NEEDS_REVISION, notes="Revise Summary.")
        assert rev_report.status == ReportStatus.NEEDS_REVISION
        assert rev_report.evaluation.is_human_approved is False

        rej_report = mgr.apply_decision(base_report, ReviewDecision.REJECTED, notes="Invalid data source.")
        assert rej_report.status == ReportStatus.REJECTED
        assert rej_report.evaluation.is_human_approved is False

    def test_simulated_review_is_distinguishable(self, sample_excel_file):
        """Rule F: Simulated approval fixture is distinguishable from actual human approval."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        mgr = HumanReviewManager()

        base_report = orchestrator.run(file_path=sample_excel_file, output_dir=None)
        sim_report = mgr.apply_decision(
            base_report,
            decision=ReviewDecision.SIMULATED_APPROVED,
            reviewer_name="Automated Test Runner",
            is_simulated=True
        )

        assert sim_report.status == ReportStatus.SIMULATED_APPROVED
        assert sim_report.review_record.is_simulated is True
        assert sim_report.evaluation.is_human_approved is False # Not counted as real human approval

    def test_single_section_regeneration(self, sample_excel_file):
        """Regenerating a single section resets status to DRAFT_PENDING_REVIEW."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)

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

        generator = SectionGenerator(MockLLMClient())
        validator = GroundingValidator()
        mgr = HumanReviewManager()

        updated_report = mgr.regenerate_section(
            report=report,
            section_name="Narrative Summary",
            generator=generator,
            context_packet=packet,
            validator=validator
        )

        assert updated_report.status == ReportStatus.DRAFT_PENDING_REVIEW
        assert updated_report.sections[0].section_name == "Reporting Period" # other sections intact


class TestEvaluatorAccuracy:
    def test_evaluator_completeness_and_expectedness(self, sample_excel_file):
        """Rules G & H: Completeness checks 8 required sections and tracks Expectedness as limitation."""
        orchestrator = PADEROrchestrator(llm_client=MockLLMClient())
        report = orchestrator.run(file_path=sample_excel_file, output_dir=None)

        evaluator = PADEREvaluator()
        eval_res = evaluator.evaluate(report)

        assert eval_res.required_sections_total == 8
        assert eval_res.required_sections_present == 8
        assert eval_res.required_sections_complete is True
        assert eval_res.additional_limitation_sections_present == ["Expectedness"]
        assert eval_res.automated_evaluation_status == SectionStatus.PASS
