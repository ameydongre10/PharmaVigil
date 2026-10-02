"""
LLM Provider Abstraction.

Provides a clean interface for LLM calls with concrete implementations:
- MockLLMClient (for offline unit tests & offline demo)
- OpenAICompatibleLLMClient (for live OpenAI/Anthropic/Gemini/Ollama endpoints using urllib)
"""

import os
import json
import time
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from .generation_models import LLMRequest, LLMResponse


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a generation request to the LLM and return structured response."""
        pass


class MockLLMClient(LLMClient):
    """
    Deterministic Mock LLM client for offline unit testing and verification.
    Does not make any network requests.
    """

    def __init__(self, canned_responses: Optional[Dict[str, str]] = None):
        self.canned_responses = canned_responses or {}
        self.call_history = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.call_history.append(request)

        # Check if user prompt matches any canned response key
        for key, response_text in self.canned_responses.items():
            if key.lower() in request.user_prompt.lower():
                return LLMResponse(
                    content=response_text,
                    model_name="mock-model-v1",
                    prompt_tokens=150,
                    completion_tokens=100,
                    latency_seconds=0.01,
                    raw_response={"mock": True}
                )

        # Generate a deterministic mock response adhering to the JSON schema
        # Attempt to dynamically extract numbers from the prompt evidence payload for perfect grounding
        evidence_dict = {}
        try:
            # Find evidence JSON block
            if "=== APPROVED EVIDENCE PACKET ===" in request.user_prompt:
                block = request.user_prompt.split("=== APPROVED EVIDENCE PACKET ===")[1].split("=== OUTPUT FORMAT REQUIREMENTS ===")[0].strip()
                items = json.loads(block)
                for itm in items:
                    evidence_dict[itm.get("evidence_id")] = itm.get("value")
        except Exception:
            pass

        start_date = evidence_dict.get("EV_PERIOD_START", "2024-12-27")
        end_date = evidence_dict.get("EV_PERIOD_END", "2025-12-26")
        total_cases = evidence_dict.get("EV_CASE_TOTAL", 1024)
        serious_cases = evidence_dict.get("EV_CASE_SERIOUS", 1023)
        serious_pct = evidence_dict.get("EV_CASE_SERIOUS_PCT", 99.9)
        non_serious_cases = evidence_dict.get("EV_CASE_NON_SERIOUS", 1)
        non_serious_pct = evidence_dict.get("EV_CASE_NON_SERIOUS_PCT", 0.1)
        top_rx = evidence_dict.get("EV_MOST_COMMON_REACTION", {"reaction": "Acute kidney injury", "count": 22})
        top_rx_name = top_rx.get("reaction", "Acute kidney injury") if isinstance(top_rx, dict) else "Acute kidney injury"
        top_rx_cnt = top_rx.get("count", 22) if isinstance(top_rx, dict) else 22
        alert_total = evidence_dict.get("EV_ALERT_TOTAL", 1023)
        alert_serious = evidence_dict.get("EV_ALERT_SERIOUS", 1023)

        if "narrative summary" in request.user_prompt.lower():
            mock_content = json.dumps({
                "narrative": (
                    f"During the reporting period from {start_date} to {end_date}, a total of {total_cases:,} "
                    f"individual case safety reports were received. Of these, {serious_cases:,} cases ({serious_pct}%) "
                    f"were classified as serious, and {non_serious_cases:,} case ({non_serious_pct}%) was classified as non-serious. "
                    f"The most frequently reported adverse reaction was {top_rx_name} with {top_rx_cnt} cases."
                ),
                "limitations": [
                    "No product label/CCDS was provided to determine expectedness.",
                    "No history-of-actions data was provided."
                ]
            })
        elif "reaction analysis" in request.user_prompt.lower():
            rx_val = evidence_dict.get("EV_TOP_REACTIONS", {})
            if isinstance(rx_val, dict) and rx_val:
                rx_str = ", ".join([f"{k} ({v} cases)" for k, v in list(rx_val.items())[:5]])
            else:
                rx_str = "Acute kidney injury (22 cases), Drug ineffective (11 cases)"

            mock_content = json.dumps({
                "narrative": (
                    f"Adverse reactions were reported using MedDRA Preferred Terms. The most frequently "
                    f"reported reactions were {rx_str}. "
                    f"System Organ Class groupings are not available in the dataset."
                ),
                "limitations": [
                    "System Organ Class (SOC) classification is unavailable in the dataset."
                ]
            })
        elif "15-day alert" in request.user_prompt.lower():
            mock_content = json.dumps({
                "narrative": (
                    f"During the reporting interval, {alert_total:,} cases met the 15-day alert / expedited reporting criteria. "
                    f"All {alert_serious:,} alert cases were classified as serious."
                ),
                "limitations": []
            })
        elif "summary analysis of cases" in request.user_prompt.lower():
            mock_content = json.dumps({
                "narrative": (
                    f"A total of {total_cases:,} cases were analyzed across age, sex, and geographic regions. "
                    f"Of these cases, {serious_cases:,} were serious and {non_serious_cases:,} were non-serious."
                ),
                "limitations": []
            })
        elif "trends and important observations" in request.user_prompt.lower():
            mock_content = json.dumps({
                "narrative": (
                    f"Monthly reporting volumes across the interval showed steady reporting across the {total_cases:,} received cases. "
                    f"No confirmed safety signals or unusual clusters were identified."
                ),
                "limitations": []
            })
        else:
            mock_content = json.dumps({
                "narrative": "Standard regulatory summary generated from approved evidence.",
                "limitations": []
            })

        return LLMResponse(
            content=mock_content,
            model_name="mock-model-v1",
            prompt_tokens=200,
            completion_tokens=80,
            latency_seconds=0.02,
            raw_response={"mock": True}
        )


class OpenAICompatibleLLMClient(LLMClient):
    """
    HTTP client for any OpenAI-compatible API endpoint (OpenAI, OpenRouter, Groq, Ollama, vLLM).
    Uses standard library urllib.request for zero extra dependencies.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model_name: str = "gpt-4o-mini",
        timeout: int = 30,
        max_retries: int = 2,
    ):
        if not api_key:
            raise ValueError("API key must be provided for OpenAICompatibleLLMClient.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout
        self.max_retries = max_retries

    def generate(self, request: LLMRequest) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt}
            ],
            "temperature": request.temperature,
        }

        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        last_error = None
        for attempt in range(self.max_retries + 1):
            start_time = time.time()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    latency = round(time.time() - start_time, 3)
                    body = resp.read().decode("utf-8")
                    result = json.loads(body)

                    choice = result["choices"][0]
                    content = choice["message"]["content"]
                    usage = result.get("usage", {})

                    return LLMResponse(
                        content=content,
                        model_name=result.get("model", self.model_name),
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        latency_seconds=latency,
                        raw_response=result
                    )
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt) # exponential backoff
                continue

        raise RuntimeError(f"LLM API call failed after {self.max_retries + 1} attempts: {last_error}")


def create_llm_client(force_mock: bool = False) -> LLMClient:
    """
    Factory creating the configured LLM client from environment variables.
    If force_mock is True or no LLM_API_KEY is found, returns a MockLLMClient.
    """
    if force_mock:
        return MockLLMClient()

    api_key = os.getenv("LLM_API_KEY")
    if not api_key or api_key.strip() in ("", "your_api_key_here"):
        return MockLLMClient()

    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    model_name = os.getenv("LLM_MODEL", "gpt-4o-mini")
    timeout = int(os.getenv("LLM_TIMEOUT", "30"))
    max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))

    return OpenAICompatibleLLMClient(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        timeout=timeout,
        max_retries=max_retries
    )
