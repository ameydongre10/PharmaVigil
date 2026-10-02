"""
Generation and validation schemas for Phase 4 Grounded LLM Generation.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class LLMRequest(BaseModel):
    """Encapsulates a request sent to the LLM client."""
    system_prompt: str
    user_prompt: str
    temperature: float = 0.0
    max_tokens: Optional[int] = 2048
    response_format: Optional[str] = "json_object"


class LLMResponse(BaseModel):
    """Standard response from any LLM provider."""
    model_config = {"protected_namespaces": ()}
    content: str
    model_name: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    latency_seconds: Optional[float] = None
    raw_response: Optional[Dict[str, Any]] = None


class GeneratedSection(BaseModel):
    """
    Structured model output for a single generated report section.

    Retains explicit evidence IDs for end-to-end traceability.
    """
    section_name: str = Field(..., description="Target report section name")
    narrative: str = Field(..., description="Generated regulatory narrative text")
    evidence_ids: List[str] = Field(
        default_factory=list,
        description="List of EvidenceItem IDs available/used for this section"
    )
    limitations: List[str] = Field(
        default_factory=list,
        description="Explicit limitations or missing data acknowledged in generation"
    )
    generation_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata including model name, timestamp, token usage, latency"
    )


class ValidationResult(BaseModel):
    """
    Result of deterministic grounding validation on a generated section.
    """
    section_name: str
    is_grounded: bool = Field(
        ..., description="True if no suspicious numbers or forbidden claims detected"
    )
    extracted_numbers: List[float] = Field(
        default_factory=list, description="All numerical values found in the narrative"
    )
    supported_numbers: List[float] = Field(
        default_factory=list, description="Numbers verified against supplied evidence"
    )
    unsupported_numbers: List[float] = Field(
        default_factory=list, description="Numbers present in text but not found in evidence"
    )
    flagged_claims: List[str] = Field(
        default_factory=list, description="Forbidden ungrounded causal/signal claims detected"
    )
    warnings: List[str] = Field(
        default_factory=list, description="Informational warnings or soft flags"
    )
