"""
PADER Pipeline Orchestrator — coordinates data loading, deterministic analysis, evidence collection,
grounded LLM generation, report assembly, evaluation, and human review sign-off.
"""

import os
import json
from typing import Optional, Dict
from .data_loader import load_and_normalize_data, validate_data
from .analysis_engine import AnalysisEngine
from .models import AnalysisResult
from .evidence_collector import collect_evidence
from .context_builder import ContextBuilder
from .report_config import PADER_CONFIG
from .llm_client import LLMClient, create_llm_client
from .section_generator import SectionGenerator
from .grounding_validator import GroundingValidator
from .generation_models import GeneratedSection, ValidationResult
from .report_models import (
    PADERReport, ReportMetadata, ReviewDecision, ReportStatus
)
from .report_assembler import ReportAssembler
from .evaluator import PADEREvaluator
from .human_review import HumanReviewManager


class PADEROrchestrator:
    """
    Coordinates the complete end-to-end PADER report generation pipeline.
    Ensures newly generated reports default to DRAFT_PENDING_REVIEW.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or create_llm_client()
        self.section_generator = SectionGenerator(self.llm_client)
        self.grounding_validator = GroundingValidator()
        self.report_assembler = ReportAssembler()
        self.evaluator = PADEREvaluator()
        self.review_manager = HumanReviewManager()

    def run(
        self,
        file_path: str,
        output_dir: Optional[str] = "outputs",
        review_decision: ReviewDecision = ReviewDecision.PENDING_REVIEW,
        reviewer_name: str = "Qualified Safety Reviewer",
        reviewer_notes: Optional[str] = None,
        is_simulated_review: bool = False
    ) -> PADERReport:
        # 1. Data Ingestion & Normalization
        df = load_and_normalize_data(file_path)
        data_issues = validate_data(df)

        # 2. Deterministic Analysis Layer (Phase 2)
        engine = AnalysisEngine(df)
        analyses: Dict[str, AnalysisResult] = {
            "period_001": engine.get_reporting_period(),
            "vol_001": engine.get_case_volume(),
            "demo_age_001": engine.get_age_distribution(),
            "demo_sex_001": engine.get_sex_distribution(),
            "demo_country_001": engine.get_country_distribution(),
            "rx_001": engine.get_reactions(top_n=20),
            "rx_002": engine.get_serious_reactions(top_n=20),
            "out_001": engine.get_outcomes(),
            "trend_001": engine.get_time_trends(),
            "alert_001": engine.get_alert_cases(),
            "hist_001": engine.get_history_of_actions(),
            "exp_001": engine.get_expectedness(),
            "idx_001": engine.get_case_index(limit=100)
        }

        # 3. Evidence Collection Layer (Phase 3)
        evidence_list = collect_evidence(
            period=analyses["period_001"],
            volume=analyses["vol_001"],
            age=analyses["demo_age_001"],
            sex=analyses["demo_sex_001"],
            country=analyses["demo_country_001"],
            reactions=analyses["rx_001"],
            serious_reactions=analyses["rx_002"],
            outcomes=analyses["out_001"],
            trends=analyses["trend_001"],
            alerts=analyses["alert_001"],
            history=analyses["hist_001"],
            expectedness=analyses["exp_001"],
            case_index=analyses["idx_001"]
        )

        # 4. Context Packet Builder (Phase 3)
        builder = ContextBuilder(PADER_CONFIG, evidence_list)
        packets = builder.build_all_packets()

        # 5. LLM Generation Layer (Phase 4) for narrative sections
        generated_sections: Dict[str, GeneratedSection] = {}
        validations: Dict[str, ValidationResult] = {}

        llm_target_sections = [
            "Narrative Summary",
            "Summary Analysis of Cases",
            "Reaction Analysis",
            "15-Day Alert Reports",
            "Trends and Important Observations"
        ]

        for pkt in packets:
            if pkt.section_name in llm_target_sections:
                try:
                    gen_sec = self.section_generator.generate(pkt)
                    val_res = self.grounding_validator.validate_section(gen_sec, pkt)
                    generated_sections[pkt.section_name] = gen_sec
                    validations[pkt.section_name] = val_res
                except Exception as exc:
                    # Safe failure: surface error without corrupting other sections
                    from .generation_models import GeneratedSection, ValidationResult
                    generated_sections[pkt.section_name] = GeneratedSection(
                        section_name=pkt.section_name,
                        narrative=f"[GENERATION FAILED — Section requires manual review. Error: {type(exc).__name__}]",
                        evidence_ids=[e.evidence_id for e in pkt.evidence],
                        limitations=["Section generation failed. Manual review required."],
                        generation_metadata={"error": str(exc), "error_type": type(exc).__name__}
                    )
                    from .generation_models import ValidationResult
                    validations[pkt.section_name] = ValidationResult(
                        section_name=pkt.section_name,
                        is_grounded=False,
                        warnings=[f"Generation failed: {type(exc).__name__}: {exc}"]
                    )

        # 6. Report Metadata
        p_val = analyses["period_001"].value
        metadata = ReportMetadata(
            report_type="PADER",
            product_name="BISOPROLOL",
            application_number="B-1",
            sponsor_name="Dev Pharma Client",
            reporting_period_start=p_val.get("start_date", "Unknown"),
            reporting_period_end=p_val.get("end_date", "Unknown")
        )

        # 7. Report Assembly (Phase 5) -> Defaults to DRAFT_PENDING_REVIEW
        report = self.report_assembler.assemble_report(
            metadata=metadata,
            analyses=analyses,
            generated_sections=generated_sections,
            validations=validations
        )

        # 8. Automated Evaluation Framework (Phase 5) -> Evaluates quality (PASS / REVIEW_REQUIRED)
        eval_report = self.evaluator.evaluate(report)
        report.evaluation = eval_report

        # 9. Human Review Action (Separate explicit step)
        if review_decision != ReviewDecision.PENDING_REVIEW:
            report = self.review_manager.apply_decision(
                report=report,
                decision=review_decision,
                reviewer_name=reviewer_name,
                notes=reviewer_notes,
                is_simulated=is_simulated_review
            )

        # 10. Persist Output Artifacts if requested
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            # Render Markdown Report
            md_content = self.report_assembler.to_markdown(report)
            with open(os.path.join(output_dir, "pader_report.md"), "w", encoding="utf-8") as f:
                f.write(md_content)

            # Render Evaluation JSON
            with open(os.path.join(output_dir, "evaluation.json"), "w", encoding="utf-8") as f:
                json.dump(eval_report.model_dump(), f, indent=2)

            # Render Review Record JSON if present
            if report.review_record:
                with open(os.path.join(output_dir, "review.json"), "w", encoding="utf-8") as f:
                    json.dump(report.review_record.model_dump(), f, indent=2)

        return report
