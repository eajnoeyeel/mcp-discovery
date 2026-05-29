"""Provider-scoped dashboard read service."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from pydantic import ValidationError as PydanticValidationError

from service.services.contracts import ParameterMetadataEntry, UpstreamAuthConfig
from service.services.metadata_diff_service import MetadataDiffService
from service.services.metadata_discovery_service import MetadataDiscoveryService
from service.services.parameter_metadata import merge_parameter_descriptions
from service.shared.param_metadata_telemetry import emit_drop_warning
from service.validation.description_rules import validate_description


def _weighted_success_rate(tools: list[dict]) -> float:
    total_calls = 0
    total_successes = 0.0
    for tool in tools:
        calls = int(tool.get("call_count") or 0)
        rate = tool.get("success_rate")
        if calls > 0 and rate is not None:
            total_calls += calls
            total_successes += float(rate) * calls
    if total_calls == 0:
        return 0.0
    return round(total_successes / total_calls, 4)


def _geo_total(tool: dict) -> float:
    geo = tool.get("geo_score") or {}
    if not isinstance(geo, dict):
        return 0.0
    return float(geo.get("total", 0.0))


class DashboardService:
    def __init__(
        self,
        repo,
        metadata_discovery_service: MetadataDiscoveryService | None = None,
        metadata_diff_service: MetadataDiffService | None = None,
    ) -> None:
        self._repo = repo
        self._metadata_discovery_service = metadata_discovery_service or MetadataDiscoveryService()
        self._metadata_diff_service = metadata_diff_service or MetadataDiffService()

    async def get_provider_dashboard(
        self, provider_id: str, owner_user_id: str | None = None
    ) -> dict:
        tools = await self._repo.fetch_provider_dashboard_tools(provider_id, owner_user_id)
        if not tools and owner_user_id:
            tools = await self._repo.fetch_owned_dashboard_tools(owner_user_id)
        scored = [tool for tool in tools if tool.get("geo_score")]
        avg_geo_score = (
            round(sum(_geo_total(tool) for tool in scored) / len(scored), 4) if scored else 0.0
        )
        total_exposures = sum(int(tool.get("times_exposed") or 0) for tool in tools)
        total_recommendations = sum(int(tool.get("times_selected") or 0) for tool in tools)
        selection_rate = (
            round(total_recommendations / total_exposures, 4) if total_exposures > 0 else 0.0
        )
        latencies = [
            float(tool["avg_latency_ms"])
            for tool in tools
            if tool.get("avg_latency_ms") is not None
        ]
        p95_latencies = [
            float(tool["p95_latency_ms"])
            for tool in tools
            if tool.get("p95_latency_ms") is not None
        ]

        # Fetch exposure and conversion metrics from migration-022 views.
        # Queried per tool then aggregated — tolerated N+1 since provider dashboards
        # typically have <50 tools. Gracefully degrades to None when views are absent.
        tool_ids = [tool["tool_id"] for tool in tools if tool.get("tool_id")]
        exposure_count, conversion_stats = await asyncio.gather(
            self._fetch_provider_exposure_count(tool_ids),
            self._fetch_provider_conversion_stats(tool_ids),
        )

        total_execution_count = sum(int(tool.get("call_count") or 0) for tool in tools)
        recommendation_count = conversion_stats.get("recommendation_count")
        converted_count = conversion_stats.get("converted_count")
        if recommendation_count is not None and recommendation_count > 0:
            conversion_rate = round(converted_count / recommendation_count, 4)
        else:
            conversion_rate = None

        summary = {
            "total_tools": len(tools),
            "avg_geo_score": avg_geo_score,
            "needs_improvement": sum(1 for tool in scored if _geo_total(tool) < 0.5),
            "indexed_count": sum(1 for tool in tools if tool.get("index_status") == "indexed"),
            "recommendation_rate": selection_rate,
            "recommendation_count": total_recommendations,
            "exposure_count": exposure_count,
            "execution_count": total_execution_count,
            "conversion_rate": conversion_rate,
            "times_exposed": total_exposures,
            "call_count": total_execution_count,
            "success_rate": _weighted_success_rate(tools),
            "avg_latency": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "avg_p95_latency": (
                round(sum(p95_latencies) / len(p95_latencies), 2) if p95_latencies else None
            ),
        }
        sorted_tools = sorted(tools, key=_geo_total)
        return {"summary": summary, "tools": sorted_tools}

    async def _fetch_provider_exposure_count(self, tool_ids: list[str]) -> int | None:
        """Sum exposure counts across all provider tool IDs.

        Returns None if the repo does not support fetch_tool_exposure_count
        (view absent in test environments without migration 022).
        """
        if not tool_ids or not hasattr(self._repo, "fetch_tool_exposure_count"):
            return None
        try:
            counts = await asyncio.gather(
                *[self._repo.fetch_tool_exposure_count(tid) for tid in tool_ids],
                return_exceptions=True,
            )
            total = 0
            for c in counts:
                if isinstance(c, Exception):
                    logger.warning(f"fetch_tool_exposure_count error: {c}")
                else:
                    total += int(c)
            return total
        except Exception as exc:
            logger.warning(f"_fetch_provider_exposure_count failed: {exc}")
            return None

    async def _fetch_provider_conversion_stats(self, tool_ids: list[str]) -> dict:
        """Aggregate conversion funnel stats across all provider tool IDs.

        Returns dict with recommendation_count and converted_count keys.
        Returns None values when repo method is unavailable (migration 022 absent).
        """
        if not tool_ids or not hasattr(self._repo, "fetch_tool_conversion_stats"):
            return {"recommendation_count": None, "converted_count": None}
        try:
            results = await asyncio.gather(
                *[self._repo.fetch_tool_conversion_stats(tid) for tid in tool_ids],
                return_exceptions=True,
            )
            total_recs = 0
            total_conv = 0
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"fetch_tool_conversion_stats error: {r}")
                elif not isinstance(r, dict):
                    logger.warning(
                        "fetch_tool_conversion_stats returned non-dict payload; "
                        f"ignoring type={type(r).__name__}"
                    )
                else:
                    total_recs += int(r.get("recommendation_count") or 0)
                    total_conv += int(r.get("converted_count") or 0)
            return {"recommendation_count": total_recs, "converted_count": total_conv}
        except Exception as exc:
            logger.warning(f"_fetch_provider_conversion_stats failed: {exc}")
            return {"recommendation_count": None, "converted_count": None}

    async def get_provider_tool_detail(
        self,
        tool_id: str,
        owner_user_id: str | None = None,
        provider_id: str | None = None,
    ) -> dict:
        tool = await self._resolve_visible_tool(
            tool_id,
            owner_user_id=owner_user_id,
            provider_id=provider_id,
        )
        if tool is None:
            raise LookupError("Provider tool not found")
        tool = {
            **tool,
            "effective_input_schema": merge_parameter_descriptions(
                tool.get("input_schema"),
                tool.get("published_parameter_metadata"),
            ),
        }
        if owner_user_id:
            competitors = await self._repo.fetch_owned_server_tools(
                owner_user_id,
                tool["server_id"],
                exclude_tool_id=tool_id,
            )
        else:
            competitors = []
        simulations = await self._repo.fetch_tool_simulations(tool_id)
        return {
            "tool": tool,
            "competitors": competitors,
            "simulations": simulations,
        }

    async def get_tool_analytics(
        self,
        tool_id: str,
        owner_user_id: str | None = None,
        provider_id: str | None = None,
    ) -> dict:
        if owner_user_id or provider_id:
            tool = await self._resolve_visible_tool(
                tool_id,
                owner_user_id=owner_user_id,
                provider_id=provider_id,
            )
            if tool is None:
                raise LookupError("Provider tool not found")
        daily_stats, client_stats, client_selection_stats = await asyncio.gather(
            self._repo.fetch_tool_daily_stats(tool_id),
            self._repo.fetch_tool_client_stats(tool_id),
            self._repo.fetch_tool_client_selection_stats(tool_id),
        )
        return {
            "tool_id": tool_id,
            "daily_stats": daily_stats,
            "client_stats": client_stats,
            "client_selection_stats": client_selection_stats,
        }

    async def update_provider_tool_metadata(
        self,
        tool_id: str,
        *,
        owner_user_id: str,
        provider_id: str | None = None,
        payload: dict[str, Any],
    ) -> dict:
        current_tool = await self._resolve_visible_tool(
            tool_id,
            owner_user_id=owner_user_id,
            provider_id=provider_id,
        )
        if current_tool is None:
            raise LookupError("Provider tool not found")

        merged_description = payload.get("description", current_tool.get("description", ""))
        if "description" in payload and (err := validate_description(merged_description)):
            raise ValueError(err)
        merged_parameter_notes = payload.get("parameter_notes", current_tool.get("parameter_notes"))
        merged_usage_examples = self._normalize_list_field(
            payload.get("usage_examples", current_tool.get("usage_examples"))
        )
        merged_usage_hints = self._normalize_list_field(
            payload.get("usage_hints", current_tool.get("usage_hints"))
        )
        merged_published_parameter_metadata = self._normalize_published_parameter_metadata(
            payload.get(
                "published_parameter_metadata",
                current_tool.get("published_parameter_metadata"),
            ),
            context="dashboard_update",
            server_id=tool_id.split("::", 1)[0] if "::" in tool_id else None,
        )
        metadata_origin = self._derive_metadata_origin(
            description=merged_description,
            upstream_description=current_tool.get("upstream_description"),
            parameter_notes=merged_parameter_notes,
            usage_examples=merged_usage_examples,
            usage_hints=merged_usage_hints,
            published_parameter_metadata=merged_published_parameter_metadata,
        )

        update_payload = {
            key: value
            for key, value in {
                "description": payload.get("description"),
                "parameter_notes": payload.get("parameter_notes"),
                "usage_examples": (
                    self._normalize_list_field(payload.get("usage_examples"))
                    if "usage_examples" in payload
                    else None
                ),
                "usage_hints": (
                    self._normalize_list_field(payload.get("usage_hints"))
                    if "usage_hints" in payload
                    else None
                ),
                "published_parameter_metadata": (
                    self._normalize_published_parameter_metadata(
                        payload.get("published_parameter_metadata"),
                        context="dashboard_update",
                        server_id=tool_id.split("::", 1)[0] if "::" in tool_id else None,
                    )
                    if "published_parameter_metadata" in payload
                    else None
                ),
                "metadata_origin": metadata_origin,
            }.items()
            if value is not None
        }

        updated = await self._repo.update_tool_metadata_override(tool_id, update_payload)
        if updated is None:
            raise LookupError("Provider tool not found")
        return updated

    async def preview_provider_tool_refresh(
        self,
        tool_id: str,
        *,
        owner_user_id: str,
        provider_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict:
        refresh_context = await self._build_refresh_context(
            tool_id,
            owner_user_id=owner_user_id,
            provider_id=provider_id,
            payload=payload,
        )
        preview = refresh_context["preview"].model_dump()
        warnings = self._refresh_preview_warnings(refresh_context)
        if warnings:
            preview["warnings"] = warnings
        return preview

    async def apply_provider_tool_refresh(
        self,
        tool_id: str,
        *,
        owner_user_id: str,
        provider_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict:
        refresh_context = await self._build_refresh_context(
            tool_id,
            owner_user_id=owner_user_id,
            provider_id=provider_id,
            payload=payload,
        )
        tool = refresh_context["tool"]
        fresh_by_name = refresh_context["fresh_by_name"]
        fresh_tool = fresh_by_name.get(tool["tool_name"])
        if fresh_tool is None:
            raise ValueError("Registered tool not found in upstream discovery result")

        fresh_upstream_description = fresh_tool.get("upstream_description") or ""
        effective_description = tool.get("description") or ""
        if tool.get("metadata_origin") == "discovered" or tool.get("upstream_description") in (
            None,
            "",
            effective_description,
        ):
            effective_description = fresh_upstream_description

        metadata_origin = self._derive_metadata_origin(
            description=effective_description,
            upstream_description=fresh_upstream_description,
            parameter_notes=tool.get("parameter_notes"),
            usage_examples=self._normalize_list_field(tool.get("usage_examples")),
            usage_hints=self._normalize_list_field(tool.get("usage_hints")),
            published_parameter_metadata=self._normalize_published_parameter_metadata(
                tool.get("published_parameter_metadata"),
                context="dashboard_refresh",
                server_id=tool_id.split("::", 1)[0] if "::" in tool_id else None,
            ),
        )
        updated = await self._repo.apply_tool_metadata_refresh(
            tool_id,
            {
                "description": effective_description,
                "upstream_description": fresh_upstream_description,
                "input_schema": fresh_tool.get("input_schema"),
                "upstream_parameter_metadata": self._normalize_upstream_parameter_metadata(
                    fresh_tool.get("upstream_parameter_metadata")
                    or fresh_tool.get("parameter_metadata"),
                    context="dashboard_refresh",
                    server_id=tool_id.split("::", 1)[0] if "::" in tool_id else None,
                ),
                "metadata_origin": metadata_origin,
                "metadata_last_fetched_at": self._timestamp(),
            },
        )
        if updated is None:
            raise LookupError("Provider tool not found")

        preview = refresh_context["preview"].model_dump()
        warnings = self._refresh_preview_warnings(refresh_context)
        if warnings:
            preview["warnings"] = warnings
        return {"tool": updated, "preview": preview}

    async def _resolve_visible_tool(
        self,
        tool_id: str,
        *,
        owner_user_id: str | None = None,
        provider_id: str | None = None,
    ) -> dict[str, Any] | None:
        if owner_user_id:
            tool = await self._repo.fetch_owned_tool_detail(owner_user_id, tool_id)
            if tool is not None:
                return tool

        if provider_id:
            tool = await self._repo.fetch_tool(tool_id)
            if tool is None:
                return None
            # Provider dashboard: owner sees their own unpublished servers too.
            server = await self._repo.fetch_server(tool["server_id"], public_only=False)
            if server is None or server.get("provider_id") != provider_id:
                return None
            return {
                **tool,
                "server_name": server["name"],
                "server_url": server.get("url"),
            }

        return None

    async def _build_refresh_context(
        self,
        tool_id: str,
        *,
        owner_user_id: str,
        provider_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_tool = await self._resolve_visible_tool(
            tool_id,
            owner_user_id=owner_user_id,
            provider_id=provider_id,
        )
        if current_tool is None:
            raise LookupError("Provider tool not found")

        refresh_payload = payload or {}
        discovery_url = refresh_payload.get("url") or current_tool.get("server_url")
        if not discovery_url:
            raise ValueError("Discovery URL is required for metadata refresh")

        if "execution_auth" in refresh_payload:
            execution_auth = UpstreamAuthConfig.model_validate(
                refresh_payload.get("execution_auth") or {}
            )
        else:
            execution_auth = await self._repo.fetch_server_execution_auth(current_tool["server_id"])
        current_tools = await self._repo.fetch_server_tools(current_tool["server_id"])
        discovery = await self._metadata_discovery_service.discover(
            url=discovery_url,
            auth=execution_auth,
        )
        fresh_tools = [
            tool.model_dump() if hasattr(tool, "model_dump") else dict(tool)
            for tool in discovery.tools
        ]
        preview = self._metadata_diff_service.build_tool_diff(
            server_id=current_tool["server_id"],
            current_tools=current_tools,
            fresh_tools=fresh_tools,
        )
        fresh_by_name = {tool["tool_name"]: tool for tool in fresh_tools if tool.get("tool_name")}
        return {
            "tool": current_tool,
            "preview": preview,
            "fresh_by_name": fresh_by_name,
            "warnings": list(discovery.warnings),
        }

    @staticmethod
    def _refresh_preview_warnings(refresh_context: dict[str, Any]) -> list[str]:
        warnings = list(refresh_context["warnings"])
        preview = refresh_context["preview"]
        selected_tool_name = str(refresh_context["tool"].get("tool_name") or "").strip()
        selected_entry = next(
            (
                entry
                for entry in preview.changed
                if str(entry.tool_name).strip() == selected_tool_name
            ),
            None,
        )
        if selected_entry and selected_entry.orphaned_parameter_paths:
            warnings.append(
                "Some published parameter descriptions no longer match the upstream schema "
                "and require review."
            )
        return warnings

    @staticmethod
    def _normalize_list_field(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if str(value).strip() else []

    @staticmethod
    def _normalize_published_parameter_metadata(
        value: Any,
        *,
        context: str | None = None,
        server_id: str | None = None,
    ) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, str]] = []
        reason_counts: dict[str, int] = {}
        total = len(value)
        for entry in value:
            if hasattr(entry, "model_dump"):
                entry = entry.model_dump()
            if not isinstance(entry, dict):
                reason_counts["not_a_dict"] = reason_counts.get("not_a_dict", 0) + 1
                continue
            path = str(entry.get("path") or "").strip()
            description = str(entry.get("description") or "").strip()
            if not path or not description:
                reason_counts["missing_required_fields"] = (
                    reason_counts.get("missing_required_fields", 0) + 1
                )
                continue
            normalized.append({"path": path, "description": description})
        emit_drop_warning(
            "DashboardService._normalize_published_parameter_metadata",
            total - len(normalized),
            total,
            reason_counts,
            context=context,
            server_id=server_id,
        )
        return normalized

    @staticmethod
    def _normalize_upstream_parameter_metadata(
        value: Any,
        *,
        context: str | None = None,
        server_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        reason_counts: dict[str, int] = {}
        total = len(value)
        for entry in value:
            if hasattr(entry, "model_dump"):
                entry = entry.model_dump()
            if not isinstance(entry, dict):
                reason_counts["not_a_dict"] = reason_counts.get("not_a_dict", 0) + 1
                continue
            candidate = dict(entry)
            candidate["path"] = str(candidate.get("path") or "").strip()
            candidate["name"] = str(candidate.get("name") or "").strip()
            if not candidate["path"] or not candidate["name"]:
                reason_counts["missing_required_fields"] = (
                    reason_counts.get("missing_required_fields", 0) + 1
                )
                continue
            try:
                normalized.append(ParameterMetadataEntry.model_validate(candidate).model_dump())
            except PydanticValidationError:
                reason_counts["validation_error"] = reason_counts.get("validation_error", 0) + 1
                continue
        emit_drop_warning(
            "DashboardService._normalize_upstream_parameter_metadata",
            total - len(normalized),
            total,
            reason_counts,
            context=context,
            server_id=server_id,
        )
        return normalized

    @staticmethod
    def _derive_metadata_origin(
        *,
        description: str | None,
        upstream_description: str | None,
        parameter_notes: str | None,
        usage_examples: list[str],
        usage_hints: list[str],
        published_parameter_metadata: list[dict[str, str]],
    ) -> str:
        manual_context_present = (
            bool(parameter_notes)
            or bool(usage_examples)
            or bool(usage_hints)
            or bool(published_parameter_metadata)
        )
        if not upstream_description:
            return "manual"
        if description == upstream_description and not manual_context_present:
            return "discovered"
        return "mixed"

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
