"""Control-Plane indexing concerns — LLM enrichment, sparse input composition."""

from mcp_discovery.indexing.enrichment import (
    EnrichedDescription,
    compute_enrichment_hash,
    enrich_tool,
    rule_based_sparse_input,
)

__all__ = [
    "EnrichedDescription",
    "compute_enrichment_hash",
    "enrich_tool",
    "rule_based_sparse_input",
]
