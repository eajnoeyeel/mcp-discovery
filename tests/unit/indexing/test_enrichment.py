from unittest.mock import AsyncMock

import pytest

from mcp_discovery.indexing.enrichment import (
    EnrichedDescription,
    compute_enrichment_hash,
    enrich_tool,
    rule_based_sparse_input,
)
from mcp_discovery.models import MCPTool


def _tool(**kw):
    """Build a minimal MCPTool. Use input_schema to drive parameter_names (computed field)."""
    defaults = dict(
        tool_id="gmail::send_email",
        server_id="gmail",
        tool_name="send_email",
        description="Sends an email immediately.",
        input_schema={
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            }
        },
    )
    # Allow callers to override input_schema via 'parameter_names' shorthand
    if "parameter_names" in kw:
        param_names = kw.pop("parameter_names")
        if param_names is None:
            kw.setdefault("input_schema", None)
        else:
            kw["input_schema"] = {"properties": {p: {"type": "string"} for p in param_names}}
    return MCPTool(**{**defaults, **kw})


def test_rule_based_sparse_input_format():
    t = _tool()
    s = rule_based_sparse_input(t)
    assert s == "send_email Sends an email immediately. to subject body"


def test_rule_based_sparse_input_handles_missing_params():
    t = _tool(parameter_names=None)
    s = rule_based_sparse_input(t)
    assert "send_email" in s and "Sends" in s


def test_compute_enrichment_hash_stable_across_whitespace():
    t1 = _tool(description="Sends an email immediately.")
    t2 = _tool(description="Sends an email immediately.")
    assert compute_enrichment_hash(t1) == compute_enrichment_hash(t2)


def test_compute_enrichment_hash_changes_when_params_change():
    t1 = _tool(parameter_names=["to", "subject", "body"])
    t2 = _tool(parameter_names=["to", "subject"])
    assert compute_enrichment_hash(t1) != compute_enrichment_hash(t2)


def test_compute_enrichment_hash_changes_when_description_changes():
    t1 = _tool(description="Sends an email immediately.")
    t2 = _tool(description="Sends an email via SMTP.")
    assert compute_enrichment_hash(t1) != compute_enrichment_hash(t2)


@pytest.mark.asyncio
async def test_enrich_tool_composes_sparse_input():
    client = AsyncMock()
    client.chat.completions.create.return_value = AsyncMock(
        choices=[
            AsyncMock(
                message=AsyncMock(
                    content=(
                        '{"function":"send outbound mail",'
                        '"when_to_use":"user asks to deliver a message",'
                        '"tags":["email","smtp"]}'
                    )
                )
            )
        ]
    )
    t = _tool()
    e = await enrich_tool(t, client)
    assert isinstance(e, EnrichedDescription)
    assert e.keyword_prefix == "send_email to subject body"
    assert "send outbound mail" in e.sparse_input
