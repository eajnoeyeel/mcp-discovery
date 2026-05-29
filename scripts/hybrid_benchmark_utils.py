"""Shared utilities for staged hybrid embedding benchmark scripts."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypeVar

from loguru import logger
from qdrant_client import AsyncQdrantClient

try:
    from scripts.enrich_descriptions import _rule_based_enrich
except ModuleNotFoundError:  # pragma: no cover - script execution fallback
    from enrich_descriptions import _rule_based_enrich

from mcp_discovery.config import Settings
from mcp_discovery.data.ground_truth import load_ground_truth
from mcp_discovery.embedding.base import Embedder
from mcp_discovery.embedding.fastembed_sparse import FastEmbedSparseEmbedder
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder
from mcp_discovery.embedding.sparse_embedder import SparseEmbedder
from mcp_discovery.evaluation.harness import evaluate
from mcp_discovery.evaluation.metrics import (
    EvalResult,
    PerQueryResult,
    compute_confusion_rate,
    compute_ece,
    compute_latency_stats,
    compute_mrr,
    compute_precision_at_1,
    compute_recall_at_k,
    compute_server_recall_at_k,
)
from mcp_discovery.models import TOOL_ID_SEPARATOR, GroundTruthEntry, MCPTool, SearchResult
from mcp_discovery.pipeline.flat import FlatStrategy
from mcp_discovery.retrieval.qdrant_store import QdrantStore

DEFAULT_MATRIX_PATH = Path("scripts/hybrid_embedding_benchmark_matrix.json")
DEFAULT_RESULTS_ROOT = Path("data/results/hybrid_embedding_benchmark")
DEFAULT_MANIFESTS_DIR = DEFAULT_RESULTS_ROOT / "manifests"
DEFAULT_COLLECTION_PREFIX = "mcp_tools_hybrid"
DEFAULT_GT_PATH = Path("data/ground_truth/mcp_atlas.jsonl")
DEFAULT_BASE_POOL_PATH = Path("data/tool-pools/base_pool.json")
DEFAULT_INPUT_PATH = Path("data/raw/mcp_zero_servers.jsonl")
DEFAULT_ENRICHED_PATH = Path("data/enriched/tool_profiles.jsonl")
DEFAULT_K_VALUES = [3, 5, 10]
DEFAULT_SPLADE_MODEL = "prithivida/Splade_PP_en_v1"
CONTROL_BASELINE = {
    "recall_at_3": 0.466,
    "precision_at_1": 0.319,
    "confusion_rate": 0.216,
}
CONTROL_PARITY_TOLERANCE_PP = 2.0
STAGE1_RECALL_AMBIGUITY_PP = 1.0
STAGE1_PRECISION_MATERIAL_LOSS_PP = 2.0  # 2.0pp P@1 loss triggers Stage 2.
STAGE2_MAX_PROMOTED_ARMS = 2  # top-2 dense arms advance to Stage 2.
STAGE2_MAX_MEASURED_ARMS = 4
T = TypeVar("T")


class BackendConfigurationError(RuntimeError):
    """Raised when a benchmark arm cannot be instantiated."""


@dataclass(frozen=True)
class ToolRecord:
    tool: MCPTool
    parameter_names: list[str]


@dataclass(frozen=True)
class DenseBackendSpec:
    provider: str
    model: str
    dimension: int
    env_api_key: str | None = None
    query_input_type: str | None = None
    document_input_type: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DenseBackendSpec":
        if "provider" not in payload:
            raise ValueError("missing arm metadata: dense_provider")
        return cls(
            provider=str(payload["provider"]),
            model=str(payload["model"]),
            dimension=int(payload["dimension"]),
            env_api_key=payload.get("env_api_key"),
            query_input_type=payload.get("query_input_type"),
            document_input_type=payload.get("document_input_type"),
            extra=dict(payload.get("extra") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "dimension": self.dimension,
            "env_api_key": self.env_api_key,
            "query_input_type": self.query_input_type,
            "document_input_type": self.document_input_type,
            "extra": self.extra,
        }


@dataclass(frozen=True)
class SparseBackendSpec:
    provider: str
    model: str
    env_api_key: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SparseBackendSpec":
        if "provider" not in payload:
            raise ValueError("missing arm metadata: sparse_provider")
        return cls(
            provider=str(payload["provider"]),
            model=str(payload["model"]),
            env_api_key=payload.get("env_api_key"),
            extra=dict(payload.get("extra") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "env_api_key": self.env_api_key,
            "extra": self.extra,
        }


@dataclass(frozen=True)
class BenchmarkArm:
    arm_id: str
    label: str
    stage: str
    rationale: str
    dense: DenseBackendSpec
    sparse: SparseBackendSpec
    sparse_text_policy: str
    collection_prefix: str = DEFAULT_COLLECTION_PREFIX
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        *,
        default_collection_prefix: str = DEFAULT_COLLECTION_PREFIX,
    ) -> "BenchmarkArm":
        if "arm_id" not in payload:
            raise ValueError("missing arm metadata: arm_slug")
        return cls(
            arm_id=str(payload["arm_id"]),
            label=str(payload.get("label") or payload["arm_id"]),
            stage=str(payload.get("stage") or "stage1"),
            rationale=str(payload.get("rationale") or ""),
            dense=DenseBackendSpec.from_dict(payload["dense"]),
            sparse=SparseBackendSpec.from_dict(payload["sparse"]),
            sparse_text_policy=str(payload["sparse_text_policy"]),
            collection_prefix=str(payload.get("collection_prefix") or default_collection_prefix),
            enabled=bool(payload.get("enabled", True)),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm_id,
            "label": self.label,
            "stage": self.stage,
            "rationale": self.rationale,
            "dense": self.dense.to_dict(),
            "sparse": self.sparse.to_dict(),
            "sparse_text_policy": self.sparse_text_policy,
            "collection_prefix": self.collection_prefix,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class SparseCandidate:
    candidate_id: str
    label: str
    rationale: str
    spec: SparseBackendSpec

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SparseCandidate":
        return cls(
            candidate_id=str(payload["candidate_id"]),
            label=str(payload.get("label") or payload["candidate_id"]),
            rationale=str(payload.get("rationale") or ""),
            spec=SparseBackendSpec.from_dict(payload["spec"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "label": self.label,
            "rationale": self.rationale,
            "spec": self.spec.to_dict(),
        }


@dataclass(frozen=True)
class SparseTextPolicyOption:
    policy: str
    label: str
    rationale: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SparseTextPolicyOption":
        return cls(
            policy=str(payload["policy"]),
            label=str(payload.get("label") or payload["policy"]),
            rationale=str(payload.get("rationale") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "label": self.label,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class BenchmarkMatrix:
    experiment_id: str
    description: str
    input_path: Path
    enriched_path: Path
    target: str
    collection_prefix: str
    k_values: list[int]
    control_arm_id: str
    stage1_arms: list[BenchmarkArm]
    stage2a_sparse_candidates: list[SparseCandidate]
    stage2b_sparse_text_policies: list[SparseTextPolicyOption]
    control_baseline: dict[str, float]
    stage_rules: dict[str, Any]

    def get_arm(self, arm_id: str) -> BenchmarkArm:
        for arm in self.stage1_arms:
            if arm.arm_id == arm_id:
                return arm
        raise KeyError(f"Unknown arm_id '{arm_id}' in matrix")

    def control_arm(self) -> BenchmarkArm:
        return self.get_arm(self.control_arm_id)


@dataclass(frozen=True)
class ArmBuildResult:
    collection_name: str
    manifest_path: Path
    config_hash: str
    reused: bool
    dense_text_source: str
    sparse_text_source: str
    sparse_fallback_count: int
    tool_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection_name": self.collection_name,
            "manifest_path": str(self.manifest_path),
            "config_hash": self.config_hash,
            "reused": self.reused,
            "dense_text_source": self.dense_text_source,
            "sparse_text_source": self.sparse_text_source,
            "sparse_fallback_count": self.sparse_fallback_count,
            "tool_count": self.tool_count,
        }


@dataclass
class ArmEvaluationResult:
    arm: BenchmarkArm
    collection_name: str
    manifest_path: Path | None
    config_hash: str
    status: str
    note: str | None
    results_by_k: dict[int, EvalResult] = field(default_factory=dict)
    build: ArmBuildResult | None = None
    reused_from_arm_id: str | None = None
    runtime_seconds: float | None = None
    eval_metadata: dict[str, Any] = field(default_factory=dict)

    def metrics_at(self, k: int) -> EvalResult | None:
        return self.results_by_k.get(k)

    def is_measured(self) -> bool:
        return self.status == "measured"

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm.to_dict(),
            "collection_name": self.collection_name,
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "config_hash": self.config_hash,
            "status": self.status,
            "note": self.note,
            "results_by_k": {
                str(k): eval_result_to_dict(result)
                for k, result in sorted(self.results_by_k.items())
            },
            "build": self.build.to_dict() if self.build else None,
            "reused_from_arm_id": self.reused_from_arm_id,
            "runtime_seconds": self.runtime_seconds,
            "eval_metadata": self.eval_metadata,
        }


def _optional_dependency_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "arm"


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_benchmark_matrix(matrix_path: Path = DEFAULT_MATRIX_PATH) -> BenchmarkMatrix:
    payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    experiment = payload.get("experiment") or {}
    data_sources = payload.get("data_sources") or {}
    control_baseline = dict(payload.get("control_baseline") or CONTROL_BASELINE)
    stage_rules = dict(payload.get("stage_rules") or {})
    collection_prefix = str(
        experiment.get("collection_prefix")
        or payload.get("collection_prefix")
        or DEFAULT_COLLECTION_PREFIX
    )

    return BenchmarkMatrix(
        experiment_id=str(experiment.get("id") or payload["experiment_id"]),
        description=str(experiment.get("description") or ""),
        input_path=Path(str(data_sources.get("input_path") or DEFAULT_INPUT_PATH)),
        enriched_path=Path(str(data_sources.get("enriched_path") or DEFAULT_ENRICHED_PATH)),
        target=str(data_sources.get("target") or "local"),
        collection_prefix=collection_prefix,
        k_values=[int(value) for value in (payload.get("k_values") or DEFAULT_K_VALUES)],
        control_arm_id=str(payload["control_arm_id"]),
        stage1_arms=[
            parsed_arm
            for arm in payload.get("stage1_dense_arms", [])
            if (parsed_arm := BenchmarkArm.from_dict(
                arm,
                default_collection_prefix=collection_prefix,
            )).enabled
        ],
        stage2a_sparse_candidates=[
            SparseCandidate.from_dict(candidate)
            for candidate in payload.get("stage2a_sparse_candidates", [])
        ],
        stage2b_sparse_text_policies=[
            SparseTextPolicyOption.from_dict(option)
            for option in payload.get("stage2b_sparse_text_policies", [])
        ],
        control_baseline={key: float(value) for key, value in control_baseline.items()},
        stage_rules=stage_rules,
    )


def make_arm_from_cli_args(
    *,
    arm_id: str,
    label: str,
    dense_provider: str,
    dense_model: str,
    dense_dimension: int,
    sparse_provider: str,
    sparse_model: str,
    sparse_text_policy: str,
    stage: str = "manual",
    rationale: str = "",
    collection_prefix: str = DEFAULT_COLLECTION_PREFIX,
) -> BenchmarkArm:
    return BenchmarkArm(
        arm_id=arm_id,
        label=label,
        stage=stage,
        rationale=rationale,
        dense=DenseBackendSpec(
            provider=dense_provider,
            model=dense_model,
            dimension=dense_dimension,
            query_input_type="query" if dense_provider == "voyage" else None,
            document_input_type="document" if dense_provider == "voyage" else None,
        ),
        sparse=SparseBackendSpec(provider=sparse_provider, model=sparse_model),
        sparse_text_policy=sparse_text_policy,
        collection_prefix=collection_prefix,
    )


def load_tool_records(
    input_path: Path,
    *,
    server_id_filter: set[str] | None = None,
) -> list[ToolRecord]:
    records: list[ToolRecord] = []
    no_desc_count = 0

    with input_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(f"Line {line_number}: JSON parse error — {exc}")
                continue

            for tool_dict in record.get("tools") or []:
                try:
                    schema = tool_dict.get("input_schema") or {}
                    properties = schema.get("properties") or {}
                    parameter_names = list(tool_dict.get("parameter_names") or properties.keys())
                    tool = MCPTool(
                        tool_id=tool_dict["tool_id"],
                        server_id=tool_dict["server_id"],
                        tool_name=tool_dict["tool_name"],
                        description=tool_dict.get("description"),
                        input_schema=schema,
                    )
                except (KeyError, Exception) as exc:
                    logger.warning(f"Line {line_number}: skipping tool — {exc}")
                    continue

                if server_id_filter is not None and tool.server_id not in server_id_filter:
                    continue
                if not tool.description:
                    no_desc_count += 1
                records.append(ToolRecord(tool=tool, parameter_names=parameter_names))

    logger.info(
        f"Loaded {len(records)} tools from {input_path} ({no_desc_count} without description)"
    )
    return records


def load_enriched_texts(enriched_path: Path) -> dict[str, str]:
    enriched: dict[str, str] = {}
    if not enriched_path.exists():
        logger.warning(f"Enriched file not found: {enriched_path} — sparse will use original text")
        return enriched

    with enriched_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                enriched[str(record["tool_id"])] = str(record["enriched_text"])
            except (KeyError, json.JSONDecodeError) as exc:
                logger.warning(f"Enriched line {line_number}: parse error — {exc}")
                continue

    logger.info(f"Loaded {len(enriched)} enriched descriptions from {enriched_path}")
    return enriched


def build_rule_only_text(record: ToolRecord) -> str:
    enriched = _rule_based_enrich(
        {
            "tool_id": record.tool.tool_id,
            "tool_name": record.tool.tool_name,
            "description": record.tool.description or "",
            "parameter_names": record.parameter_names,
        }
    )
    return str(enriched["enriched_text"])


def build_sparse_texts(
    records: list[ToolRecord],
    *,
    sparse_text_policy: str,
    enriched_path: Path,
) -> tuple[list[str], str, int]:
    original_texts = [QdrantStore.build_tool_text(record.tool) for record in records]

    if sparse_text_policy == "raw_original":
        return original_texts, "raw_original", 0

    if sparse_text_policy == "rule_only":
        return [build_rule_only_text(record) for record in records], "rule_only", 0

    if sparse_text_policy != "keyword_llm":
        raise ValueError(f"Unsupported sparse_text_policy '{sparse_text_policy}'")

    enriched_map = load_enriched_texts(enriched_path)
    texts = [
        enriched_map.get(record.tool.tool_id, original)
        for record, original in zip(records, original_texts)
    ]
    fallback_count = sum(1 for record in records if record.tool.tool_id not in enriched_map)
    if fallback_count:
        logger.info(
            f"{fallback_count}/{len(records)} tools using original text for sparse "
            "(no enriched_text found)"
        )
    return texts, str(enriched_path), fallback_count


def build_dense_texts(records: list[ToolRecord]) -> list[str]:
    return [QdrantStore.build_tool_text(record.tool) for record in records]


def get_qdrant_config(target: str, settings: Settings) -> tuple[str, str]:
    if target == "prod":
        return os.environ["PROD_QDRANT_URL"], os.environ["PROD_QDRANT_API_KEY"]
    if target == "staging":
        return os.environ["STAGING_QDRANT_URL"], os.environ["STAGING_QDRANT_API_KEY"]
    return (
        settings.qdrant_url or os.environ.get("QDRANT_URL", "http://localhost:6333"),
        settings.qdrant_api_key or os.environ.get("QDRANT_API_KEY", ""),
    )


def arm_backend_requirements(arm: BenchmarkArm) -> list[str]:
    requirements: list[str] = []
    if arm.dense.provider == "openai":
        requirements.append("OPENAI_API_KEY")
    elif arm.dense.provider == "voyage":
        requirements.append(arm.dense.env_api_key or "VOYAGE_API_KEY")
        requirements.append("httpx")
    elif arm.dense.provider == "bge_m3":
        requirements.append("FlagEmbedding")
        requirements.append("local model download for BAAI/bge-m3")

    if arm.sparse.provider == "splade":
        requirements.append("fastembed")
    elif arm.sparse.provider == "bge_m3":
        requirements.append("FlagEmbedding")
        requirements.append("local model download for BAAI/bge-m3")

    if arm.sparse_text_policy == "keyword_llm":
        requirements.append(str(DEFAULT_ENRICHED_PATH))
    return requirements


def check_arm_backend_availability(
    arm: BenchmarkArm,
    settings: Settings,
) -> tuple[bool, str | None]:
    if arm.dense.provider == "openai" and not settings.openai_api_key:
        return False, "OPENAI_API_KEY is required for dense provider 'openai'"

    if arm.dense.provider == "voyage":
        env_name = arm.dense.env_api_key or "VOYAGE_API_KEY"
        if not os.getenv(env_name):
            return False, f"{env_name} is required for dense provider 'voyage'"

    if arm.dense.provider == "bge_m3" and not _optional_dependency_available("FlagEmbedding"):
        return False, "FlagEmbedding is required for dense provider 'bge_m3'"

    if arm.sparse.provider == "splade" and not _optional_dependency_available("fastembed"):
        return False, "fastembed is required for sparse provider 'splade'"

    if arm.sparse.provider == "bge_m3" and not _optional_dependency_available("FlagEmbedding"):
        return False, "FlagEmbedding is required for sparse provider 'bge_m3'"

    if arm.sparse_text_policy == "keyword_llm" and not DEFAULT_ENRICHED_PATH.exists():
        return False, f"keyword_llm sparse policy requires {DEFAULT_ENRICHED_PATH}"

    return True, None


def maybe_build_bge_m3_backend(
    dense_spec: DenseBackendSpec,
    sparse_spec: SparseBackendSpec | None = None,
) -> Any | None:
    if dense_spec.provider != "bge_m3":
        return None
    if sparse_spec is not None and sparse_spec.provider != "bge_m3":
        return None
    if sparse_spec is not None and sparse_spec.model != dense_spec.model:
        return None

    use_fp16 = bool(dense_spec.extra.get("use_fp16", True))
    batch_size = int(dense_spec.extra.get("batch_size", 12))
    max_length = int(dense_spec.extra.get("max_length", 8192))
    try:
        from mcp_discovery.embedding.bge_m3_backend import BGEM3HybridBackend
    except ImportError as exc:
        raise BackendConfigurationError(
            "BGE-M3 backend is unavailable. Install FlagEmbedding and required "
            "provider dependencies before running BGE-M3 arms."
        ) from exc
    return BGEM3HybridBackend(
        model=dense_spec.model,
        use_fp16=use_fp16,
        default_batch_size=batch_size,
        max_length=max_length,
    )


def instantiate_dense_embedder(
    spec: DenseBackendSpec,
    settings: Settings,
    *,
    bge_backend: Any | None = None,
    input_role: Literal["document", "query"] = "document",
) -> Embedder:
    if spec.provider == "openai":
        if not settings.openai_api_key:
            raise BackendConfigurationError(
                "OPENAI_API_KEY is required for dense provider 'openai'"
            )
        return OpenAIEmbedder(
            api_key=settings.openai_api_key,
            model=spec.model,
            dimension=spec.dimension,
        )

    if spec.provider == "voyage":
        env_name = spec.env_api_key or "VOYAGE_API_KEY"
        api_key = os.getenv(env_name)
        if not api_key:
            raise BackendConfigurationError(
                f"{env_name} is required for dense provider 'voyage'"
            )
        try:
            from mcp_discovery.embedding.voyage_embedder import VoyageEmbedder
        except ImportError as exc:
            raise BackendConfigurationError(
                "Voyage backend is unavailable. Install voyage provider "
                "dependencies before running Voyage arms."
            ) from exc
        input_type = (
            spec.query_input_type
            if input_role == "query"
            else spec.document_input_type
        )
        return VoyageEmbedder(
            api_key=api_key,
            model=spec.model,
            dimension=spec.dimension,
            input_type=input_type or None,
            truncation=bool(spec.extra.get("truncation", True)),
            max_retries=int(spec.extra.get("max_retries", 0)),
            timeout=spec.extra.get("timeout_seconds"),
            requests_per_minute=(
                float(spec.extra["requests_per_minute"])
                if spec.extra.get("requests_per_minute") is not None
                else None
            ),
            tokens_per_minute=(
                int(spec.extra["tokens_per_minute"])
                if spec.extra.get("tokens_per_minute") is not None
                else None
            ),
            max_tokens_per_request=(
                int(spec.extra["max_tokens_per_request"])
                if spec.extra.get("max_tokens_per_request") is not None
                else None
            ),
        )

    if spec.provider == "bge_m3":
        backend = bge_backend or maybe_build_bge_m3_backend(spec)
        if backend is None:
            raise BackendConfigurationError("Unable to initialize BGE-M3 dense backend")
        dense_embedder = backend.build_dense_embedder()
        if dense_embedder.dimension != spec.dimension:
            raise BackendConfigurationError(
                f"BGE-M3 dimension mismatch: requested {spec.dimension}, backend produced "
                f"{dense_embedder.dimension}"
            )
        return dense_embedder

    raise BackendConfigurationError(f"Unsupported dense provider '{spec.provider}'")


def instantiate_sparse_embedder(
    spec: SparseBackendSpec,
    *,
    bge_backend: Any | None = None,
) -> SparseEmbedder:
    if spec.provider == "splade":
        return FastEmbedSparseEmbedder(model=spec.model)

    if spec.provider == "bge_m3":
        backend = bge_backend
        if backend is None:
            from mcp_discovery.embedding.bge_m3_backend import BGEM3HybridBackend

            backend = BGEM3HybridBackend(
                model=spec.model,
                use_fp16=bool(spec.extra.get("use_fp16", True)),
                default_batch_size=int(spec.extra.get("batch_size", 12)),
                max_length=int(spec.extra.get("max_length", 8192)),
            )
        return backend.build_sparse_embedder()

    raise BackendConfigurationError(f"Unsupported sparse provider '{spec.provider}'")


async def maybe_close_embedder(embedder: Embedder) -> None:
    close_method = getattr(embedder, "aclose", None)
    if close_method is not None:
        await close_method()


class PrecomputedHybridStrategy:
    """Benchmark-only strategy that reuses precomputed query embeddings across K runs."""

    name = "PrecomputedHybridStrategy"

    def __init__(
        self,
        *,
        tool_store: QdrantStore,
        dense_query_vectors: dict[str, Any],
        sparse_query_vectors: dict[str, Any] | None = None,
        reranker: Any | None = None,
    ) -> None:
        self.tool_store = tool_store
        self.dense_query_vectors = dense_query_vectors
        self.sparse_query_vectors = sparse_query_vectors
        self.reranker = reranker

    async def search(self, query: str, top_k: int) -> list[SearchResult]:
        if top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")
        try:
            dense_vector = self.dense_query_vectors[query]
        except KeyError as exc:
            raise KeyError("Query vector was not precomputed for benchmark evaluation") from exc

        if self.sparse_query_vectors is not None:
            try:
                sparse_vector = self.sparse_query_vectors[query]
            except KeyError as exc:
                raise KeyError("Sparse query vector was not precomputed") from exc
            results = await self.tool_store.hybrid_search(
                dense_vector=dense_vector,
                sparse_vector=sparse_vector,
                top_k=top_k,
                prefetch_limit=max(20, top_k * 3),
            )
        else:
            results = await self.tool_store.search(
                query_vector=dense_vector,
                top_k=top_k,
                server_id_filter=None,
            )

        if self.reranker is not None:
            results = await self.reranker.rerank(query, results, top_k)
        return results


async def _embed_sparse_queries_in_batches(
    sparse_embedder: SparseEmbedder,
    unique_queries: list[str],
    *,
    batch_size: int,
) -> list[Any]:
    all_vectors: list[Any] = []
    effective_batch_size = max(1, batch_size)
    total_batches = (len(unique_queries) + effective_batch_size - 1) // effective_batch_size
    for batch_number, start in enumerate(
        range(0, len(unique_queries), effective_batch_size),
        start=1,
    ):
        end = min(start + effective_batch_size, len(unique_queries))
        logger.info(
            f"Precomputing sparse query vectors: batch {batch_number}/{total_batches} "
            f"[{start + 1}-{end}/{len(unique_queries)}]"
        )
        batch_vectors = await asyncio.to_thread(
            sparse_embedder.embed_batch,
            unique_queries[start:end],
        )
        all_vectors.extend(batch_vectors)
    return all_vectors


async def build_precomputed_query_strategy(
    *,
    entries: list[GroundTruthEntry],
    dense_embedder: Embedder,
    sparse_embedder: SparseEmbedder | None,
    tool_store: QdrantStore,
    batch_size: int,
    precomputed_sparse_query_vectors: dict[str, Any] | None = None,
) -> tuple[PrecomputedHybridStrategy, dict[str, Any]]:
    unique_queries = list(dict.fromkeys(entry.query for entry in entries))
    logger.info(
        f"Precomputing dense query vectors: n_unique={len(unique_queries)} "
        f"batch_size={batch_size} dimension={getattr(dense_embedder, 'dimension', None)}"
    )
    dense_started = time.perf_counter()
    dense_vectors = await dense_embedder.embed_batch(unique_queries, batch_size=batch_size)
    dense_seconds = time.perf_counter() - dense_started
    dense_by_query = dict(zip(unique_queries, dense_vectors, strict=True))
    logger.info(
        f"Precomputed dense query vectors: n_unique={len(unique_queries)} "
        f"seconds={dense_seconds:.1f}"
    )

    sparse_by_query: dict[str, Any] | None = None
    sparse_seconds: float | None = None
    if sparse_embedder is not None:
        if precomputed_sparse_query_vectors is not None:
            sparse_by_query = precomputed_sparse_query_vectors
            logger.info(
                f"Reusing sparse query vectors: n_unique={len(precomputed_sparse_query_vectors)}"
            )
        else:
            logger.info(f"Precomputing sparse query vectors: n_unique={len(unique_queries)}")
            sparse_started = time.perf_counter()
            sparse_vectors = await _embed_sparse_queries_in_batches(
                sparse_embedder,
                unique_queries,
                batch_size=batch_size,
            )
            sparse_seconds = time.perf_counter() - sparse_started
            sparse_by_query = dict(zip(unique_queries, sparse_vectors, strict=True))
            logger.info(
                f"Precomputed sparse query vectors: n_unique={len(unique_queries)} "
                f"seconds={sparse_seconds:.1f}"
            )

    metadata = {
        "query_cache_enabled": True,
        "query_cache_unique_queries": len(unique_queries),
        "query_cache_dense_batch_size": batch_size,
        "query_cache_dense_seconds": dense_seconds,
        "query_cache_sparse_seconds": sparse_seconds,
        "query_cache_sparse_reused": precomputed_sparse_query_vectors is not None,
        "query_cache_dense_dimension": getattr(dense_embedder, "dimension", None),
    }
    strategy = PrecomputedHybridStrategy(
        tool_store=tool_store,
        dense_query_vectors=dense_by_query,
        sparse_query_vectors=sparse_by_query,
    )
    return strategy, metadata


def _server_id_from_tool_id(tool_id: str) -> str:
    if TOOL_ID_SEPARATOR not in tool_id:
        return ""
    return tool_id.rsplit(TOOL_ID_SEPARATOR, maxsplit=1)[0]


def sparse_query_cache_key(spec: SparseBackendSpec) -> str:
    payload = json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _compute_ndcg_at_5_from_tool_ids(
    retrieved_tool_ids: tuple[str, ...],
    entry: GroundTruthEntry,
) -> float:
    cutoff = 5
    alternative_ids = set(entry.alternative_tools or [])

    def grade(tool_id: str) -> int:
        if tool_id == entry.correct_tool_id:
            return 2
        if tool_id in alternative_ids:
            return 1
        return 0

    dcg = sum(
        grade(retrieved_tool_ids[i]) / math.log2(i + 2)
        for i in range(min(cutoff, len(retrieved_tool_ids)))
    )
    ideal_grades = sorted([2] + [1] * len(alternative_ids), reverse=True)[:cutoff]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal_grades))
    return dcg / idcg if idcg > 0 else 0.0


def _truncate_per_query_result(
    source: PerQueryResult,
    entry: GroundTruthEntry,
    *,
    top_k: int,
) -> PerQueryResult:
    retrieved_tool_ids = source.retrieved_tool_ids[:top_k]
    rank_of_correct = None
    for idx, tool_id in enumerate(retrieved_tool_ids):
        if tool_id == entry.correct_tool_id:
            rank_of_correct = idx + 1
            break

    return PerQueryResult(
        query_id=source.query_id,
        top_1_correct=bool(retrieved_tool_ids and retrieved_tool_ids[0] == entry.correct_tool_id),
        in_top_k=rank_of_correct is not None,
        rank_of_correct=rank_of_correct,
        confidence=source.confidence,
        latency_ms=source.latency_ms,
        retrieved_tool_ids=retrieved_tool_ids,
        correct_server_in_top_k=any(
            _server_id_from_tool_id(tool_id) == entry.correct_server_id
            for tool_id in retrieved_tool_ids
        ),
    )


def derive_eval_results_by_k(
    max_k_result: EvalResult,
    entries: list[GroundTruthEntry],
    k_values: list[int],
) -> dict[int, EvalResult]:
    entries_by_query_id = {entry.query_id: entry for entry in entries}
    derived: dict[int, EvalResult] = {}

    for k in sorted(k_values):
        per_query: list[PerQueryResult] = []
        ndcg_scores: list[float] = []
        confidences: list[float] = []
        correct_flags: list[bool] = []
        latencies_ms: list[float] = []

        for source in max_k_result.per_query:
            entry = entries_by_query_id[source.query_id]
            truncated = _truncate_per_query_result(source, entry, top_k=k)
            per_query.append(truncated)
            ndcg_scores.append(
                _compute_ndcg_at_5_from_tool_ids(truncated.retrieved_tool_ids, entry)
            )
            confidences.append(truncated.confidence)
            correct_flags.append(truncated.top_1_correct)
            latencies_ms.append(truncated.latency_ms)

        p50, p95, p99, mean_lat = compute_latency_stats(latencies_ms)
        derived[k] = EvalResult(
            strategy_name=max_k_result.strategy_name,
            n_queries=max_k_result.n_queries,
            n_failed=max_k_result.n_failed,
            k_used=k,
            precision_at_1=compute_precision_at_1(per_query),
            recall_at_k=compute_recall_at_k(per_query),
            mrr=compute_mrr(per_query),
            ndcg_at_5=sum(ndcg_scores) / len(ndcg_scores) if ndcg_scores else 0.0,
            confusion_rate=compute_confusion_rate(per_query),
            ece=compute_ece(confidences, correct_flags),
            latency_p50=p50,
            latency_p95=p95,
            latency_p99=p99,
            latency_mean=mean_lat,
            server_recall_at_k=compute_server_recall_at_k(per_query),
            per_query=tuple(per_query),
        )

    return derived


def pool_server_hash(pool_server_ids: list[str] | None) -> str | None:
    if not pool_server_ids:
        return None
    digest = hashlib.sha1("\n".join(pool_server_ids).encode("utf-8")).hexdigest()
    return digest[:10]


def build_arm_manifest_payload(
    arm: BenchmarkArm,
    *,
    collection_name: str,
    config_hash: str,
    input_path: Path,
    enriched_path: Path,
    sparse_text_source: str,
    dense_text_source: str,
    sparse_fallback_count: int,
    tool_count: int,
    target: str,
    pool_server_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "arm_id": arm.arm_id,
        "label": arm.label,
        "stage": arm.stage,
        "collection_name": collection_name,
        "config_hash": config_hash,
        "dense": arm.dense.to_dict(),
        "sparse": arm.sparse.to_dict(),
        "sparse_text_policy": arm.sparse_text_policy,
        "dense_text_source": dense_text_source,
        "sparse_text_source": sparse_text_source,
        "sparse_fallback_count": sparse_fallback_count,
        "tool_count": tool_count,
        "input_path": str(input_path),
        "enriched_path": str(enriched_path),
        "target": target,
        "pool_server_count": len(pool_server_ids) if pool_server_ids is not None else None,
        "pool_server_ids_hash": pool_server_hash(pool_server_ids),
        "metadata": arm.metadata,
    }


def arm_config_hash(
    arm: BenchmarkArm,
    *,
    input_path: Path,
    enriched_path: Path,
    target: str,
    pool_server_ids: list[str] | None = None,
) -> str:
    payload = {
        "arm": arm.to_dict(),
        "input_path": str(input_path),
        "enriched_path": str(enriched_path),
        "target": target,
        "pool_server_ids": pool_server_ids,
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    return digest[:10]


def deterministic_collection_name(
    arm: BenchmarkArm,
    *,
    input_path: Path,
    enriched_path: Path,
    target: str,
    pool_server_ids: list[str] | None = None,
) -> tuple[str, str]:
    config_hash = arm_config_hash(
        arm,
        input_path=input_path,
        enriched_path=enriched_path,
        target=target,
        pool_server_ids=pool_server_ids,
    )
    slug = _slugify(arm.arm_id)
    return f"{arm.collection_prefix}_{slug}_{config_hash}", config_hash


async def qdrant_collection_exists(client: AsyncQdrantClient, collection_name: str) -> bool:
    collections = await client.get_collections()
    return collection_name in {item.name for item in collections.collections}


async def build_or_reuse_arm_collection(
    *,
    arm: BenchmarkArm,
    settings: Settings,
    input_path: Path,
    enriched_path: Path,
    target: str,
    qdrant_client: AsyncQdrantClient,
    batch_size: int,
    manifest_dir: Path,
    pool_server_ids: list[str] | None = None,
    force_rebuild: bool = False,
    dry_run: bool = False,
) -> ArmBuildResult:
    records = load_tool_records(
        input_path,
        server_id_filter=set(pool_server_ids) if pool_server_ids is not None else None,
    )
    if not records:
        raise RuntimeError("No tools loaded from input JSONL")

    collection_name, config_hash = deterministic_collection_name(
        arm,
        input_path=input_path,
        enriched_path=enriched_path,
        target=target,
        pool_server_ids=pool_server_ids,
    )
    manifest_path = manifest_dir / f"{collection_name}.json"
    dense_texts = build_dense_texts(records)
    sparse_texts, sparse_text_source, sparse_fallback_count = build_sparse_texts(
        records,
        sparse_text_policy=arm.sparse_text_policy,
        enriched_path=enriched_path,
    )
    requested_manifest = build_arm_manifest_payload(
        arm,
        collection_name=collection_name,
        config_hash=config_hash,
        input_path=input_path,
        enriched_path=enriched_path,
        sparse_text_source=sparse_text_source,
        dense_text_source="tool_name_plus_description",
        sparse_fallback_count=sparse_fallback_count,
        tool_count=len(records),
        target=target,
        pool_server_ids=pool_server_ids,
    )

    if dry_run:
        return ArmBuildResult(
            collection_name=collection_name,
            manifest_path=manifest_path,
            config_hash=config_hash,
            reused=False,
            dense_text_source="tool_name_plus_description",
            sparse_text_source=sparse_text_source,
            sparse_fallback_count=sparse_fallback_count,
            tool_count=len(records),
        )

    manifest_dir.mkdir(parents=True, exist_ok=True)
    collection_exists = await qdrant_collection_exists(qdrant_client, collection_name)
    existing_manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if not force_rebuild and collection_exists and existing_manifest == requested_manifest:
        logger.info(f"Reusing '{collection_name}' — manifest matches requested arm config")
        return ArmBuildResult(
            collection_name=collection_name,
            manifest_path=manifest_path,
            config_hash=config_hash,
            reused=True,
            dense_text_source="tool_name_plus_description",
            sparse_text_source=sparse_text_source,
            sparse_fallback_count=sparse_fallback_count,
            tool_count=len(records),
        )

    if collection_exists:
        logger.info(f"Deleting stale collection '{collection_name}' before rebuild")
        await qdrant_client.delete_collection(collection_name=collection_name)
    if manifest_path.exists():
        manifest_path.unlink()

    bge_backend = maybe_build_bge_m3_backend(arm.dense, arm.sparse)
    dense_embedder = instantiate_dense_embedder(arm.dense, settings, bge_backend=bge_backend)
    sparse_embedder = instantiate_sparse_embedder(arm.sparse, bge_backend=bge_backend)
    store = QdrantStore(client=qdrant_client, collection_name=collection_name)

    try:
        await store.ensure_hybrid_collection(dense_dimension=arm.dense.dimension)
        for batch_start in range(0, len(records), batch_size):
            batch_end = min(batch_start + batch_size, len(records))
            batch_records = records[batch_start:batch_end]
            logger.info(
                f"Indexing {arm.arm_id}: batch {batch_start // batch_size + 1} "
                f"[{batch_start + 1}-{batch_end}/{len(records)}]"
            )
            batch_dense_inputs = dense_texts[batch_start:batch_end]
            batch_sparse_inputs = sparse_texts[batch_start:batch_end]
            if (
                bge_backend is not None
                and arm.sparse.provider == "bge_m3"
                and arm.sparse_text_policy == "raw_original"
            ):
                # Reuse one BGE-M3 encode pass when dense and sparse inputs are identical.
                hybrid_batch = await bge_backend.embed_hybrid_batch(
                    batch_dense_inputs,
                    batch_size=batch_size,
                )
                batch_dense = hybrid_batch.dense_vectors
                batch_sparse = hybrid_batch.sparse_vectors
            else:
                batch_dense = await dense_embedder.embed_batch(
                    batch_dense_inputs,
                    batch_size=batch_size,
                )
                batch_sparse = sparse_embedder.embed_batch(batch_sparse_inputs)
            extra_payloads = [
                {
                    "benchmark_arm_id": arm.arm_id,
                    "benchmark_config_hash": config_hash,
                    "benchmark_sparse_text_policy": arm.sparse_text_policy,
                }
                for _ in batch_records
            ]
            await store.upsert_tools_hybrid(
                [record.tool for record in batch_records],
                batch_dense,
                batch_sparse,
                extra_payloads=extra_payloads,
            )
    finally:
        await maybe_close_embedder(dense_embedder)

    manifest_path.write_text(_json_dump(requested_manifest), encoding="utf-8")
    logger.info(
        f"Built '{collection_name}' for arm '{arm.arm_id}' "
        f"(dense={arm.dense.provider}:{arm.dense.model}, "
        f"sparse={arm.sparse.provider}:{arm.sparse.model})"
    )
    return ArmBuildResult(
        collection_name=collection_name,
        manifest_path=manifest_path,
        config_hash=config_hash,
        reused=False,
        dense_text_source="tool_name_plus_description",
        sparse_text_source=sparse_text_source,
        sparse_fallback_count=sparse_fallback_count,
        tool_count=len(records),
    )


def load_pool_server_ids(
    base_pool_path: Path = DEFAULT_BASE_POOL_PATH,
    *,
    pool_size: int | None = None,
) -> list[str]:
    ordered: list[str] = json.loads(base_pool_path.read_text(encoding="utf-8"))
    if pool_size is not None:
        ordered = ordered[:pool_size]
    logger.info(f"Loaded {len(ordered)}-server pool from {base_pool_path}")
    return ordered


def sample_entries(
    entries: list[T],
    *,
    max_items: int | None = None,
    sample_seed: int = 42,
) -> list[T]:
    if max_items is None or max_items >= len(entries):
        return list(entries)
    if max_items < 1:
        raise ValueError("max_items must be >= 1 when provided")
    rng = random.Random(sample_seed)
    sampled_indices = sorted(rng.sample(range(len(entries)), k=max_items))
    return [entries[index] for index in sampled_indices]


def load_and_filter_gt(
    pool_server_ids: list[str],
    gt_path: Path = DEFAULT_GT_PATH,
    *,
    max_queries: int | None = None,
    sample_seed: int = 42,
) -> list[GroundTruthEntry]:
    if not gt_path.exists():
        logger.error(f"GT file not found: {gt_path}")
        return []
    entries = load_ground_truth(gt_path)
    pool_set = set(pool_server_ids)
    filtered = [entry for entry in entries if entry.correct_server_id in pool_set]
    sampled = sample_entries(filtered, max_items=max_queries, sample_seed=sample_seed)
    if max_queries is not None and max_queries < len(filtered):
        logger.info(
            f"GT sample: {len(sampled)}/{len(filtered)} queries "
            f"(seed={sample_seed}, bounded for rate-limit-safe runs)"
        )
    logger.info(f"GT: {len(entries)} total, {len(filtered)} covered by pool")
    return sampled


def eval_result_to_dict(result: EvalResult) -> dict[str, Any]:
    return {
        "precision_at_1": result.precision_at_1,
        "recall_at_k": result.recall_at_k,
        "server_recall_at_k": result.server_recall_at_k,
        "mrr": result.mrr,
        "ndcg_at_5": result.ndcg_at_5,
        "confusion_rate": result.confusion_rate,
        "latency_p50": result.latency_p50,
        "latency_p95": result.latency_p95,
        "latency_mean": result.latency_mean,
        "n_queries": result.n_queries,
        "n_failed": result.n_failed,
    }


async def run_hybrid_eval_for_arm(
    *,
    arm: BenchmarkArm,
    settings: Settings,
    qdrant_client: AsyncQdrantClient,
    pool_server_ids: list[str],
    entries: list[GroundTruthEntry],
    k_values: list[int],
    collection_name: str,
    batch_size: int = 50,
    precompute_query_vectors: bool = True,
    metadata_out: dict[str, Any] | None = None,
    sparse_query_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[int, EvalResult]:
    bge_backend = maybe_build_bge_m3_backend(arm.dense, arm.sparse)
    dense_embedder = instantiate_dense_embedder(
        arm.dense,
        settings,
        bge_backend=bge_backend,
        input_role="query",
    )
    sparse_embedder = instantiate_sparse_embedder(arm.sparse, bge_backend=bge_backend)
    store = QdrantStore(
        client=qdrant_client,
        collection_name=collection_name,
        pool_server_ids=pool_server_ids,
    )

    try:
        if precompute_query_vectors:
            sparse_cache_key = None
            precomputed_sparse_query_vectors = None
            if sparse_embedder is not None and sparse_query_cache is not None:
                sparse_cache_key = sparse_query_cache_key(arm.sparse)
                precomputed_sparse_query_vectors = sparse_query_cache.get(sparse_cache_key)
            strategy, metadata = await build_precomputed_query_strategy(
                entries=entries,
                dense_embedder=dense_embedder,
                sparse_embedder=sparse_embedder,
                tool_store=store,
                batch_size=batch_size,
                precomputed_sparse_query_vectors=precomputed_sparse_query_vectors,
            )
            if sparse_cache_key is not None:
                metadata["query_cache_sparse_key"] = sparse_cache_key
                if (
                    precomputed_sparse_query_vectors is None
                    and strategy.sparse_query_vectors is not None
                ):
                    sparse_query_cache[sparse_cache_key] = strategy.sparse_query_vectors
        else:
            metadata = {"query_cache_enabled": False}
            strategy = FlatStrategy(
                embedder=dense_embedder,
                tool_store=store,
                reranker=None,
                sparse_embedder=sparse_embedder,
            )
        if metadata_out is not None:
            metadata_out.update(metadata)
        sorted_k_values = sorted(k_values)
        max_k = max(sorted_k_values)
        logger.info(
            f"Running {arm.arm_id} once with K={max_k}; deriving metrics for K={sorted_k_values}"
        )
        max_k_result = await evaluate(strategy, entries, top_k=max_k)
        results = derive_eval_results_by_k(max_k_result, entries, sorted_k_values)
        if metadata_out is not None:
            metadata_out.update(
                {
                    "single_max_k_pass": True,
                    "single_max_k_source_k": max_k,
                    "single_max_k_derived_k_values": sorted_k_values,
                }
            )
        return results
    finally:
        await maybe_close_embedder(dense_embedder)


def control_parity_summary(
    result: ArmEvaluationResult,
    *,
    baseline: dict[str, float] | None = None,
    tolerance_pp: float = CONTROL_PARITY_TOLERANCE_PP,
) -> dict[str, Any]:
    k3 = result.metrics_at(3)
    if k3 is None:
        raise ValueError("Control parity requires Recall@3 results")

    baseline_payload = baseline or CONTROL_BASELINE
    recall_delta_pp = (k3.recall_at_k - baseline_payload["recall_at_3"]) * 100.0
    precision_delta_pp = (k3.precision_at_1 - baseline_payload["precision_at_1"]) * 100.0
    confusion_delta_pp = (k3.confusion_rate - baseline_payload["confusion_rate"]) * 100.0
    passed = (
        abs(recall_delta_pp) <= tolerance_pp
        and abs(precision_delta_pp) <= tolerance_pp
    )
    return {
        "passed": passed,
        "baseline": baseline_payload,
        "measured": {
            "recall_at_3": k3.recall_at_k,
            "precision_at_1": k3.precision_at_1,
            "confusion_rate": k3.confusion_rate,
        },
        "delta_pp": {
            "recall_at_3": recall_delta_pp,
            "precision_at_1": precision_delta_pp,
            "confusion_rate": confusion_delta_pp,
        },
        "tolerance_pp": tolerance_pp,
    }


def ranking_tuple(result: ArmEvaluationResult) -> tuple[float, float, float, float, str]:
    k3 = result.metrics_at(3)
    if k3 is None:
        raise ValueError(f"Ranking requires Recall@3 metrics for arm '{result.arm.arm_id}'")
    return (
        -k3.recall_at_k,
        -k3.precision_at_1,
        -k3.mrr,
        k3.latency_p50,
        result.arm.arm_id,
    )


def rank_measured_results(results: list[ArmEvaluationResult]) -> list[ArmEvaluationResult]:
    measured = [result for result in results if result.is_measured()]
    return sorted(measured, key=ranking_tuple)


def ambiguity_trigger(results: list[ArmEvaluationResult]) -> dict[str, Any]:
    ranked = rank_measured_results(results)
    if len(ranked) < 2:
        return {"triggered": False, "reason": "fewer than two measured arms"}

    best = ranked[0].metrics_at(3)
    runner_up = ranked[1].metrics_at(3)
    if best is None or runner_up is None:
        return {"triggered": False, "reason": "missing Recall@3 metrics"}

    recall_gap_pp = (best.recall_at_k - runner_up.recall_at_k) * 100.0
    precision_gap_pp = (runner_up.precision_at_1 - best.precision_at_1) * 100.0

    recall_close = abs(recall_gap_pp) <= STAGE1_RECALL_AMBIGUITY_PP
    precision_loss = precision_gap_pp >= STAGE1_PRECISION_MATERIAL_LOSS_PP
    triggered = recall_close or precision_loss

    if recall_close and precision_loss:
        reason = "top Recall@3 arms are within 1.0pp and best-recall arm trails on P@1"
    elif recall_close:
        reason = "top Recall@3 arms are within 1.0pp"
    elif precision_loss:
        reason = "best-recall arm loses materially on P@1"
    else:
        reason = "stage ambiguity threshold not met"

    return {
        "triggered": triggered,
        "reason": reason,
        "recall_gap_pp": recall_gap_pp,
        "precision_gap_pp": precision_gap_pp,
        "best_arm_id": ranked[0].arm.arm_id,
        "runner_up_arm_id": ranked[1].arm.arm_id,
    }


def promoted_stage1_arms(results: list[ArmEvaluationResult]) -> list[ArmEvaluationResult]:
    return rank_measured_results(results)[:STAGE2_MAX_PROMOTED_ARMS]


def make_stage2a_arms(
    promoted: list[ArmEvaluationResult],
    matrix: BenchmarkMatrix,
) -> list[BenchmarkArm]:
    arms: list[BenchmarkArm] = []
    for promoted_result in promoted:
        dense = promoted_result.arm.dense
        for candidate in matrix.stage2a_sparse_candidates:
            arm_id = f"stage2a_{promoted_result.arm.arm_id}_{candidate.candidate_id}_keyword_llm"
            arms.append(
                BenchmarkArm(
                    arm_id=arm_id,
                    label=f"{promoted_result.arm.label} + {candidate.label}",
                    stage="stage2a",
                    rationale=(
                        f"Stage 2A sparse-encoder playoff from '{promoted_result.arm.arm_id}'. "
                        f"{candidate.rationale}"
                    ),
                    dense=dense,
                    sparse=candidate.spec,
                    sparse_text_policy="keyword_llm",
                    collection_prefix=matrix.collection_prefix,
                    metadata={
                        "promoted_from": promoted_result.arm.arm_id,
                        "sparse_candidate_id": candidate.candidate_id,
                    },
                )
            )
    return arms


def make_stage2b_arms(
    winning_stage2a: ArmEvaluationResult,
    matrix: BenchmarkMatrix,
) -> list[BenchmarkArm]:
    arms: list[BenchmarkArm] = []
    for option in matrix.stage2b_sparse_text_policies:
        arm_id = (
            f"stage2b_{winning_stage2a.arm.arm_id}_{_slugify(option.policy)}"
        )
        arms.append(
            BenchmarkArm(
                arm_id=arm_id,
                label=f"{winning_stage2a.arm.label} / {option.label}",
                stage="stage2b",
                rationale=(
                    "Stage 2B sparse-text ablation under the winning Stage 2A encoder. "
                    f"{option.rationale}"
                ),
                dense=winning_stage2a.arm.dense,
                sparse=winning_stage2a.arm.sparse,
                sparse_text_policy=option.policy,
                collection_prefix=matrix.collection_prefix,
                metadata={
                    "stage2a_winner": winning_stage2a.arm.arm_id,
                    "sparse_text_policy_option": option.policy,
                },
            )
        )
    return arms


def result_summary_row(result: ArmEvaluationResult) -> dict[str, Any]:
    k3 = result.metrics_at(3)
    return {
        "arm_id": result.arm.arm_id,
        "stage": result.arm.stage,
        "status": result.status,
        "collection_name": result.collection_name,
        "dense_provider": result.arm.dense.provider,
        "dense_model": result.arm.dense.model,
        "dense_dimension": result.arm.dense.dimension,
        "sparse_provider": result.arm.sparse.provider,
        "sparse_model": result.arm.sparse.model,
        "sparse_text_policy": result.arm.sparse_text_policy,
        "recall_at_3": None if k3 is None else k3.recall_at_k,
        "precision_at_1": None if k3 is None else k3.precision_at_1,
        "mrr": None if k3 is None else k3.mrr,
        "latency_p50": None if k3 is None else k3.latency_p50,
        "failure_count": None if k3 is None else k3.n_failed,
        "note": result.note,
    }


def measured_stage_rows(results: list[ArmEvaluationResult]) -> list[dict[str, Any]]:
    return [result_summary_row(result) for result in results]


def format_results_table(results: list[ArmEvaluationResult]) -> str:
    lines = [
        "| Arm | Stage | Status | R@3 | P@1 | MRR | Lat p50 | Sparse Text | Collection |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        k3 = result.metrics_at(3)
        recall = "n/a" if k3 is None else f"{k3.recall_at_k:.3f}"
        precision = "n/a" if k3 is None else f"{k3.precision_at_1:.3f}"
        mrr = "n/a" if k3 is None else f"{k3.mrr:.3f}"
        latency = "n/a" if k3 is None else f"{k3.latency_p50:.1f}ms"
        lines.append(
            f"| {result.arm.arm_id} | {result.arm.stage} | {result.status} | "
            f"{recall} | {precision} | {mrr} | {latency} | "
            f"{result.arm.sparse_text_policy} | {result.collection_name} |"
        )
    return "\n".join(lines)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dump(payload), encoding="utf-8")


def create_artifact_dir(results_root: Path = DEFAULT_RESULTS_ROOT) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = results_root / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def format_parity_failure_notes(
    *,
    control_result: ArmEvaluationResult,
    parity_summary: dict[str, Any],
) -> list[str]:
    baseline = parity_summary["baseline"]
    lines = [
        "Control parity gate failed.",
        f"Measured control arm: {control_result.arm.arm_id}",
        (
            "Recall@3 delta: "
            f"{parity_summary['delta_pp']['recall_at_3']:+.2f}pp "
            f"(target {baseline['recall_at_3']:.3f})"
        ),
        (
            "P@1 delta: "
            f"{parity_summary['delta_pp']['precision_at_1']:+.2f}pp "
            f"(target {baseline['precision_at_1']:.3f})"
        ),
        (
            "Confusion delta: "
            f"{parity_summary['delta_pp']['confusion_rate']:+.2f}pp "
            f"(reference {baseline['confusion_rate']:.3f})"
        ),
    ]
    if control_result.build is not None:
        lines.append(
            f"Sparse fallback count during build: {control_result.build.sparse_fallback_count}"
        )
        lines.append(
            f"Manifest path: {control_result.build.manifest_path}"
        )
    return lines
