from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from mcp_discovery.evaluation.metrics import EvalResult, PerQueryResult
from scripts.hybrid_benchmark_utils import (
    DenseBackendSpec,
    SparseBackendSpec,
    arm_config_hash,
    build_precomputed_query_strategy,
    derive_eval_results_by_k,
    instantiate_dense_embedder,
    load_pool_server_ids,
    load_tool_records,
    make_arm_from_cli_args,
    sample_entries,
    sparse_query_cache_key,
)
from scripts.run_hybrid_embedding_benchmark import _arm_k_values


def test_stage1_sample_defaults_to_k3_only() -> None:
    args = Namespace(k_values=None, stage1_sample=True)

    matrix = type("Matrix", (), {"k_values": [3, 5, 10]})()

    assert _arm_k_values(matrix, args) == [3]


def test_k3_is_required_for_stage1_ranking() -> None:
    args = Namespace(k_values=[5, 10], stage1_sample=False)
    matrix = type("Matrix", (), {"k_values": [3, 5, 10]})()

    with pytest.raises(SystemExit, match="K=3 is required"):
        _arm_k_values(matrix, args)


def test_load_pool_server_ids_respects_pool_size(tmp_path: Path) -> None:
    pool_path = tmp_path / "base_pool.json"
    pool_path.write_text(json.dumps(["s1", "s2", "s3"]), encoding="utf-8")

    assert load_pool_server_ids(pool_path, pool_size=2) == ["s1", "s2"]


def test_load_tool_records_filters_by_server_id(tmp_path: Path) -> None:
    input_path = tmp_path / "tools.jsonl"
    records = [
        {
            "server_id": "alpha",
            "tools": [
                {
                    "server_id": "alpha",
                    "tool_name": "search",
                    "tool_id": "alpha::search",
                    "description": "Search alpha",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
        },
        {
            "server_id": "beta",
            "tools": [
                {
                    "server_id": "beta",
                    "tool_name": "list",
                    "tool_id": "beta::list",
                    "description": "List beta",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
        },
    ]
    input_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    loaded = load_tool_records(input_path, server_id_filter={"beta"})

    assert [record.tool.tool_id for record in loaded] == ["beta::list"]


def test_sample_entries_is_deterministic_and_preserves_source_order() -> None:
    entries = list(range(10))

    sampled = sample_entries(entries, max_items=4, sample_seed=7)

    assert sampled == sample_entries(entries, max_items=4, sample_seed=7)
    assert sampled == sorted(sampled)
    assert len(sampled) == 4


def test_arm_config_hash_changes_when_pool_slice_changes() -> None:
    arm = make_arm_from_cli_args(
        arm_id="voyage_test",
        label="Voyage Test",
        dense_provider="voyage",
        dense_model="voyage-4-lite",
        dense_dimension=1024,
        sparse_provider="splade",
        sparse_model="prithivida/Splade_PP_en_v1",
        sparse_text_policy="keyword_llm",
    )

    full_hash = arm_config_hash(
        arm,
        input_path=Path("data/raw/mcp_zero_servers.jsonl"),
        enriched_path=Path("data/enriched/tool_profiles.jsonl"),
        target="local",
        pool_server_ids=None,
    )
    sliced_hash = arm_config_hash(
        arm,
        input_path=Path("data/raw/mcp_zero_servers.jsonl"),
        enriched_path=Path("data/enriched/tool_profiles.jsonl"),
        target="local",
        pool_server_ids=["alpha", "beta"],
    )

    assert full_hash != sliced_hash


def test_voyage_embedder_uses_query_and_document_input_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, Any]] = []

    class FakeVoyageEmbedder:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
    monkeypatch.setattr(
        "mcp_discovery.embedding.voyage_embedder.VoyageEmbedder",
        FakeVoyageEmbedder,
    )

    spec = DenseBackendSpec(
        provider="voyage",
        model="voyage-4-lite",
        dimension=1024,
        env_api_key="VOYAGE_API_KEY",
        query_input_type="query",
        document_input_type="document",
        extra={
            "requests_per_minute": 3,
            "tokens_per_minute": 8000,
            "max_tokens_per_request": 7000,
        },
    )

    instantiate_dense_embedder(spec, settings=object(), input_role="document")
    instantiate_dense_embedder(spec, settings=object(), input_role="query")

    assert created[0]["input_type"] == "document"
    assert created[1]["input_type"] == "query"
    assert created[0]["requests_per_minute"] == 3.0
    assert created[0]["tokens_per_minute"] == 8000
    assert created[0]["max_tokens_per_request"] == 7000


@pytest.mark.asyncio
async def test_precomputed_query_strategy_reuses_embeddings_across_searches() -> None:
    class FakeDenseEmbedder:
        dimension = 2

        def __init__(self) -> None:
            self.calls: list[tuple[list[str], int]] = []

        async def embed_batch(
            self,
            texts: list[str],
            batch_size: int = 50,
        ) -> list[tuple[str, str]]:
            self.calls.append((list(texts), batch_size))
            return [("dense", text) for text in texts]

    class FakeSparseEmbedder:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def embed_batch(self, texts: list[str]) -> list[tuple[str, str]]:
            self.calls.append(list(texts))
            return [("sparse", text) for text in texts]

    class FakeStore:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def hybrid_search(
            self,
            *,
            dense_vector: Any,
            sparse_vector: Any,
            top_k: int,
            prefetch_limit: int,
        ) -> list[Any]:
            self.calls.append(
                {
                    "dense_vector": dense_vector,
                    "sparse_vector": sparse_vector,
                    "top_k": top_k,
                    "prefetch_limit": prefetch_limit,
                }
            )
            return []

    entries = [
        type("Entry", (), {"query": "alpha"})(),
        type("Entry", (), {"query": "beta"})(),
        type("Entry", (), {"query": "alpha"})(),
    ]
    dense = FakeDenseEmbedder()
    sparse = FakeSparseEmbedder()
    store = FakeStore()

    strategy, metadata = await build_precomputed_query_strategy(
        entries=entries,
        dense_embedder=dense,
        sparse_embedder=sparse,
        tool_store=store,
        batch_size=32,
    )

    await strategy.search("alpha", top_k=3)
    await strategy.search("alpha", top_k=10)

    assert dense.calls == [(["alpha", "beta"], 32)]
    assert sparse.calls == [["alpha", "beta"]]
    assert metadata["query_cache_enabled"] is True
    assert metadata["query_cache_unique_queries"] == 2
    assert [call["top_k"] for call in store.calls] == [3, 10]
    assert store.calls[0]["dense_vector"] == ("dense", "alpha")
    assert store.calls[0]["sparse_vector"] == ("sparse", "alpha")


@pytest.mark.asyncio
async def test_precomputed_query_strategy_reuses_supplied_sparse_query_vectors() -> None:
    class FakeDenseEmbedder:
        dimension = 2

        async def embed_batch(
            self,
            texts: list[str],
            batch_size: int = 50,
        ) -> list[tuple[str, str]]:
            return [("dense", text) for text in texts]

    class FailIfCalledSparseEmbedder:
        def embed_batch(self, texts: list[str]) -> list[tuple[str, str]]:
            raise AssertionError("sparse cache should be reused")

    entries = [
        type("Entry", (), {"query": "alpha"})(),
        type("Entry", (), {"query": "beta"})(),
    ]
    sparse_vectors = {
        "alpha": ("cached_sparse", "alpha"),
        "beta": ("cached_sparse", "beta"),
    }

    strategy, metadata = await build_precomputed_query_strategy(
        entries=entries,
        dense_embedder=FakeDenseEmbedder(),
        sparse_embedder=FailIfCalledSparseEmbedder(),
        tool_store=object(),
        batch_size=32,
        precomputed_sparse_query_vectors=sparse_vectors,
    )

    assert strategy.sparse_query_vectors is sparse_vectors
    assert metadata["query_cache_sparse_reused"] is True


def test_sparse_query_cache_key_ignores_dense_arm_identity() -> None:
    first = SparseBackendSpec(provider="splade", model="model-a")
    same = SparseBackendSpec(provider="splade", model="model-a")
    different = SparseBackendSpec(provider="splade", model="model-b")

    assert sparse_query_cache_key(first) == sparse_query_cache_key(same)
    assert sparse_query_cache_key(first) != sparse_query_cache_key(different)


def test_derive_eval_results_by_k_recomputes_recall_from_max_k_result() -> None:
    entries = [
        type(
            "Entry",
            (),
            {
                "query_id": "q1",
                "correct_server_id": "server-a",
                "correct_tool_id": "server-a::correct",
                "alternative_tools": ["server-a::alternative"],
            },
        )(),
        type(
            "Entry",
            (),
            {
                "query_id": "q2",
                "correct_server_id": "server-b",
                "correct_tool_id": "server-b::correct",
                "alternative_tools": None,
            },
        )(),
    ]
    max_result = EvalResult(
        strategy_name="benchmark",
        n_queries=2,
        n_failed=0,
        k_used=5,
        precision_at_1=0.0,
        recall_at_k=0.0,
        mrr=0.0,
        ndcg_at_5=0.0,
        confusion_rate=None,
        ece=None,
        latency_p50=1.0,
        latency_p95=1.0,
        latency_p99=1.0,
        latency_mean=1.0,
        server_recall_at_k=0.0,
        per_query=(
            PerQueryResult(
                query_id="q1",
                top_1_correct=False,
                in_top_k=True,
                rank_of_correct=3,
                confidence=0.8,
                latency_ms=10.0,
                retrieved_tool_ids=(
                    "other::tool",
                    "server-a::alternative",
                    "server-a::correct",
                    "tail::tool",
                ),
            ),
            PerQueryResult(
                query_id="q2",
                top_1_correct=False,
                in_top_k=True,
                rank_of_correct=4,
                confidence=0.7,
                latency_ms=20.0,
                retrieved_tool_ids=(
                    "other::tool",
                    "server-b::related",
                    "other::tool-2",
                    "server-b::correct",
                ),
            ),
        ),
    )

    derived = derive_eval_results_by_k(max_result, entries, [1, 3, 5])

    assert derived[1].recall_at_k == 0.0
    assert derived[3].recall_at_k == 0.5
    assert derived[5].recall_at_k == 1.0
    assert derived[3].mrr == pytest.approx(1 / 3 / 2)
    assert derived[5].mrr == pytest.approx((1 / 3 + 1 / 4) / 2)
    assert derived[3].server_recall_at_k == 1.0
    assert derived[3].per_query[0].retrieved_tool_ids == (
        "other::tool",
        "server-a::alternative",
        "server-a::correct",
    )
