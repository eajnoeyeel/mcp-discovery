"""Tests for scripts/import_mcp_zero.py — MCP-Zero import conversion."""

import json

from import_mcp_zero import (
    convert_server,
    extract_server_embeddings,
    extract_tool_embeddings,
    load_mcp_zero_json,
    parse_parameter_schema,
)

from mcp_discovery.models import TOOL_ID_SEPARATOR, MCPServer, MCPTool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_raw_server(
    name: str = "GitHub MCP",
    summary: str = "Interact with GitHub",
    description: str = "A server for GitHub interactions",
    tools: list[dict] | None = None,
) -> dict:
    """Build a minimal MCP-Zero server entry for testing.

    Uses actual MCP-Zero schema: name, description, summary, url, tools.
    """
    if tools is None:
        tools = [
            {
                "name": "search_issues",
                "description": "Search GitHub issues",
                "description_embedding": [0.1] * 3072,
                "parameter": {
                    "query": "(string) Search query text",
                    "limit": "(integer) Max results",
                },
            },
        ]
    return {
        "name": name,
        "summary": summary,
        "description": description,
        "url": "https://github.com/example/mcp",
        "description_embedding": [0.01] * 3072,
        "summary_embedding": [0.02] * 3072,
        "tools": tools,
    }


# ===========================================================================
# TestParseParameterSchema
# ===========================================================================


class TestParseParameterSchema:
    """Test MCP-Zero parameter → JSON Schema conversion."""

    def test_converts_mcp_zero_format(self):
        """Standard MCP-Zero format: {"param": "(type) description"} → JSON Schema."""
        params = {
            "query": "(string) Search query text",
            "limit": "(integer) Max results to return",
        }
        schema = parse_parameter_schema(params)

        assert schema is not None
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert schema["properties"]["query"]["type"] == "string"
        assert schema["properties"]["query"]["description"] == "Search query text"
        assert schema["properties"]["limit"]["type"] == "integer"
        assert schema["properties"]["limit"]["description"] == "Max results to return"

    def test_boolean_and_number_types(self):
        params = {
            "verbose": "(boolean) Enable verbose output",
            "temperature": "(number) Sampling temperature",
        }
        schema = parse_parameter_schema(params)

        assert schema["properties"]["verbose"]["type"] == "boolean"
        assert schema["properties"]["temperature"]["type"] == "number"

    def test_empty_params(self):
        """Empty dict and None both return None (no schema)."""
        assert parse_parameter_schema({}) is None
        assert parse_parameter_schema(None) is None

    def test_unknown_type_defaults_to_string(self):
        """Unknown type annotation (e.g. bytes) falls back to string."""
        params = {"data": "(bytes) Raw binary data"}
        schema = parse_parameter_schema(params)

        assert schema["properties"]["data"]["type"] == "string"

    def test_no_type_annotation(self):
        """Value without (type) prefix uses string type, full value as description."""
        params = {"query": "Search query text without type annotation"}
        schema = parse_parameter_schema(params)

        assert schema["properties"]["query"]["type"] == "string"
        assert (
            schema["properties"]["query"]["description"]
            == "Search query text without type annotation"
        )

    def test_array_type(self):
        params = {"tags": "(array) List of tags"}
        schema = parse_parameter_schema(params)

        assert schema["properties"]["tags"]["type"] == "array"


# ===========================================================================
# TestConvertServer
# ===========================================================================


class TestConvertServer:
    """Test MCP-Zero server → MCPServer conversion."""

    def test_basic_conversion(self):
        """Full happy-path: server_id, name, description, tool count."""
        raw = _make_raw_server()
        server = convert_server(raw)

        assert server is not None
        assert isinstance(server, MCPServer)
        assert server.server_id == "github_mcp"
        assert server.name == "GitHub MCP"
        assert server.description == "A server for GitHub interactions"
        assert len(server.tools) == 1

    def test_tool_ids_use_separator(self):
        """tool_id uses '::' separator: '{server_id}::{tool_name}'."""
        raw = _make_raw_server()
        server = convert_server(raw)

        tool = server.tools[0]
        assert TOOL_ID_SEPARATOR in tool.tool_id
        assert tool.tool_id == f"github_mcp{TOOL_ID_SEPARATOR}search_issues"
        assert tool.server_id == "github_mcp"
        assert tool.tool_name == "search_issues"

    def test_tool_description_preserved(self):
        """Tool description from MCP-Zero is preserved in MCPTool."""
        raw = _make_raw_server(
            tools=[
                {
                    "name": "create_issue",
                    "description": "Create a new GitHub issue with title and body",
                    "description_embedding": [0.1] * 3072,
                    "parameter": {},
                }
            ]
        )
        server = convert_server(raw)

        assert server is not None
        assert server.tools[0].description == "Create a new GitHub issue with title and body"

    def test_server_id_normalization(self):
        """'My Cool Server' → 'my_cool_server'."""
        raw = _make_raw_server(name="My Cool Server")
        server = convert_server(raw)

        assert server is not None
        assert server.server_id == "my_cool_server"

    def test_no_tools_returns_none(self):
        """Server with empty tools list → None."""
        raw = _make_raw_server(tools=[])
        result = convert_server(raw)

        assert result is None

    def test_missing_server_name_returns_none(self):
        """Missing name key → None."""
        raw = _make_raw_server()
        del raw["name"]
        result = convert_server(raw)

        assert result is None

    def test_embeddings_not_stored_in_model(self):
        """MCPTool has no embedding field — embeddings extracted separately."""
        raw = _make_raw_server()
        server = convert_server(raw)

        tool = server.tools[0]
        assert isinstance(tool, MCPTool)
        # MCPTool should not have any embedding-related attribute
        assert not hasattr(tool, "embedding")
        assert not hasattr(tool, "description_embedding")
        # Only expected fields exist
        expected_fields = {
            "server_id",
            "tool_name",
            "tool_id",
            "description",
            "input_schema",
            "selection_description",
        }
        assert set(MCPTool.model_fields.keys()) == expected_fields

    def test_empty_server_name_returns_none(self):
        """Empty string name → None."""
        raw = _make_raw_server(name="")
        result = convert_server(raw)

        assert result is None

    def test_tool_without_name_is_skipped(self):
        """Tools missing 'name' field are skipped."""
        raw = _make_raw_server(
            tools=[
                {"description": "No name tool", "parameter": {}},
                {
                    "name": "valid_tool",
                    "description": "Has name",
                    "description_embedding": [0.1] * 3072,
                    "parameter": {},
                },
            ]
        )
        server = convert_server(raw)

        assert server is not None
        assert len(server.tools) == 1
        assert server.tools[0].tool_name == "valid_tool"

    def test_tool_input_schema_from_parameter(self):
        """parameter field is converted to JSON Schema via parse_parameter_schema."""
        raw = _make_raw_server(
            tools=[
                {
                    "name": "search",
                    "description": "Search things",
                    "description_embedding": [0.1] * 3072,
                    "parameter": {
                        "query": "(string) Search query",
                        "limit": "(integer) Max results",
                    },
                }
            ]
        )
        server = convert_server(raw)
        tool = server.tools[0]

        assert tool.input_schema is not None
        assert tool.input_schema["type"] == "object"
        assert "query" in tool.input_schema["properties"]

    def test_multiple_tools(self):
        """Server with multiple tools creates all MCPTool entries."""
        raw = _make_raw_server(
            tools=[
                {
                    "name": "tool_a",
                    "description": "First",
                    "description_embedding": [0.1] * 3072,
                    "parameter": {},
                },
                {
                    "name": "tool_b",
                    "description": "Second",
                    "description_embedding": [0.2] * 3072,
                    "parameter": {"x": "(string) param"},
                },
            ]
        )
        server = convert_server(raw)

        assert server is not None
        assert len(server.tools) == 2
        assert server.tools[0].tool_name == "tool_a"
        assert server.tools[1].tool_name == "tool_b"

    def test_summary_fallback(self):
        """If description is missing, fall back to summary."""
        raw = _make_raw_server()
        del raw["description"]
        server = convert_server(raw)

        assert server is not None
        assert server.description == "Interact with GitHub"


# ===========================================================================
# TestExtractToolEmbeddings
# ===========================================================================


class TestExtractToolEmbeddings:
    """Test extraction of pre-computed embeddings keyed by tool_id."""

    def test_extracts_embeddings(self):
        """Returns dict mapping tool_id → embedding vector."""
        raw_servers = [_make_raw_server()]
        embeddings = extract_tool_embeddings(raw_servers)

        expected_tool_id = f"github_mcp{TOOL_ID_SEPARATOR}search_issues"
        assert expected_tool_id in embeddings
        assert len(embeddings[expected_tool_id]) == 3072

    def test_skips_tools_without_embedding(self):
        """Tools missing description_embedding are skipped."""
        raw = _make_raw_server(
            tools=[
                {
                    "name": "no_embed",
                    "description": "Missing embedding",
                    "parameter": {},
                },
            ]
        )
        embeddings = extract_tool_embeddings([raw])

        assert len(embeddings) == 0

    def test_skips_servers_without_name(self):
        """Servers without name are skipped entirely."""
        raw = _make_raw_server()
        del raw["name"]
        embeddings = extract_tool_embeddings([raw])

        assert len(embeddings) == 0

    def test_multiple_servers_multiple_tools(self):
        """Correct count across multiple servers."""
        raw1 = _make_raw_server(name="Server A")
        raw2 = _make_raw_server(
            name="Server B",
            tools=[
                {
                    "name": "t1",
                    "description": "Tool 1",
                    "description_embedding": [0.3] * 3072,
                    "parameter": {},
                },
                {
                    "name": "t2",
                    "description": "Tool 2",
                    "description_embedding": [0.4] * 3072,
                    "parameter": {},
                },
            ],
        )
        embeddings = extract_tool_embeddings([raw1, raw2])

        # 1 from server A + 2 from server B = 3
        assert len(embeddings) == 3


# ===========================================================================
# TestExtractServerEmbeddings
# ===========================================================================


class TestExtractServerEmbeddings:
    """Test extraction of pre-computed server-level embeddings keyed by server_id."""

    def test_extracts_server_embeddings(self):
        """Returns dict mapping server_id → embedding vector."""
        raw_servers = [_make_raw_server()]
        embeddings = extract_server_embeddings(raw_servers)

        assert "github_mcp" in embeddings
        assert len(embeddings["github_mcp"]) == 3072

    def test_skips_servers_without_embedding(self):
        """Servers missing description_embedding are skipped."""
        raw = _make_raw_server()
        del raw["description_embedding"]
        embeddings = extract_server_embeddings([raw])

        assert len(embeddings) == 0

    def test_skips_servers_without_name(self):
        """Servers without name are skipped entirely."""
        raw = _make_raw_server()
        del raw["name"]
        embeddings = extract_server_embeddings([raw])

        assert len(embeddings) == 0

    def test_multiple_servers(self):
        """Correct count across multiple servers."""
        raw1 = _make_raw_server(name="Server A")
        raw2 = _make_raw_server(name="Server B")
        raw3 = _make_raw_server(name="Server C")
        embeddings = extract_server_embeddings([raw1, raw2, raw3])

        assert len(embeddings) == 3
        assert "server_a" in embeddings
        assert "server_b" in embeddings
        assert "server_c" in embeddings

    def test_uses_normalized_server_id_as_key(self):
        """'My Cool Server' → 'my_cool_server'."""
        raw = _make_raw_server(name="My Cool Server")
        embeddings = extract_server_embeddings([raw])

        assert "my_cool_server" in embeddings
        assert len(embeddings) == 1


# ===========================================================================
# TestLoadMcpZeroJson
# ===========================================================================


class TestLoadMcpZeroJson:
    """Test JSON loading with both list and dict-with-servers formats."""

    def test_loads_list_format(self, tmp_path):
        """JSON file is a list of server objects."""
        data = [_make_raw_server(), _make_raw_server(name="Second")]
        path = tmp_path / "servers.json"
        path.write_text(json.dumps(data))

        result = load_mcp_zero_json(path)

        assert len(result) == 2

    def test_loads_dict_with_servers_key(self, tmp_path):
        """JSON file wraps servers under a 'servers' key."""
        data = {"servers": [_make_raw_server()]}
        path = tmp_path / "servers.json"
        path.write_text(json.dumps(data))

        result = load_mcp_zero_json(path)

        assert len(result) == 1

    def test_unexpected_structure_returns_empty(self, tmp_path):
        """Unexpected JSON structure → empty list."""
        data = {"not_servers": [1, 2, 3]}
        path = tmp_path / "servers.json"
        path.write_text(json.dumps(data))

        result = load_mcp_zero_json(path)

        assert result == []
