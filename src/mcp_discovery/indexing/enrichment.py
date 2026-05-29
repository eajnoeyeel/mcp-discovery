"""Indexing-time enrichment for Keyword+LLM sparse input."""

from __future__ import annotations

import hashlib
import json

from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from mcp_discovery.models import MCPTool  # noqa: E402

_ENRICH_PROMPT = """You analyse an MCP tool and produce a JSON object with keys:
  function (string, 1 sentence describing what it does),
  when_to_use (string, 1 sentence describing the trigger),
  tags (list of short lowercase keywords, 3-8 items, no duplicates).
Only return JSON. Tool:
  name: {tool_name}
  description: {description}
  parameters: {parameter_names}
"""


class EnrichedDescription(BaseModel):
    function: str
    when_to_use: str
    tags: list[str] = Field(default_factory=list)
    keyword_prefix: str
    sparse_input: str
    model: str


def compute_enrichment_hash(tool: MCPTool) -> str:
    params = ",".join(sorted(tool.parameter_names or []))
    payload = f"{tool.tool_id}\n{tool.tool_name}\n{tool.description or ''}\n{params}"
    return hashlib.sha256(payload.encode()).hexdigest()


def rule_based_sparse_input(tool: MCPTool) -> str:
    params = " ".join(tool.parameter_names or [])
    return f"{tool.tool_name} {tool.description or ''} {params}".strip()


async def enrich_tool(
    tool: MCPTool,
    llm_client: AsyncOpenAI,
    *,
    model: str = "gpt-4o-mini",
    timeout_s: float = 10.0,
) -> EnrichedDescription:
    prompt = _ENRICH_PROMPT.format(
        tool_name=tool.tool_name,
        description=tool.description or "",
        parameter_names=", ".join(tool.parameter_names or []),
    )
    logger.info(f"Enriching tool '{tool.tool_id}' with model '{model}'")
    resp = await llm_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        timeout=timeout_s,
    )
    payload = json.loads(resp.choices[0].message.content)
    tags = list(dict.fromkeys(payload.get("tags", [])))
    keyword_prefix = " ".join([tool.tool_name, *(tool.parameter_names or [])])
    sparse_input = " ".join(
        [keyword_prefix, payload["function"], payload["when_to_use"], *tags]
    ).strip()
    return EnrichedDescription(
        function=payload["function"],
        when_to_use=payload["when_to_use"],
        tags=tags,
        keyword_prefix=keyword_prefix,
        sparse_input=sparse_input,
        model=model,
    )
