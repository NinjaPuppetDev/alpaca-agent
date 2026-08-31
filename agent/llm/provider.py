"""LLM Provider interface and implementations (Groq with openai/gpt-oss-120b & Mock fallback).

Wraps LLM operations behind an abstract interface so models, streaming behavior,
or reasoning parameters can be updated without modifying layer business logic.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import json
import re
import os
import logging
from agent.config import settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract interface for LLM operations."""

    @abstractmethod
    def complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate text completion from a prompt."""
        pass

    @abstractmethod
    def complete_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Generate structured JSON completion from a prompt."""
        pass


class GroqLLMProvider(LLMProvider):
    """Groq implementation using openai/gpt-oss-120b with streamed chunk aggregation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None
    ):
        self.api_key = api_key or settings.GROQ_API_KEY or os.environ.get("GROQ_API_KEY")
        self.model = model or settings.LLM_MODEL
        self.reasoning_effort = reasoning_effort or settings.LLM_REASONING_EFFORT

        try:
            from groq import Groq
            # If api_key is specified, pass it explicitly; otherwise Groq() picks up GROQ_API_KEY from env
            if self.api_key and len(self.api_key.strip()) > 5:
                self.client = Groq(api_key=self.api_key.strip())
            else:
                self.client = Groq()
        except Exception as e:
            logger.warning(f"Could not initialize Groq client: {e}")
            self.client = None

    def complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generates text completion using Groq streaming client, collecting chunks into a single response."""
        has_key = bool(self.api_key and len(self.api_key.strip()) > 5) or bool(os.environ.get("GROQ_API_KEY"))
        if not self.client or not has_key:
            logger.warning("Groq API key not set or client unavailable; falling back to MockLLMProvider.")
            return MockLLMProvider().complete(prompt, system_prompt)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": 1,
                "max_completion_tokens": 2048,
                "top_p": 1,
                "stream": True,
                "stop": None
            }
            if self.reasoning_effort:
                kwargs["reasoning_effort"] = self.reasoning_effort

            completion = self.client.chat.completions.create(**kwargs)

            collected = []
            for chunk in completion:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    collected.append(chunk.choices[0].delta.content)

            return "".join(collected).strip()

        except Exception as e:
            logger.error(f"Error during Groq streamed completion: {e}. Falling back to MockLLMProvider.")
            return MockLLMProvider().complete(prompt, system_prompt)

    def complete_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Generates structured JSON completion with streamed chunk aggregation and robust JSON parsing."""
        has_key = bool(self.api_key and len(self.api_key.strip()) > 5) or bool(os.environ.get("GROQ_API_KEY"))
        if not self.client or not has_key:
            logger.warning("Groq API key not set; falling back to MockLLMProvider.")
            return MockLLMProvider().complete_json(prompt, system_prompt)

        json_sys_prompt = (
            (system_prompt or "") + "\nRespond strictly with a valid JSON object. Do not include markdown code fences or conversational text outside the JSON."
        ).strip()

        raw_output = self.complete(prompt=prompt, system_prompt=json_sys_prompt)

        # 1. Direct JSON parse attempt
        try:
            return json.loads(raw_output)
        except json.JSONDecodeError:
            pass

        # 2. Strip markdown fences if present
        try:
            cleaned = raw_output.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 3. Regex search for outermost JSON object
        try:
            match = re.search(r"\{.*\}", raw_output, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            logger.warning(f"Failed to regex-parse JSON from Groq output: {e}. Output was: {raw_output[:200]}")

        # 4. Fallback to mock structured output if unparsable
        logger.warning(f"Could not parse valid JSON from {self.model} output. Using mock fallback structure.")
        return MockLLMProvider().complete_json(prompt, system_prompt)


class MockLLMProvider(LLMProvider):
    """Deterministic Mock LLM provider for tests, local demos, and fallback."""

    def complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        return "Mock LLM analysis: market risk indicates standard risk hedging."

    def complete_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        prompt_lower = prompt.lower()
        if "theme" in prompt_lower or "cluster" in prompt_lower:
            return {
                "themes": [
                    {
                        "name": "Semiconductors & AI Hardware",
                        "description": "Surging demand for GPU infrastructure and custom silicon accelerators.",
                        "tickers": ["NVDA", "AMD", "TSM", "AVGO"]
                    },
                    {
                        "name": "Clean Energy & Critical Materials",
                        "description": "Grid expansion and battery storage demand boosting copper, lithium, and uranium.",
                        "tickers": ["FCX", "CCJ", "ALB", "NEE"]
                    }
                ],
                "reasoning": "Clustered top macro and tech headlines into AI compute infrastructure and energy transition."
            }
        elif "hedge" in prompt_lower or "overlay" in prompt_lower or "exposure" in prompt_lower:
            return {
                "exposure_shape": "downside_risk",
                "structure_type": "protective_put",
                "reasoning": "Elevated news volatility and high negative delta confirmed by negative VWAP divergence.",
                "target_delta": -0.30,
                "days_to_expiration": 21
            }
        elif "expiration" in prompt_lower or "roll" in prompt_lower:
            return {
                "action": "roll",
                "target_dte": 21,
                "reasoning": "Position has reached 4 DTE threshold; rolling out to 21 DTE to maintain downside buffer."
            }
        return {"status": "ok", "reasoning": "Mock processed successfully."}


def get_llm_provider() -> LLMProvider:
    """Returns the configured LLM provider based on environment settings."""
    api_key = settings.GROQ_API_KEY or os.environ.get("GROQ_API_KEY")
    if api_key and len(api_key.strip()) > 5:
        return GroqLLMProvider()
    return MockLLMProvider()
