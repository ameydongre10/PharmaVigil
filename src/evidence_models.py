"""
Evidence and context engineering models for the GenAR system.

The evidence layer sits between deterministic analysis (Phase 2) and
LLM generation (Phase 4). It organises approved facts into traceable
evidence items, groups them by report section, and packages only the
relevant evidence into minimal context packets for each section.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum


class EvidenceType(str, Enum):
    """Distinguishes hard facts from defensible observations."""
    FACT = "fact"                   # Directly computed value (e.g. "total cases = 1024")
    OBSERVATION = "observation"     # Defensible statement derived from facts (e.g. "most common reaction")
    NOT_AVAILABLE = "not_available" # Explicitly represents missing/out-of-scope data


class AggregationLevel(str, Enum):
    CASE = "case"
    REACTION = "reaction"
    ROW = "row"


class EvidenceItem(BaseModel):
    """
    A single traceable piece of approved evidence.

    Every EvidenceItem must trace back to a deterministic AnalysisResult
    produced in Phase 2. The evidence layer does NOT recalculate values;
    it only organises and labels them.
    """
    evidence_id: str = Field(..., description="Unique identifier, e.g. EV_CASE_TOTAL")
    analysis_id: str = Field(..., description="The Phase 2 AnalysisResult.analysis_id this came from")
    section: str = Field(..., description="Primary report section this evidence serves")
    evidence_type: EvidenceType = Field(default=EvidenceType.FACT)
    metric: str = Field(..., description="Human-readable name of what is measured")
    value: Any = Field(..., description="The approved value")
    unit: Optional[str] = None
    aggregation_level: AggregationLevel = Field(default=AggregationLevel.CASE)
    source_fields: List[str] = Field(default_factory=list)
    methodology: str = Field(default="", description="How the value was calculated")
    notes: Optional[str] = None


class SectionContextPacket(BaseModel):
    """
    A minimal, self-contained context packet for one report section.

    This is what Phase 4 will pass to the LLM. It contains ONLY the
    evidence relevant to the target section, plus static instructions.
    It must NEVER contain a raw DataFrame or the full dataset.
    """
    report_type: str = Field(default="PADER")
    section_name: str
    section_purpose: str
    evidence: List[EvidenceItem]
    grounding_instructions: List[str] = Field(
        default_factory=lambda: [
            "Use ONLY the evidence supplied in this context packet.",
            "Do NOT invent or infer facts not present in the evidence.",
            "Do NOT perform independent calculations.",
            "Do NOT infer causality or declare safety signals unless the evidence explicitly supports such a conclusion.",
            "Use neutral, regulatory-style language.",
            "Distinguish observations from conclusions.",
            "Acknowledge information that is unavailable or out of scope.",
        ]
    )


class ReportSectionConfig(BaseModel):
    """Configuration for one section of a report type."""
    section_name: str
    section_purpose: str
    required_analysis_ids: List[str] = Field(
        ..., description="Phase 2 analysis_ids this section depends on"
    )
    optional_analysis_ids: List[str] = Field(default_factory=list)
    extra_grounding_instructions: List[str] = Field(default_factory=list)


class ReportTypeConfig(BaseModel):
    """
    Top-level configuration for a report type.

    Version 0 supports PADER only. Future report types (PSUR, PBRER, etc.)
    can be added as new ReportTypeConfig instances without modifying the
    evidence engine or context builder code.
    """
    report_type: str
    display_name: str
    sections: List[ReportSectionConfig]
