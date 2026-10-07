"""
PADER Pipeline Orchestrator ?" coordinates data loading, deterministic analysis, evidence collection,
grounded LLM generation, report assembly, evaluation, and human review sign-off.
"""

import os
import json
import re
from pathlib import Path
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
        is_simulated_review: bool = False,
        doctor_license: Optional[str] = None,
        specialty: Optional[str] = None,
        affiliation: Optional[str] = None,
        verification_id: Optional[str] = None,
        signature_hash: Optional[str] = None
    ) -> PADERReport:
        # 1. Data Ingestion & Normalization
        df = load_and_normalize_data(file_path)
        data_issues = validate_data(df)

        # 2. Deterministic Analysis Layer (Phase 2)
        engine = AnalysisEngine(df)
        rx_res = engine.get_reactions(top_n=20)
        rx_serious_res = engine.get_serious_reactions(top_n=20)
        out_res = engine.get_outcomes()

        if rx_res is None:
            rx_res = AnalysisResult(
                analysis_id="rx_001",
                analysis_name="Top Reactions",
                metric="Top 20 Counts",
                value={},
                methodology="Count of unique PTs per case",
                case_level=False,
                source_fields=["patient_reaction_reactionmeddrapt"]
            )
        if rx_serious_res is None:
            rx_serious_res = AnalysisResult(
                analysis_id="rx_002",
                analysis_name="Top Serious Reactions",
                metric="Top 20 Counts in Serious Cases",
                value={},
                methodology="Count of unique PTs per serious case",
                case_level=False,
                source_fields=["patient_reaction_reactionmeddrapt", "serious"]
            )
        if out_res is None:
            out_res = AnalysisResult(
                analysis_id="out_001",
                analysis_name="Reaction Outcomes",
                metric="Counts",
                value={"Unknown": len(df)},
                methodology="Row-level count of reaction outcomes",
                case_level=False,
                source_fields=[]
            )

        analyses: Dict[str, AnalysisResult] = {
            "period_001": engine.get_reporting_period(),
            "vol_001": engine.get_case_volume(),
            "demo_age_001": engine.get_age_distribution(),
            "demo_sex_001": engine.get_sex_distribution(),
            "demo_country_001": engine.get_country_distribution(),
            "rx_001": rx_res,
            "rx_002": rx_serious_res,
            "out_001": out_res,
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
                        narrative=f"[GENERATION FAILED - Section requires manual review. Error: {type(exc).__name__}]",
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

        # 6. Report Metadata - dynamically derived from dataset or file
        p_val = analyses["period_001"].value
        inferred_product = None
        if "medicinalproduct" in df.columns:
            top_drugs = df["medicinalproduct"].dropna().astype(str).str.strip().str.upper()
            valid_drugs = top_drugs[(top_drugs != "") & (top_drugs != "NAN") & (top_drugs != "NONE")]
            if not valid_drugs.empty:
                inferred_product = valid_drugs.value_counts().index[0]
        if not inferred_product:
            file_stem = Path(file_path).stem
            # Strip upload timestamp prefix e.g., uploaded_1728123456_amoxicillin_study -> amoxicillin_study
            clean_stem = re.sub(r"^uploaded_\d+_", "", file_stem, flags=re.IGNORECASE)
            parts = [p for p in re.split(r"[_\-\s]+", clean_stem) if p and not p.isdigit() and p.upper() not in ("SAMPLE", "DATA", "DATASET", "STUDY", "ICSR", "ROWS", "TEST", "UPLOADED")]
            if parts:
                candidate = parts[0].strip().upper()
                if candidate:
                    inferred_product = candidate
        if not inferred_product:
            inferred_product = "BISOPROLOL"

        app_num = "B-1" if inferred_product == "BISOPROLOL" else f"NDA-{inferred_product[:4]}-01"
        sponsor = "Dev Pharma Client" if inferred_product == "BISOPROLOL" else "Clinical Safety Sponsor"

        metadata = ReportMetadata(
            report_type="PADER",
            product_name=inferred_product,
            application_number=app_num,
            sponsor_name=sponsor,
            reporting_period_start=p_val.get("start_date") or "Unknown",
            reporting_period_end=p_val.get("end_date") or "Unknown"
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
                is_simulated=is_simulated_review,
                doctor_license=doctor_license,
                specialty=specialty,
                affiliation=affiliation,
                verification_id=verification_id,
                signature_hash=signature_hash
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
