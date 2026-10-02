"""
Evaluation Engine — performs automated quality and grounding checks on an assembled PADERReport.
Strictly separates automated checks from human approval status.
"""

from typing import Dict, Any, List
from .report_models import PADERReport, EvaluationReport, SectionStatus, SectionType, ReportStatus


class PADEREvaluator:
    """
    Evaluates report quality, factual consistency, grounding coverage, and safety rule conformance.
    Tracks required assignment sections separately from additional limitation notices.
    """

    # The 8 mandatory report areas defined by the assignment
    REQUIRED_ASSIGNMENT_SECTIONS = [
        "Reporting Period",
        "Narrative Summary",
        "Summary Analysis of Cases",
        "Reaction Analysis",
        "15-Day Alert Reports",
        "Trends and Important Observations",
        "History of Actions",
        "Case Listing"
    ]

    # Additional contextual limitation sections (not independent mandatory PADER sections)
    ADDITIONAL_LIMITATION_SECTIONS = [
        "Expectedness"
    ]

    def evaluate(self, report: PADERReport) -> EvaluationReport:
        total_sections = len(report.sections)
        generated_count = sum(1 for s in report.sections if s.section_type == SectionType.LLM_GENERATED)
        deterministic_count = total_sections - generated_count

        passed_val = 0
        failed_val = 0
        unsupported_claims_total = 0
        valid_eid_sections = 0

        section_details: Dict[str, Dict[str, Any]] = {}
        present_section_names = {s.section_name for s in report.sections}

        for sec in report.sections:
            sec_name = sec.section_name
            is_valid = (sec.validation_status == SectionStatus.PASS)

            if is_valid:
                passed_val += 1
            else:
                failed_val += 1

            if sec.evidence_ids:
                valid_eid_sections += 1

            # Count warnings and issues
            warnings = sec.validation_warnings
            unsupported_claims = sum(1 for w in warnings if "claim" in w.lower())
            unsupported_claims_total += unsupported_claims

            section_details[sec_name] = {
                "type": sec.section_type.value,
                "is_required_by_assignment": sec.is_required_by_assignment,
                "status": sec.validation_status.value,
                "evidence_ids_count": len(sec.evidence_ids),
                "warnings": warnings
            }

        # Check required assignment sections completeness
        missing_required = [r for r in self.REQUIRED_ASSIGNMENT_SECTIONS if r not in present_section_names]
        required_complete = (len(missing_required) == 0)
        required_present_count = len(self.REQUIRED_ASSIGNMENT_SECTIONS) - len(missing_required)

        # Track additional limitation sections
        limitations_present = [lim for lim in self.ADDITIONAL_LIMITATION_SECTIONS if lim in present_section_names]

        # Calculate scores
        grounding_score = round((valid_eid_sections / total_sections) * 100, 1) if total_sections > 0 else 0.0

        if missing_required:
            failed_val += len(missing_required)

        # Factual consistency score
        factual_consistency_score = 100.0 if failed_val == 0 else max(0.0, round(((total_sections - failed_val) / total_sections) * 100, 1))

        # Automated Evaluation Status (PASS vs REVIEW_REQUIRED)
        # Note: PASS indicates automated quality checks passed; it does NOT mean Human Approved.
        if failed_val == 0 and unsupported_claims_total == 0 and required_complete:
            automated_eval_status = SectionStatus.PASS
        else:
            automated_eval_status = SectionStatus.REVIEW_REQUIRED

        report_id = f"PADER-{report.metadata.product_name}-{report.metadata.reporting_period_end}"

        return EvaluationReport(
            report_id=report_id,
            total_sections=total_sections,
            required_sections_total=len(self.REQUIRED_ASSIGNMENT_SECTIONS),
            required_sections_present=required_present_count,
            required_sections_complete=required_complete,
            additional_limitation_sections_present=limitations_present,
            generated_sections=generated_count,
            deterministic_sections=deterministic_count,
            passed_validation_sections=passed_val,
            failed_validation_sections=failed_val,
            factual_consistency_score=factual_consistency_score,
            grounding_score=grounding_score,
            unsupported_claim_count=unsupported_claims_total,
            automated_evaluation_status=automated_eval_status,
            is_human_approved=(report.status == ReportStatus.HUMAN_APPROVED),
            section_details=section_details
        )
