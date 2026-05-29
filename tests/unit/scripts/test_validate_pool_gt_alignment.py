"""Tests for scripts/validate_pool_gt_alignment.py"""

import json
from pathlib import Path

from validate_pool_gt_alignment import (
    compute_alignment,
    format_alignment_report,
    load_gt_server_ids,
    load_pool_server_ids_from_jsonl,
)


def _write_pool(tmp_path: Path, ids: list[str]) -> Path:
    p = tmp_path / "pool.jsonl"
    p.write_text("\n".join(json.dumps({"server_id": s, "tools": []}) for s in ids))
    return p


def _write_gt(tmp_path: Path, entries: list[tuple[str, str]]) -> Path:
    p = tmp_path / "gt.jsonl"
    p.write_text("\n".join(json.dumps({"correct_server_id": s, "query_id": q}) for s, q in entries))
    return p


class TestLoadPoolServerIds:
    def test_extracts_unique_server_ids(self, tmp_path: Path) -> None:
        pool_file = _write_pool(tmp_path, ["alpha", "bravo", "alpha"])  # duplicate
        ids = load_pool_server_ids_from_jsonl(pool_file)
        assert ids == {"alpha", "bravo"}

    def test_empty_lines_skipped(self, tmp_path: Path) -> None:
        pool_file = tmp_path / "pool.jsonl"
        pool_file.write_text('{"server_id": "alpha", "tools": []}\n\n')
        assert load_pool_server_ids_from_jsonl(pool_file) == {"alpha"}


class TestLoadGtServerIds:
    def test_counts_queries_per_server(self, tmp_path: Path) -> None:
        gt_file = _write_gt(tmp_path, [("github", "q1"), ("github", "q2"), ("slack", "q3")])
        result = load_gt_server_ids([gt_file])
        assert result["github"] == 2
        assert result["slack"] == 1

    def test_merges_multiple_files(self, tmp_path: Path) -> None:
        d1 = tmp_path / "d1"
        d1.mkdir()
        f1 = _write_gt(d1, [("a", "q1")])
        f2 = tmp_path / "f2.jsonl"
        f2.write_text(json.dumps({"correct_server_id": "b", "query_id": "q2"}) + "\n")
        result = load_gt_server_ids([f1, f2])
        assert set(result.keys()) == {"a", "b"}

    def test_missing_file_skipped(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.jsonl"
        result = load_gt_server_ids([missing])
        assert result == {}


class TestComputeAlignment:
    def test_covered_and_missing_classification(self, tmp_path: Path) -> None:
        pool = _write_pool(tmp_path, ["alpha", "bravo"])
        gt = _write_gt(tmp_path, [("alpha", "q1"), ("delta", "q2")])
        report = compute_alignment(pool, [gt])
        assert "alpha" in report.covered_servers
        assert "delta" in report.missing_servers

    def test_gt_first_ordering_in_pool_sizes(self, tmp_path: Path) -> None:
        # pool: [alpha, bravo, charlie, delta] alphabetical
        # GT: charlie(rank3), delta(rank4) → pool[:2] should cover both with GT-first
        pool = _write_pool(tmp_path, ["alpha", "bravo", "charlie", "delta"])
        gt = _write_gt(tmp_path, [("charlie", "q1"), ("charlie", "q2"), ("delta", "q3")])
        report = compute_alignment(pool, [gt], pool_sizes=[2, 4])
        at_2 = report.coverage_by_pool_size[2]
        assert at_2.n_gt_servers == 2
        assert at_2.n_gt_queries == 3  # charlie(2) + delta(1)

    def test_alphabetical_pool_size_misses_gt_without_gt_first(self, tmp_path: Path) -> None:
        # Verifies GT-first is used: charlie+delta are GT servers at alpha rank 3,4
        # Without GT-first, pool[:2] = [alpha, bravo] → 0 GT coverage
        # With GT-first, pool[:2] = [charlie, delta] → 2 GT servers
        pool = _write_pool(tmp_path, ["alpha", "bravo", "charlie", "delta"])
        gt = _write_gt(tmp_path, [("charlie", "q1"), ("delta", "q2")])
        report = compute_alignment(pool, [gt], pool_sizes=[2])
        assert report.coverage_by_pool_size[2].n_gt_servers == 2

    def test_total_gt_queries_count(self, tmp_path: Path) -> None:
        pool = _write_pool(tmp_path, ["alpha"])
        gt = _write_gt(tmp_path, [("alpha", "q1"), ("alpha", "q2"), ("beta", "q3")])
        report = compute_alignment(pool, [gt])
        assert report.total_gt_queries == 3

    def test_no_pool_sizes_returns_empty_coverage_dict(self, tmp_path: Path) -> None:
        pool = _write_pool(tmp_path, ["alpha"])
        gt = _write_gt(tmp_path, [("alpha", "q1")])
        report = compute_alignment(pool, [gt], pool_sizes=None)
        assert report.coverage_by_pool_size == {}


class TestFormatAlignmentReport:
    def test_output_contains_mandatory_sections(self, tmp_path: Path) -> None:
        pool = _write_pool(tmp_path, ["alpha"])
        gt = _write_gt(tmp_path, [("alpha", "q1"), ("beta", "q2")])
        report = compute_alignment(pool, [gt], pool_sizes=[1])
        text = format_alignment_report(report)
        assert "POOL-GT ALIGNMENT REPORT" in text
        assert "Missing" in text
        assert "Coverage by pool_size" in text

    def test_high_skew_flag_appears_for_dominant_server(self, tmp_path: Path) -> None:
        pool = _write_pool(tmp_path, ["alpha", "beta"])
        # alpha has 90% of queries → HIGH SKEW
        gt = _write_gt(
            tmp_path,
            [("alpha", f"q{i}") for i in range(9)] + [("beta", "q9")],
        )
        report = compute_alignment(pool, [gt])
        text = format_alignment_report(report)
        assert "HIGH SKEW" in text

    def test_no_skew_flag_for_balanced_distribution(self, tmp_path: Path) -> None:
        pool = _write_pool(tmp_path, ["alpha", "beta", "charlie", "delta"])
        gt = _write_gt(
            tmp_path,
            [("alpha", "q1"), ("beta", "q2"), ("charlie", "q3"), ("delta", "q4")],
        )
        report = compute_alignment(pool, [gt])
        text = format_alignment_report(report)
        assert "HIGH SKEW" not in text
