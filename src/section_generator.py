"""
Section Generator — transforms a Phase 3 SectionContextPacket into a structured GeneratedSection.
"""

import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from .evidence_models import SectionContextPacket
from .generation_models import LLMRequest, GeneratedSection
from .llm_client import LLMClient
from .prompts import BASE_SYSTEM_PROMPT, format_section_user_prompt


class SectionGenerator:
    """
    Coordinates LLM generation of a single report section from an approved context packet.
    """

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def generate(
        self,
        context_packet: SectionContextPacket,
        temperature: float = 0.0,
        max_tokens: int = 2048
    ) -> GeneratedSection:
        """
        Generate a structured section from an approved SectionContextPacket.
        """
        system_prompt = BASE_SYSTEM_PROMPT
        user_prompt = format_section_user_prompt(context_packet)

        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format="json_object"
        )

        response = self.llm_client.generate(request)
        parsed_data = self._parse_json_response(response.content)

        # Extract evidence IDs from the context packet for traceability
        available_eids = [e.evidence_id for e in context_packet.evidence]

        metadata: Dict[str, Any] = {
            "model_name": response.model_name,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "latency_seconds": response.latency_seconds,
            "evidence_item_count": len(context_packet.evidence),
        }

        return GeneratedSection(
            section_name=context_packet.section_name,
            narrative=parsed_data.get("narrative", "").strip(),
            evidence_ids=available_eids,
            limitations=parsed_data.get("limitations", []),
            generation_metadata=metadata
        )

    def _parse_json_response(self, raw_content: str) -> Dict[str, Any]:
        """
        Safely parse JSON response from LLM, stripping any surrounding markdown if present.
        """
        content = raw_content.strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
            if match:
                content = match.group(1).strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}\nRaw content:\n{raw_content}")
