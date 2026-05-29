"""Tests for LLMVariantGenerator.

Unit tests mock AsyncOpenAI. Integration tests require OPENAI_API_KEY.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_discovery.analytics.token_tracker import TokenTracker
from mcp_discovery.description.base import VendorStyle
from mcp_discovery.description.llm_generator import LLMVariantGenerator


@pytest.fixture
def mock_openai_response() -> MagicMock:
    """Create a mock OpenAI chat completion response."""
    choice = MagicMock()
    choice.message.content = "Optimized description for the tool."
    usage = MagicMock()
    usage.prompt_tokens = 400
    usage.completion_tokens = 150
    usage.total_tokens = 550
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


@pytest.fixture
def tracker(tmp_path: Path) -> TokenTracker:
    return TokenTracker(log_path=tmp_path / "tokens.jsonl")


class TestLLMVariantGenerator:
    @pytest.mark.asyncio
    async def test_generate_returns_all_vendors(
        self, mock_openai_response: MagicMock, tracker: TokenTracker
    ) -> None:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_openai_response)

        generator = LLMVariantGenerator(client=mock_client, token_tracker=tracker)
        variants = await generator.generate(
            tool_id="github::search_repositories",
            tool_name="search_repositories",
            raw_description="Search GitHub repositories.",
            input_schema={"properties": {"query": {"type": "string"}}},
        )

        assert len(variants) == 3
        assert VendorStyle.GEMINI in variants
        assert VendorStyle.CLAUDE in variants
        assert VendorStyle.GPT in variants

    @pytest.mark.asyncio
    async def test_generate_tracks_tokens(
        self, mock_openai_response: MagicMock, tracker: TokenTracker
    ) -> None:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_openai_response)

        generator = LLMVariantGenerator(client=mock_client, token_tracker=tracker)
        await generator.generate(
            tool_id="github::search_repositories",
            tool_name="search_repositories",
            raw_description="Search GitHub repositories.",
        )

        summary = tracker.summary()
        assert summary["total_calls"] == 3  # one per vendor
        assert summary["total_tokens"] == 550 * 3

    @pytest.mark.asyncio
    async def test_variant_has_correct_tool_id(
        self, mock_openai_response: MagicMock, tracker: TokenTracker
    ) -> None:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_openai_response)

        generator = LLMVariantGenerator(client=mock_client, token_tracker=tracker)
        variants = await generator.generate(
            tool_id="slack::send_message",
            tool_name="send_message",
            raw_description="Send a message.",
        )

        for vendor, variant in variants.items():
            assert variant.tool_id == "slack::send_message"
            assert variant.vendor == vendor
            assert variant.token_usage == 550

    @pytest.mark.asyncio
    async def test_parameters_extracted_from_input_schema(
        self, mock_openai_response: MagicMock, tracker: TokenTracker
    ) -> None:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_openai_response)

        generator = LLMVariantGenerator(client=mock_client, token_tracker=tracker)
        await generator.generate(
            tool_id="t::x",
            tool_name="x",
            raw_description="desc",
            input_schema={"properties": {"a": {}, "b": {}, "c": {}}},
        )

        # Verify the prompt contained "a, b, c"
        call_args = mock_client.chat.completions.create.call_args_list[0]
        prompt_content = call_args.kwargs["messages"][0]["content"]
        assert "a, b, c" in prompt_content

    @pytest.mark.asyncio
    async def test_no_input_schema_uses_none_placeholder(
        self, mock_openai_response: MagicMock, tracker: TokenTracker
    ) -> None:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_openai_response)

        generator = LLMVariantGenerator(client=mock_client, token_tracker=tracker)
        await generator.generate(
            tool_id="t::x",
            tool_name="x",
            raw_description="desc",
            input_schema=None,
        )

        call_args = mock_client.chat.completions.create.call_args_list[0]
        prompt_content = call_args.kwargs["messages"][0]["content"]
        assert "(none)" in prompt_content
