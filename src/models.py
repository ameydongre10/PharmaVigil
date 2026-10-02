from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

class AnalysisResult(BaseModel):
    """Structured model for deterministic analysis results to be passed to LLM."""
    analysis_id: str
    analysis_name: str
    metric: str
    value: Any
    unit: Optional[str] = None
    methodology: str
    case_level: bool
    source_fields: List[str]
    supporting_case_ids: Optional[List[str]] = None
