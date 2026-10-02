"""
Grounding Validator — deterministic validation of generated narrative against approved context.
"""

import re
from typing import List, Set, Any
from .evidence_models import SectionContextPacket
from .generation_models import GeneratedSection, ValidationResult


# Forbidden phrases that assert ungrounded causality or signals
FORBIDDEN_CLAIM_PATTERNS = [
    (r"\b(proven to cause|definitely caused|causes|causality is established|causality established)\b", "Causal inference asserted"),
    (r"\b(confirmed safety signal|confirmed signal|proven safety risk|definite safety concern)\b", "Confirmed safety signal declared"),
    (r"\b(labeling change implemented|label updated|black box warning added|market withdrawal ordered)\b", "Invented regulatory action"),
]


class GroundingValidator:
    """
    Validates that a GeneratedSection adheres to evidence grounding rules.
    """

    def validate_section(
        self,
        generated: GeneratedSection,
        context_packet: SectionContextPacket
    ) -> ValidationResult:
        narrative = generated.narrative

        # 1. Extract numbers from text
        extracted_numbers = self._extract_numbers_from_text(narrative)

        # 2. Extract allowed numbers from evidence
        allowed_numbers = self._extract_allowed_numbers_from_evidence(context_packet)

        # 3. Compare numbers
        supported_numbers: List[float] = []
        unsupported_numbers: List[float] = []

        for num in extracted_numbers:
            # Allow integer vs float match, e.g. 99.9 vs 99.9
            if any(abs(num - allowed) < 0.01 for allowed in allowed_numbers):
                supported_numbers.append(num)
            else:
                unsupported_numbers.append(num)

        # 4. Check for forbidden claims
        flagged_claims: List[str] = []
        for pattern, reason in FORBIDDEN_CLAIM_PATTERNS:
            match = re.search(pattern, narrative, re.IGNORECASE)
            if match:
                flagged_claims.append(f"{reason}: '{match.group(0)}'")

        warnings: List[str] = []
        if unsupported_numbers:
            warnings.append(f"Detected {len(unsupported_numbers)} numerical values in text not present in approved evidence: {unsupported_numbers}")
        if flagged_claims:
            warnings.append(f"Detected {len(flagged_claims)} forbidden/unsupported claim phrases.")

        is_grounded = (len(unsupported_numbers) == 0 and len(flagged_claims) == 0)

        return ValidationResult(
            section_name=generated.section_name,
            is_grounded=is_grounded,
            extracted_numbers=extracted_numbers,
            supported_numbers=supported_numbers,
            unsupported_numbers=unsupported_numbers,
            flagged_claims=flagged_claims,
            warnings=warnings
        )

    def _extract_numbers_from_text(self, text: str) -> List[float]:
        """Extract all isolated numbers and percentages from text."""
        # Clean text of date formats like 2024-12-27 so we extract year/month/day
        cleaned = re.sub(r"(\d{4})-(\d{2})-(\d{2})", r"\1 \2 \3", text)
        # Match standard numbers: 1,024 -> 1024, 99.9% -> 99.9
        tokens = re.findall(r"(?<![a-zA-Z_])\b\d+(?:,\d{3})*(?:\.\d+)?%?\b", cleaned)
        numbers = []
        for t in tokens:
            t_clean = t.replace(",", "").replace("%", "")
            try:
                numbers.append(float(t_clean))
            except ValueError:
                continue
        return numbers

    def _extract_allowed_numbers_from_evidence(self, context_packet: SectionContextPacket) -> Set[float]:
        """Recursively harvest all numbers from context packet evidence values."""
        allowed: Set[float] = set()

        def _collect(val: Any):
            if val is None:
                return
            if isinstance(val, (int, float)):
                allowed.add(float(val))
            elif isinstance(val, str):
                # Check for dates: 2024-12-27
                date_match = re.match(r"(\d{4})-(\d{2})-(\d{2})", val)
                if date_match:
                    allowed.add(float(date_match.group(1))) # 2024
                    allowed.add(float(date_match.group(2))) # 12
                    allowed.add(float(date_match.group(3))) # 27
                else:
                    # Generic numbers in string
                    for n in re.findall(r"\b\d+(?:\.\d+)?\b", val):
                        try:
                            allowed.add(float(n))
                        except ValueError:
                            pass
            elif isinstance(val, dict):
                for k, v in val.items():
                    _collect(k)
                    _collect(v)
            elif isinstance(val, (list, tuple, set)):
                for item in val:
                    _collect(item)

        # Collect numbers from evidence values
        for e in context_packet.evidence:
            _collect(e.value)
            _collect(e.metric)
            _collect(e.methodology)

        # Collect numbers from section metadata and grounding instructions (e.g. "15" from "15-Day Alert")
        _collect(context_packet.section_name)
        _collect(context_packet.section_purpose)
        for inst in context_packet.grounding_instructions:
            _collect(inst)

        # Also permit common structural numbers and standard regulatory timeframes
        for n in [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 15.0, 30.0, 60.0, 90.0, 180.0, 365.0]:
            allowed.add(n)

        return allowed
