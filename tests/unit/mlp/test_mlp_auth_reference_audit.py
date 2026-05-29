from pathlib import Path


def test_auth_reference_audit_records_required_sources():
    content = Path("service/docs/history/2026-04-20_auth_reference_audit.md").read_text()

    assert "docs.anthropic.com/en/docs/claude-code/mcp" in content
    assert "modelcontextprotocol.io/specification/2025-03-26/basic/authorization" in content
    assert "platform.openai.com/docs/guides/developer-mode" in content
    assert "example-remote-server" in content
    assert "mcp-remote-auth-proxy" in content
