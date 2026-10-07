"""
Human Review & Revision Manager ?" provides structured audit trails and targeted section revision.
Enforces that automated generation produces PENDING_REVIEW, requiring an explicit review action to approve.
"""

import json
from typing import Optional
from .report_models import (
    PADERReport, ReviewRecord, ReviewDecision, ReportStatus, SectionStatus, SectionType
)
from .evidence_models import SectionContextPacket
from .section_generator import SectionGenerator
from .grounding_validator import GroundingValidator


class HumanReviewManager:
    """
    Manages the explicit human approval workflow, simulated review fixtures, and targeted section revision.
    """

    def apply_decision(
        self,
        report: PADERReport,
        decision: ReviewDecision,
        reviewer_name: str = "Qualified Safety Reviewer",
        notes: Optional[str] = None,
        is_simulated: bool = False,
        doctor_license: Optional[str] = None,
        specialty: Optional[str] = None,
        affiliation: Optional[str] = None,
        verification_id: Optional[str] = None,
        signature_hash: Optional[str] = None
    ) -> PADERReport:
        """
        Record an explicit human review decision (or a designated simulated test fixture decision),
        along with verified medical credentials and verification audit signature.
        """
        section_statuses = {}
        for sec in report.sections:
            if decision in (ReviewDecision.APPROVED, ReviewDecision.SIMULATED_APPROVED):
                section_statuses[sec.section_name] = SectionStatus.APPROVED
            elif decision == ReviewDecision.REJECTED:
                section_statuses[sec.section_name] = SectionStatus.REJECTED
            elif decision == ReviewDecision.NEEDS_REVISION:
                section_statuses[sec.section_name] = SectionStatus.REVIEW_REQUIRED
            else:
                section_statuses[sec.section_name] = sec.validation_status

        # Map decision to top-level report status
        if decision == ReviewDecision.APPROVED:
            report_status = ReportStatus.HUMAN_APPROVED
        elif decision == ReviewDecision.SIMULATED_APPROVED:
            report_status = ReportStatus.SIMULATED_APPROVED
            is_simulated = True
        elif decision == ReviewDecision.NEEDS_REVISION:
            report_status = ReportStatus.NEEDS_REVISION
        elif decision == ReviewDecision.REJECTED:
            report_status = ReportStatus.REJECTED
        else:
            report_status = ReportStatus.DRAFT_PENDING_REVIEW

        record = ReviewRecord(
            report_id=f"PADER-{report.metadata.product_name}-{report.metadata.reporting_period_end}",
            reviewer_decision=decision,
            reviewer_name=reviewer_name,
            doctor_license=doctor_license,
            specialty=specialty,
            affiliation=affiliation,
            verification_id=verification_id,
            signature_hash=signature_hash,
            is_simulated=is_simulated,
            section_statuses=section_statuses,
            reviewer_notes=notes
        )

        report.status = report_status
        report.review_record = record

        # Refresh evaluation human-approval flag if evaluation object exists
        if report.evaluation:
            report.evaluation.is_human_approved = (report_status == ReportStatus.HUMAN_APPROVED)

        return report

    def regenerate_section(
        self,
        report: PADERReport,
        section_name: str,
        generator: SectionGenerator,
        context_packet: SectionContextPacket,
        validator: GroundingValidator
    ) -> PADERReport:
        """
        Regenerate a single flagged section without recreating the entire report.
        Resets report status back to DRAFT_PENDING_REVIEW.
        """
        target_idx = None
        for i, sec in enumerate(report.sections):
            if sec.section_name == section_name:
                target_idx = i
                break

        if target_idx is None:
            raise ValueError(f"Section '{section_name}' not found in report.")

        fresh_generated = generator.generate(context_packet)
        val_res = validator.validate_section(fresh_generated, context_packet)

        val_status = SectionStatus.PASS if val_res.is_grounded else SectionStatus.REVIEW_REQUIRED

        updated_sec = report.sections[target_idx].model_copy(update={
            "narrative": fresh_generated.narrative,
            "limitations": fresh_generated.limitations,
            "validation_status": val_status,
            "validation_warnings": val_res.warnings,
            "generation_metadata": fresh_generated.generation_metadata
        })

        report.sections[target_idx] = updated_sec
        # Reset overall report review status back to pending review
        report.status = ReportStatus.DRAFT_PENDING_REVIEW
        report.review_record = None

        if report.evaluation:
            report.evaluation.is_human_approved = False

        return report

    def save_review_record(self, review: ReviewRecord, file_path: str):
        """Save machine-readable review audit record to disk."""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(review.model_dump(), f, indent=2)
