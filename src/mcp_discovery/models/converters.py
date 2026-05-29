"""Conversion functions between data contract layers."""

from mcp_discovery.models.canonical import CanonicalServer, CanonicalTool
from mcp_discovery.models.registry import RegistryRecord
from mcp_discovery.utils.content_hash import compute_content_hash


def registry_to_canonical_tools(record: RegistryRecord) -> list[CanonicalTool]:
    """Convert raw RegistryRecord to a list of CanonicalTools."""
    return [
        CanonicalTool(
            tool_id=f"{record.server_id}::{tool.tool_name}",
            server_id=record.server_id,
            tool_name=tool.tool_name,
            description=tool.description or None,
            input_schema=tool.input_schema,
            content_hash=compute_content_hash(tool.tool_name, tool.description),
        )
        for tool in record.tools
    ]


def registry_to_canonical_server(record: RegistryRecord) -> CanonicalServer:
    """Convert raw RegistryRecord to a CanonicalServer."""
    return CanonicalServer(
        server_id=record.server_id,
        name=record.name,
        description=record.description or None,
        url=record.url or None,
        tags=record.tags,
    )
