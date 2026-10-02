"""
Context Builder — assembles minimal, section-specific context packets
from the full evidence list and a report configuration.

Core guarantee: each SectionContextPacket contains ONLY the evidence
items whose analysis_id is listed in that section's required or optional
analysis_ids. Raw DataFrames or the full dataset are never included.
"""

from typing import List, Dict
from .evidence_models import (
    EvidenceItem,
    SectionContextPacket,
    ReportSectionConfig,
    ReportTypeConfig,
)


class ContextBuilder:
    """Builds per-section context packets from evidence and a report config."""

    def __init__(self, config: ReportTypeConfig, evidence: List[EvidenceItem]):
        self.config = config
        self.evidence = evidence
        # Index evidence by analysis_id for fast lookup
        self._by_analysis: Dict[str, List[EvidenceItem]] = {}
        for item in evidence:
            self._by_analysis.setdefault(item.analysis_id, []).append(item)

    def build_section_packet(
        self, section_cfg: ReportSectionConfig
    ) -> SectionContextPacket:
        """
        Build a context packet for one section.

        Selects only evidence whose analysis_id appears in the section's
        required or optional analysis_ids.
        """
        allowed_ids = set(section_cfg.required_analysis_ids
                          + section_cfg.optional_analysis_ids)

        selected: List[EvidenceItem] = []
        for aid in allowed_ids:
            selected.extend(self._by_analysis.get(aid, []))

        grounding = list(SectionContextPacket.model_fields[
            "grounding_instructions"
        ].default_factory()) + section_cfg.extra_grounding_instructions

        return SectionContextPacket(
            report_type=self.config.report_type,
            section_name=section_cfg.section_name,
            section_purpose=section_cfg.section_purpose,
            evidence=selected,
            grounding_instructions=grounding,
        )

    def build_all_packets(self) -> List[SectionContextPacket]:
        """Build context packets for every section in the report config."""
        return [
            self.build_section_packet(sec) for sec in self.config.sections
        ]

    def validate(self) -> List[str]:
        """
        Validate that all required analysis_ids are present in the evidence.

        Returns a list of error messages (empty list = valid).
        """
        errors: List[str] = []
        available_ids = set(self._by_analysis.keys())

        for sec in self.config.sections:
            for aid in sec.required_analysis_ids:
                if aid not in available_ids:
                    errors.append(
                        f"Section '{sec.section_name}' requires "
                        f"analysis_id '{aid}' but it is missing from evidence."
                    )

        # Check evidence_id uniqueness
        seen_eids: set = set()
        for item in self.evidence:
            if item.evidence_id in seen_eids:
                errors.append(
                    f"Duplicate evidence_id: '{item.evidence_id}'"
                )
            seen_eids.add(item.evidence_id)

        return errors
