"""Tests for GT-first pool ordering in build_base_pool.py."""


def test_gt_covered_servers_come_first(tmp_path):
    """GT-covered servers must appear before non-GT servers in the pool."""
    gt_file = tmp_path / "atlas.jsonl"
    gt_file.write_text(
        '{"query_id": "gt-atlas-001-s00", "query": "search papers", '
        '"correct_server_id": "semantic_scholar", "correct_tool_id": "semantic_scholar::search", '
        '"difficulty": "easy", "category": "search", "ambiguity": "low", '
        '"source": "external_mcp_atlas", "manually_verified": true, '
        '"author": "scale_ai+llm_decomposed", "created_at": "2026-03-28T00:00:00Z", '
        '"task_type": "single_step", "origin_task_id": "atlas-001", "step_index": 0}\n'
        '{"query_id": "gt-atlas-001-s01", "query": "find academic article", '
        '"correct_server_id": "semantic_scholar", '
        '"correct_tool_id": "semantic_scholar::get_paper", '
        '"difficulty": "medium", "category": "search", "ambiguity": "low", '
        '"source": "external_mcp_atlas", "manually_verified": true, '
        '"author": "scale_ai+llm_decomposed", "created_at": "2026-03-28T00:00:00Z", '
        '"task_type": "single_step", "origin_task_id": "atlas-001", "step_index": 1}\n'
    )
    pool_file = tmp_path / "mcp_zero.jsonl"
    # semantic_scholar appears last alphabetically — confirms GT-first ordering works
    pool_file.write_text(
        '{"server_id": "aaa_other_server"}\n'
        '{"server_id": "bbb_another_server"}\n'
        '{"server_id": "semantic_scholar"}\n'
    )

    from scripts.build_base_pool import build_ordered_pool

    result = build_ordered_pool(gt_paths=[gt_file], pool_path=pool_file)

    assert result[0] == "semantic_scholar", f"Expected GT server first, got {result[0]}"
    assert "aaa_other_server" in result
    assert "bbb_another_server" in result


def test_pool_slice_coverage_is_monotonic(tmp_path):
    """GT coverage must be non-decreasing as pool_size increases."""
    gt_file = tmp_path / "atlas.jsonl"
    gt_file.write_text(
        '{"query_id": "gt-a", "correct_server_id": "s1", "correct_tool_id": "s1::t1", '
        '"query": "q", "difficulty": "easy", "category": "search", "ambiguity": "low", '
        '"source": "external_mcp_atlas", "manually_verified": true, '
        '"author": "scale_ai+llm_decomposed", "created_at": "2026-03-28T00:00:00Z", '
        '"task_type": "single_step", "origin_task_id": "a-001", "step_index": 0}\n'
        '{"query_id": "gt-b", "correct_server_id": "s2", "correct_tool_id": "s2::t2", '
        '"query": "q2", "difficulty": "easy", "category": "search", "ambiguity": "low", '
        '"source": "external_mcp_atlas", "manually_verified": true, '
        '"author": "scale_ai+llm_decomposed", "created_at": "2026-03-28T00:00:00Z", '
        '"task_type": "single_step", "origin_task_id": "a-002", "step_index": 0}\n'
    )
    pool_file = tmp_path / "mcp_zero.jsonl"
    pool_file.write_text('{"server_id": "s1"}\n{"server_id": "s2"}\n{"server_id": "z_other"}\n')

    from scripts.build_base_pool import build_ordered_pool, compute_coverage

    ordered = build_ordered_pool(gt_paths=[gt_file], pool_path=pool_file)

    prev_coverage = 0
    for n in range(1, len(ordered) + 1):
        coverage = compute_coverage(ordered[:n], gt_paths=[gt_file])
        assert coverage >= prev_coverage, (
            f"Coverage not monotonic: pool_size={n} coverage={coverage} < prev={prev_coverage}"
        )
        prev_coverage = coverage


def test_all_pool_servers_present(tmp_path):
    """Output must contain every server from the pool, no more, no less."""
    gt_file = tmp_path / "empty.jsonl"
    gt_file.write_text("")
    pool_file = tmp_path / "pool.jsonl"
    pool_file.write_text('{"server_id": "alpha"}\n{"server_id": "beta"}\n{"server_id": "gamma"}\n')

    from scripts.build_base_pool import build_ordered_pool

    result = build_ordered_pool(gt_paths=[gt_file], pool_path=pool_file)

    assert set(result) == {"alpha", "beta", "gamma"}
    assert len(result) == 3


def test_run_e0_loads_pool_gt_first(tmp_path):
    """_load_pool_server_ids must use GT-first order from base_pool.json."""
    import json

    base_pool = tmp_path / "base_pool.json"
    base_pool.write_text(json.dumps(["semantic_scholar", "alpha_server", "beta_server"]))

    import scripts.run_e0 as run_e0_module

    original = run_e0_module.BASE_POOL_PATH
    run_e0_module.BASE_POOL_PATH = base_pool
    try:
        result = run_e0_module._load_pool_server_ids(pool_size=2)
    finally:
        run_e0_module.BASE_POOL_PATH = original

    assert result == ["semantic_scholar", "alpha_server"]
    assert "beta_server" not in result
