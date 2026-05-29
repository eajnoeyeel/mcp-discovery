from mcp_discovery.utils.content_hash import compute_content_hash


def test_content_hash_deterministic():
    h1 = compute_content_hash("tool_name", "some description")
    h2 = compute_content_hash("tool_name", "some description")
    assert h1 == h2
    assert len(h1) == 64


def test_content_hash_differs_on_change():
    h1 = compute_content_hash("tool_name", "description A")
    h2 = compute_content_hash("tool_name", "description B")
    assert h1 != h2


def test_content_hash_includes_tool_name():
    h1 = compute_content_hash("tool_a", "same description")
    h2 = compute_content_hash("tool_b", "same description")
    assert h1 != h2


def test_content_hash_handles_none_description():
    h1 = compute_content_hash("tool_name", None)
    h2 = compute_content_hash("tool_name", "")
    assert h1 == h2


def test_content_hash_no_collision_with_colon_in_name():
    """tool_name containing separator doesn't cause collision."""
    h1 = compute_content_hash("tool:desc", "")
    h2 = compute_content_hash("tool", "desc")
    assert h1 != h2
