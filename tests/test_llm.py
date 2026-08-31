"""Tests for LLMProvider implementations (Groq openai/gpt-oss-120b and Mock)."""

import pytest
from unittest.mock import MagicMock, patch
from agent.llm.provider import GroqLLMProvider, MockLLMProvider, get_llm_provider
from agent.config import settings


def test_mock_llm_provider():
    llm = MockLLMProvider()
    text = llm.complete("Hello world")
    assert isinstance(text, str)
    assert len(text) > 0

    theme_res = llm.complete_json("Cluster these headlines into themes")
    assert "themes" in theme_res
    assert len(theme_res["themes"]) > 0

    hedge_res = llm.complete_json("Evaluate downside risk overlay exposure shape")
    assert "exposure_shape" in hedge_res


def test_groq_llm_provider_initialization():
    provider = GroqLLMProvider(model="openai/gpt-oss-120b", reasoning_effort="medium")
    assert provider.model == "openai/gpt-oss-120b"
    assert provider.reasoning_effort == "medium"


def test_groq_llm_provider_streaming_collection():
    """Verifies that GroqLLMProvider properly aggregates streamed chunks into a single string."""
    provider = GroqLLMProvider(api_key="test-dummy-groq-key-12345")

    # Mock chunk structure from Groq SDK streaming
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock(delta=MagicMock(content='{"themes": ['))]
    chunk2 = MagicMock()
    chunk2.choices = [MagicMock(delta=MagicMock(content='{"name": "AI Hardware", "tickers": ["NVDA"]}]}'))]

    mock_completion = [chunk1, chunk2]

    with patch.object(provider.client.chat.completions, "create", return_value=mock_completion) as mock_create:
        result_text = provider.complete("Cluster news")
        assert result_text == '{"themes": [{"name": "AI Hardware", "tickers": ["NVDA"]}]}'

        # Verify streaming parameter and reasoning_effort were passed
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["stream"] is True
        assert call_kwargs["model"] == "openai/gpt-oss-120b"
        assert call_kwargs["reasoning_effort"] == "medium"
        assert call_kwargs["temperature"] == 1
        assert call_kwargs["max_completion_tokens"] == 2048


def test_groq_llm_provider_complete_json_parsing():
    """Verifies complete_json handles raw JSON, markdown fences, and extraction."""
    provider = GroqLLMProvider(api_key="test-dummy-groq-key-12345")

    # 1. Test markdown code fences stripping
    chunk_fenced = MagicMock()
    chunk_fenced.choices = [MagicMock(delta=MagicMock(content='```json\n{"status": "success", "val": 42}\n```'))]

    with patch.object(provider.client.chat.completions, "create", return_value=[chunk_fenced]):
        data = provider.complete_json("Test prompt")
        assert data["status"] == "success"
        assert data["val"] == 42

    # 2. Test JSON with preamble text
    chunk_preamble = MagicMock()
    chunk_preamble.choices = [MagicMock(delta=MagicMock(content='Here is your analysis:\n{"exposure_shape": "downside_risk", "reasoning": "High vol"}\nDone.'))]

    with patch.object(provider.client.chat.completions, "create", return_value=[chunk_preamble]):
        data2 = provider.complete_json("Test prompt")
        assert data2["exposure_shape"] == "downside_risk"
