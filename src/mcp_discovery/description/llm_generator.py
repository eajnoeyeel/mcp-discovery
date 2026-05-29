"""LLM-based per-client description variant generator using GPT-4o-mini."""

from __future__ import annotations

import asyncio

from loguru import logger
from openai import AsyncOpenAI

from mcp_discovery.analytics.token_tracker import TokenTracker, TokenUsageEntry
from mcp_discovery.description.base import PerClientVariant, VariantGenerator, VendorStyle
from mcp_discovery.description.templates import format_template

# GPT-4o-mini pricing (as of 2026-04)
_GPT4O_MINI_INPUT_COST_PER_1M = 0.15
_GPT4O_MINI_OUTPUT_COST_PER_1M = 0.60
_MODEL = "gpt-4o-mini"


class LLMVariantGenerator(VariantGenerator):
    """Generate vendor-optimized descriptions using GPT-4o-mini.

    Generates all 3 vendor variants concurrently via asyncio.gather.
    Tracks token usage via TokenTracker.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        token_tracker: TokenTracker | None = None,
        model: str = _MODEL,
    ) -> None:
        self._client = client
        self._tracker = token_tracker
        self._model = model

    async def generate(
        self,
        tool_id: str,
        tool_name: str,
        raw_description: str,
        input_schema: dict | None = None,
    ) -> dict[VendorStyle, PerClientVariant]:
        """Generate per-vendor description variants concurrently."""
        parameters = self._extract_parameters(input_schema)

        tasks = [
            self._generate_single(vendor, tool_id, tool_name, raw_description, parameters)
            for vendor in VendorStyle
        ]
        results = await asyncio.gather(*tasks)

        return {variant.vendor: variant for variant in results}

    async def _generate_single(
        self,
        vendor: VendorStyle,
        tool_id: str,
        tool_name: str,
        raw_description: str,
        parameters: str,
    ) -> PerClientVariant:
        """Generate a single vendor variant."""
        prompt = format_template(
            vendor=vendor,
            tool_name=tool_name,
            raw_description=raw_description,
            parameters=parameters,
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )

        content = response.choices[0].message.content or ""
        usage = response.usage
        total_tokens = usage.total_tokens if usage else 0

        if self._tracker and usage:
            self._tracker.record(
                TokenUsageEntry(
                    operation="variant_generation",
                    model=self._model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    input_cost_per_1m=_GPT4O_MINI_INPUT_COST_PER_1M,
                    output_cost_per_1m=_GPT4O_MINI_OUTPUT_COST_PER_1M,
                    tool_id=tool_id,
                )
            )

        logger.debug(f"Generated {vendor} variant for {tool_id} ({total_tokens} tokens)")

        return PerClientVariant(
            tool_id=tool_id,
            vendor=vendor,
            description=content.strip(),
            token_usage=total_tokens,
        )

    @staticmethod
    def _extract_parameters(input_schema: dict | None) -> str:
        """Extract parameter names from input_schema as comma-separated string."""
        if not input_schema:
            return "(none)"
        props = input_schema.get("properties", {})
        if not props:
            return "(none)"
        return ", ".join(props.keys())
