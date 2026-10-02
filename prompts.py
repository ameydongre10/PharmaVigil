"""
Prompt templates and formatting utilities for grounded regulatory narrative generation.
"""

import json
from .evidence_models import SectionContextPacket


BASE_SYSTEM_PROMPT = """You are a specialized regulatory medical writing assistant assisting in the preparation of a Periodic Adverse Drug Experience Report (PADER).

Your primary responsibility is ABSOLUTE GROUNDING to the approved quantitative and qualitative evidence supplied to you.

STRICT GROUNDING RULES:
1. Use ONLY the approved evidence supplied in the context packet.
2. Do NOT invent or extrapolate facts, patient records, or numbers not present in the evidence.
3. Do NOT perform independent calculations or statistical transformations.
4. Do NOT introduce numbers, percentages, or metrics that are not directly supported by the evidence.
5. Do NOT infer causality (e.g. do NOT state that the drug caused an adverse event).
6. Do NOT declare a confirmed safety signal or safety risk unless the evidence explicitly provides such an assessment.
7. Use neutral, objective, regulatory-style medical language.
8. Distinguish observed data from high-level observations and acknowledge limitations.
9. Explicitly state when information is unavailable, missing, or out of scope.
10. Do NOT invent System Organ Class (SOC) classifications; report reactions only using the supplied MedDRA Preferred Terms (PT).
11. Do NOT determine or speculate on Expectedness / Labelled status unless explicit CCDS/Product Label evidence is provided.
12. Do NOT invent history-of-actions data.
13. Keep the narrative concise, professional, and strictly focused on the requested section.
14. Return your output STRICTLY as a valid JSON object matching the requested schema.
"""


OUTPUT_SCHEMA_INSTRUCTIONS = """
You must respond with a single, valid JSON object with the following schema:
{
  "narrative": "<string: the regulatory narrative text for this section>",
  "limitations": [
    "<string: explicit acknowledgement of missing/unavailable data, e.g. 'No history of actions provided'>"
  ]
}
Do not include any introductory commentary or markdown blocks outside the JSON object.
"""


def format_section_user_prompt(context_packet: SectionContextPacket) -> str:
    """
    Format a minimal, section-specific user prompt from a SectionContextPacket.
    Never includes raw DataFrames or the full dataset.
    """
    # Serialize evidence items cleanly without internal artifacts
    evidence_payload = [
        {
            "evidence_id": e.evidence_id,
            "metric": e.metric,
            "evidence_type": e.evidence_type.value,
            "value": e.value,
            "unit": e.unit,
            "aggregation_level": e.aggregation_level.value,
            "methodology": e.methodology,
            "notes": e.notes,
        }
        for e in context_packet.evidence
    ]

    prompt = f"""=== REPORT SECTION GENERATION TASK ===
Report Type: {context_packet.report_type}
Section Name: {context_packet.section_name}
Section Purpose: {context_packet.section_purpose}

=== SECTION GROUNDING INSTRUCTIONS ===
"""
    for idx, inst in enumerate(context_packet.grounding_instructions, 1):
        prompt += f"{idx}. {inst}\n"

    prompt += f"""
=== APPROVED EVIDENCE PACKET ===
{json.dumps(evidence_payload, indent=2)}

=== OUTPUT FORMAT REQUIREMENTS ===
{OUTPUT_SCHEMA_INSTRUCTIONS}
"""
    return prompt
