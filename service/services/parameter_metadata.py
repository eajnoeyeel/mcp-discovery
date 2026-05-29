"""Helpers for normalized parameter metadata derived from JSON Schema."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from service.services.contracts import ParameterMetadataEntry, PublishedParameterMetadataEntry


def extract_parameter_metadata(schema: dict | None) -> list[ParameterMetadataEntry]:
    """Flatten supported JSON Schema shapes into review-friendly parameter metadata."""

    if not isinstance(schema, dict):
        return []

    entries: list[ParameterMetadataEntry] = []

    def walk(node: dict[str, Any], prefix: str = "") -> None:
        properties = node.get("properties")
        if not isinstance(properties, dict):
            return

        required_names = set(node.get("required") or [])
        for name, child in properties.items():
            if not isinstance(child, dict):
                continue

            path = f"{prefix}.{name}" if prefix else name
            child_type = child.get("type")
            item_schema = child.get("items") if isinstance(child.get("items"), dict) else None
            object_properties = child.get("properties")
            object_properties_count = (
                len(object_properties)
                if isinstance(object_properties, dict) and object_properties
                else None
            )
            enum_values = child.get("enum")

            entries.append(
                ParameterMetadataEntry(
                    path=path,
                    name=name,
                    type=child_type if isinstance(child_type, str) else None,
                    required=name in required_names,
                    description=child.get("description")
                    if isinstance(child.get("description"), str)
                    else None,
                    enum_values=[str(value) for value in enum_values]
                    if isinstance(enum_values, list)
                    else [],
                    default_value=child.get("default"),
                    items_type=item_schema.get("type")
                    if item_schema and isinstance(item_schema.get("type"), str)
                    else None,
                    object_properties_count=object_properties_count,
                )
            )

            if _is_object_like(child):
                walk(child, path)
            elif _is_object_array_like(child, item_schema):
                walk(item_schema, f"{path}[]")

    walk(schema)
    return entries


def merge_parameter_descriptions(
    schema: dict | None,
    published: list[dict[str, Any] | PublishedParameterMetadataEntry] | None,
) -> dict | None:
    """Apply published description overrides onto a copied JSON Schema."""

    if not isinstance(schema, dict):
        return schema

    if not published:
        return deepcopy(schema)

    merged = deepcopy(schema)
    description_by_path = {
        path: description
        for entry in published
        if (path := _entry_path(entry)) and (description := _entry_description(entry)) is not None
    }

    if not description_by_path:
        return merged

    def apply(node: dict[str, Any], prefix: str = "") -> None:
        properties = node.get("properties")
        if not isinstance(properties, dict):
            return

        for name, child in properties.items():
            if not isinstance(child, dict):
                continue

            path = f"{prefix}.{name}" if prefix else name
            if path in description_by_path:
                child["description"] = description_by_path[path]

            item_schema = child.get("items") if isinstance(child.get("items"), dict) else None

            if _is_object_like(child):
                apply(child, path)
            elif _is_object_array_like(child, item_schema):
                apply(item_schema, f"{path}[]")

    apply(merged)
    return merged


def _entry_path(entry: dict[str, Any] | PublishedParameterMetadataEntry) -> str | None:
    if isinstance(entry, PublishedParameterMetadataEntry):
        return entry.path
    path = entry.get("path")
    return path if isinstance(path, str) else None


def _entry_description(entry: dict[str, Any] | PublishedParameterMetadataEntry) -> str | None:
    if isinstance(entry, PublishedParameterMetadataEntry):
        return entry.description
    if "description" not in entry:
        return None
    description = entry.get("description")
    return description if isinstance(description, str) else None


def _has_properties(node: dict[str, Any] | None) -> bool:
    return isinstance(node, dict) and isinstance(node.get("properties"), dict)


def _is_object_like(node: dict[str, Any]) -> bool:
    return node.get("type") == "object" or _has_properties(node)


def _is_object_array_like(
    node: dict[str, Any],
    item_schema: dict[str, Any] | None,
) -> bool:
    return node.get("type") == "array" and _has_properties(item_schema)
