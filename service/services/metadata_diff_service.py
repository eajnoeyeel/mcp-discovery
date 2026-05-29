"""Metadata diff service for upstream MCP tool refresh flows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from service.services.contracts import (
    ToolMetadataDiffEntry,
    ToolMetadataDiffResult,
    ToolParameterChangeEntry,
)


class MetadataDiffService:
    """Compare stored tool metadata with a fresh upstream discovery snapshot."""

    def build_tool_diff(
        self,
        *,
        server_id: str,
        current_tools: list[dict[str, Any]],
        fresh_tools: list[dict[str, Any]],
    ) -> ToolMetadataDiffResult:
        current_by_name = {
            tool_name: tool
            for tool in current_tools
            if (tool_name := self._tool_name(tool)) is not None
        }
        fresh_by_name = {
            tool_name: tool
            for tool in fresh_tools
            if (tool_name := self._tool_name(tool)) is not None
        }

        changed: list[ToolMetadataDiffEntry] = []
        added: list[ToolMetadataDiffEntry] = []
        removed: list[ToolMetadataDiffEntry] = []

        for tool_name in sorted(fresh_by_name.keys() - current_by_name.keys()):
            fresh = fresh_by_name[tool_name]
            added.append(
                ToolMetadataDiffEntry(
                    tool_name=tool_name,
                    change_type="added",
                    upstream_description=self._fresh_upstream_description(fresh),
                    severity="info",
                )
            )

        for tool_name in sorted(current_by_name.keys() - fresh_by_name.keys()):
            current = current_by_name[tool_name]
            removed.append(
                ToolMetadataDiffEntry(
                    tool_name=tool_name,
                    change_type="removed",
                    upstream_description=self._stored_upstream_description(current),
                    effective_description=self._effective_description(current),
                    severity="info",
                )
            )

        for tool_name in sorted(current_by_name.keys() & fresh_by_name.keys()):
            current = current_by_name[tool_name]
            fresh = fresh_by_name[tool_name]
            current_upstream_description = self._stored_upstream_description(current)
            fresh_upstream_description = self._fresh_upstream_description(fresh)
            upstream_description_changed = (
                current_upstream_description is not None
                and current_upstream_description != fresh_upstream_description
            )
            parameter_changes = self._parameter_changes(current, fresh)
            orphaned_parameter_paths = self._orphaned_parameter_paths(current, fresh)
            schema_changed = (
                self._input_schema(current) != self._input_schema(fresh)
                or bool(parameter_changes)
                or bool(orphaned_parameter_paths)
            )

            if not upstream_description_changed and not schema_changed:
                continue

            changed.append(
                ToolMetadataDiffEntry(
                    tool_name=tool_name,
                    change_type="changed",
                    upstream_description=fresh_upstream_description,
                    effective_description=self._effective_description(current),
                    schema_changed=schema_changed,
                    severity="warning" if schema_changed else "info",
                    parameter_changes=parameter_changes,
                    orphaned_parameter_paths=orphaned_parameter_paths,
                )
            )

        return ToolMetadataDiffResult(
            server_id=server_id,
            changed=changed,
            added=added,
            removed=removed,
        )

    @staticmethod
    def _tool_name(tool: Mapping[str, Any]) -> str | None:
        value = tool.get("tool_name") or tool.get("name")
        return str(value) if value else None

    @staticmethod
    def _stored_upstream_description(tool: Mapping[str, Any]) -> str | None:
        value = tool.get("upstream_description")
        return str(value) if value is not None else None

    @staticmethod
    def _fresh_upstream_description(tool: Mapping[str, Any]) -> str | None:
        value = tool.get("upstream_description")
        if value is None:
            value = tool.get("description")
        return str(value) if value is not None else None

    @staticmethod
    def _effective_description(tool: Mapping[str, Any]) -> str | None:
        value = tool.get("description")
        return str(value) if value is not None else None

    @staticmethod
    def _input_schema(tool: Mapping[str, Any]) -> Any:
        if "input_schema" in tool:
            return tool.get("input_schema")
        return tool.get("inputSchema")

    @classmethod
    def _parameter_changes(
        cls,
        current: Mapping[str, Any],
        fresh: Mapping[str, Any],
    ) -> list[ToolParameterChangeEntry]:
        current_by_path = cls._parameter_metadata_by_path(current, "upstream_parameter_metadata")
        fresh_by_path = cls._parameter_metadata_by_path(
            fresh,
            "upstream_parameter_metadata",
            "parameter_metadata",
        )
        published_by_path = cls._published_parameter_descriptions(current)

        changes: list[ToolParameterChangeEntry] = []
        for path in sorted(fresh_by_path.keys() - current_by_path.keys()):
            changes.append(
                ToolParameterChangeEntry(
                    path=path,
                    change_type="added",
                    severity="warning",
                    upstream_description=cls._string_or_none(
                        fresh_by_path[path].get("description")
                    ),
                    published_description=published_by_path.get(path),
                )
            )
        for path in sorted(current_by_path.keys() - fresh_by_path.keys()):
            changes.append(
                ToolParameterChangeEntry(
                    path=path,
                    change_type="removed",
                    severity="warning",
                    upstream_description=None,
                    published_description=published_by_path.get(path),
                )
            )
        for path in sorted(current_by_path.keys() & fresh_by_path.keys()):
            if current_by_path[path] == fresh_by_path[path]:
                continue
            changes.append(
                ToolParameterChangeEntry(
                    path=path,
                    change_type="changed",
                    severity="info",
                    upstream_description=cls._string_or_none(
                        fresh_by_path[path].get("description")
                    ),
                    published_description=published_by_path.get(path),
                )
            )
        return sorted(changes, key=lambda entry: entry.path)

    @classmethod
    def _orphaned_parameter_paths(
        cls,
        current: Mapping[str, Any],
        fresh: Mapping[str, Any],
    ) -> list[str]:
        published_by_path = cls._published_parameter_descriptions(current)
        fresh_by_path = cls._parameter_metadata_by_path(
            fresh,
            "upstream_parameter_metadata",
            "parameter_metadata",
        )
        return sorted(path for path in published_by_path if path not in fresh_by_path)

    @staticmethod
    def _parameter_metadata_by_path(
        tool: Mapping[str, Any],
        *keys: str,
    ) -> dict[str, dict[str, Any]]:
        for key in keys:
            value = tool.get(key)
            if isinstance(value, list):
                metadata_by_path: dict[str, dict[str, Any]] = {}
                for entry in value:
                    if hasattr(entry, "model_dump"):
                        entry = entry.model_dump()
                    if not isinstance(entry, Mapping):
                        continue
                    path = str(entry.get("path") or "").strip()
                    if not path:
                        continue
                    metadata_by_path[path] = dict(entry)
                if metadata_by_path:
                    return metadata_by_path
        return {}

    @staticmethod
    def _published_parameter_descriptions(tool: Mapping[str, Any]) -> dict[str, str | None]:
        entries = tool.get("published_parameter_metadata")
        if not isinstance(entries, list):
            return {}
        published_by_path: dict[str, str | None] = {}
        for entry in entries:
            if hasattr(entry, "model_dump"):
                entry = entry.model_dump()
            if not isinstance(entry, Mapping):
                continue
            path = str(entry.get("path") or "").strip()
            if not path:
                continue
            published_by_path[path] = MetadataDiffService._string_or_none(entry.get("description"))
        return published_by_path

    @staticmethod
    def _string_or_none(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
