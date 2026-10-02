"""
Offline tests for Phase 4 Grounded LLM Generation and Validation.
All tests run offline using MockLLMClient and in-memory fixtures.
"""

import json
import pytest
from src.evidence_models import (
    EvidenceItem, EvidenceType, AggregationLevel, SectionContextPacket
)
from src.generation_models import GeneratedSection
from src.llm_client import MockLLMClient, OpenAICompatibleLLMClient
from src.section_generator import SectionGenerator
from src.grounding_validator import GroundingValidator
from src.prompts import format_section_user_prompt, BASE_SYSTEM_PROMPT


@pytest.fixture
def mock_context_packet():
    return SectionContextPacket(
        report_type="PADER",
        section_name="Narrative Summary",
        section_purpose="Executive summary of reporting period and top reactions.",
        evidence=[
            EvidenceItem(
                evidence_id="EV_PERIOD_START",
                analysis_id="period_001",
                section="Reporting Period",
                metric="Start Date",
                value="2024-12-27",
                methodology="min receivedate"
            ),
            EvidenceItem(
                evidence_id="EV_PERIOD_END",
                analysis_id="period_001",
                section="Reporting Period",
                metric="End Date",
                value="2025-12-26",
                methodology="max receivedate"
            ),
            EvidenceItem(
                evidence_id="EV_CASE_TOTAL",
                analysis_id="vol_001",
                section="Narrative Summary",
                metric="Total Cases",
                value=1024,
                methodology="unique safetyreportid"
            ),
            EvidenceItem(
                evidence_id="EV_CASE_SERIOUS",
                analysis_id="vol_001",
                section="Narrative Summary",
                metric="Serious Cases",
                value=1023,
                methodology="serious is true"
            ),
            EvidenceItem(
                evidence_id="EV_CASE_SERIOUS_PCT",
                analysis_id="vol_001",
                section="Narrative Summary",
                metric="Serious Pct",
                value=99.9,
                unit="%",
                methodology="serious / total"
            ),
            EvidenceItem(
                evidence_id="EV_CASE_NON_SERIOUS",
                analysis_id="vol_001",
                section="Narrative Summary",
                metric="Non-serious Cases",
                value=1,
                methodology="non-serious is true"
            ),
            EvidenceItem(
                evidence_id="EV_CASE_NON_SERIOUS_PCT",
                analysis_id="vol_001",
                section="Narrative Summary",
                metric="Non-serious Pct",
                value=0.1,
                unit="%",
                methodology="non_serious / total"
            ),
            EvidenceItem(
                evidence_id="EV_MOST_COMMON_REACTION",
                analysis_id="rx_001",
                section="Narrative Summary",
                evidence_type=EvidenceType.OBSERVATION,
                metric="Top Reaction",
                value={"reaction": "Acute kidney injury", "count": 22},
                methodology="top count"
            ),
        ]
    )


class TestPromptAssembly:
    def test_prompt_formatting_contains_evidence_and_instructions(self, mock_context_packet):
        prompt = format_section_user_prompt(mock_context_packet)
        assert "Narrative Summary" in prompt
        assert "EV_CASE_TOTAL" in prompt
        assert "1024" in prompt
        assert "Acute kidney injury" in prompt
        assert "STRICT GROUNDING RULES" not in prompt # System prompt is separate

    def test_system_prompt_enforces_rules(self):
        assert "ONLY the approved evidence" in BASE_SYSTEM_PROMPT
        assert "Do NOT infer causality" in BASE_SYSTEM_PROMPT
        assert "Do NOT declare a confirmed safety signal" in BASE_SYSTEM_PROMPT


class TestSectionGenerator:
    def test_generation_with_mock_client(self, mock_context_packet):
        client = MockLLMClient()
        generator = SectionGenerator(client)

        section = generator.generate(mock_context_packet)

        assert isinstance(section, GeneratedSection)
        assert section.section_name == "Narrative Summary"
        assert "1,024" in section.narrative or "1024" in section.narrative
        assert "EV_CASE_TOTAL" in section.evidence_ids
        assert len(section.evidence_ids) == 8
        assert section.generation_metadata["model_name"] == "mock-model-v1"

    def test_json_parsing_with_markdown_fences(self, mock_context_packet):
        fenced_json = "```json\n{\n  \"narrative\": \"Test narrative text with 1024 cases.\",\n  \"limitations\": [\"No label provided\"]\n}\n```"
        client = MockLLMClient(canned_responses={"narrative summary": fenced_json})
        generator = SectionGenerator(client)

        section = generator.generate(mock_context_packet)
        assert section.narrative == "Test narrative text with 1024 cases."
        assert section.limitations == ["No label provided"]

    def test_malformed_json_raises_error(self, mock_context_packet):
        client = MockLLMClient(canned_responses={"narrative summary": "Not valid JSON at all"})
        generator = SectionGenerator(client)

        with pytest.raises(ValueError, match="Failed to parse LLM response as JSON"):
            generator.generate(mock_context_packet)


class TestGroundingValidator:
    def test_valid_grounded_narrative_passes(self, mock_context_packet):
        client = MockLLMClient()
        generator = SectionGenerator(client)
        section = generator.generate(mock_context_packet)

        validator = GroundingValidator()
        val_result = validator.validate_section(section, mock_context_packet)

        assert val_result.is_grounded is True
        assert len(val_result.unsupported_numbers) == 0
        assert len(val_result.flagged_claims) == 0

    def test_hallucinated_number_is_flagged(self, mock_context_packet):
        # Generate narrative with hallucinated number 1100
        bad_json = json.dumps({
            "narrative": "A total of 1,100 cases were received, including 500 fatal cases.",
            "limitations": []
        })
        client = MockLLMClient(canned_responses={"narrative summary": bad_json})
        generator = SectionGenerator(client)
        section = generator.generate(mock_context_packet)

        validator = GroundingValidator()
        val_result = validator.validate_section(section, mock_context_packet)

        assert val_result.is_grounded is False
        assert 1100.0 in val_result.unsupported_numbers
        assert 500.0 in val_result.unsupported_numbers

    def test_forbidden_causality_claim_is_flagged(self, mock_context_packet):
        bad_json = json.dumps({
            "narrative": "The medication causes Acute kidney injury in 22 patients.",
            "limitations": []
        })
        client = MockLLMClient(canned_responses={"narrative summary": bad_json})
        generator = SectionGenerator(client)
        section = generator.generate(mock_context_packet)

        validator = GroundingValidator()
        val_result = validator.validate_section(section, mock_context_packet)

        assert val_result.is_grounded is False
        assert any("Causal inference" in claim for claim in val_result.flagged_claims)

    def test_forbidden_safety_signal_claim_is_flagged(self, mock_context_packet):
        bad_json = json.dumps({
            "narrative": "Acute kidney injury is a confirmed safety signal.",
            "limitations": []
        })
        client = MockLLMClient(canned_responses={"narrative summary": bad_json})
        generator = SectionGenerator(client)
        section = generator.generate(mock_context_packet)

        validator = GroundingValidator()
        val_result = validator.validate_section(section, mock_context_packet)

        assert val_result.is_grounded is False
        assert any("safety signal" in claim for claim in val_result.flagged_claims)


class TestClientConfiguration:
    def test_openai_client_requires_api_key(self):
        with pytest.raises(ValueError, match="API key must be provided"):
            OpenAICompatibleLLMClient(api_key="")
