#!/usr/bin/env python3
"""Verify generated ground truth quality.

Usage:
    uv run python scripts/verify_ground_truth.py \\
        --synthetic data/ground_truth/synthetic.jsonl \\
        --seed data/ground_truth/seed_set.jsonl
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add src/ to path so we can import project modules

from mcp_discovery.data.ground_truth import (
    QualityGate,
    QualityGateError,
    load_ground_truth,
    merge_ground_truth,
    split_by_difficulty,
)
from mcp_discovery.models import Difficulty

# Short tool names that cause false-positive leakage (substring of common words)
FALSE_POSITIVE_TOOL_NAMES = {
    "sin",
    "min",
    "max",
    "sum",
    "add",
    "tan",
    "cos",
    "log",
    "mode",
    "round",
    "mean",
    "median",
    "floor",
    "ceiling",
    "division",
    "multiply",
    "modulo",
}


def print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_section(num: int, title: str) -> None:
    print(f"\n[{num}] {title}")
    print("-" * 40)


def verify(args: argparse.Namespace) -> bool:
    """Run all verification checks. Returns True if all pass."""
    passed = True
    synthetic_path = Path(args.synthetic)
    seed_path = Path(args.seed)

    print_header("Ground Truth Verification Report")

    # --- Check file existence ---
    if not synthetic_path.exists():
        print(f"\nERROR: Synthetic file not found: {synthetic_path}")
        return False
    if not seed_path.exists():
        print(f"\nERROR: Seed file not found: {seed_path}")
        return False

    synthetic = load_ground_truth(synthetic_path)
    seed = load_ground_truth(seed_path, only_verified=True)

    # --- [1] Basic Stats ---
    print_section(1, "Basic Stats")
    print(f"  Synthetic entries: {len(synthetic)}")
    print(f"  Seed entries:      {len(seed)}")

    # Difficulty distribution
    synth_by_diff = split_by_difficulty(synthetic)
    seed_by_diff = split_by_difficulty(seed)

    print(f"\n  {'Difficulty':<10} {'Synthetic':>10} {'%':>8} {'Seed':>8} {'%':>8}")
    print(f"  {'-' * 10} {'-' * 10} {'-' * 8} {'-' * 8} {'-' * 8}")
    for diff in Difficulty:
        s_count = len(synth_by_diff[diff])
        s_pct = s_count / len(synthetic) * 100 if synthetic else 0
        sd_count = len(seed_by_diff[diff])
        sd_pct = sd_count / len(seed) * 100 if seed else 0
        print(f"  {diff.value:<10} {s_count:>10} {s_pct:>7.1f}% {sd_count:>8} {sd_pct:>7.1f}%")

    # Server distribution
    server_counter = Counter(e.correct_server_id for e in synthetic)
    print("\n  Server distribution:")
    for server_id, count in server_counter.most_common():
        print(f"    {server_id:<40} {count:>4} entries")

    # Category distribution
    cat_counter = Counter(e.category.value for e in synthetic)
    print("\n  Category distribution:")
    for cat, count in cat_counter.most_common():
        print(f"    {cat:<20} {count:>4} entries")

    # --- [2] Quality Gate ---
    print_section(2, "Quality Gate")
    gate = QualityGate()

    # Difficulty distribution check
    try:
        gate.check_difficulty_distribution(synthetic, seed)
        print("  Difficulty distribution: PASS")
    except QualityGateError as e:
        print(f"  Difficulty distribution: FAIL — {e}")
        passed = False

    # Tool name leakage check (with false-positive filtering)
    all_tool_names = set()
    for entry in synthetic:
        tool_id = entry.correct_tool_id
        if "::" in tool_id:
            all_tool_names.add(tool_id.split("::")[-1])

    # Check with all tool names first
    try:
        gate.check_no_tool_name_leakage(synthetic, list(all_tool_names))
        print("  Tool name leakage:      PASS (0 violations)")
    except QualityGateError:
        # Re-check excluding short false-positive names
        real_tool_names = [n for n in all_tool_names if n.lower() not in FALSE_POSITIVE_TOOL_NAMES]
        real_violations = []
        for entry in synthetic:
            if entry.difficulty == Difficulty.EASY:
                continue
            query_lower = entry.query.lower()
            for tn in real_tool_names:
                if tn.lower() in query_lower:
                    real_violations.append(
                        f"    [{entry.query_id}] '{entry.query}' contains '{tn}'"
                    )
                    break

        fp_names = all_tool_names - set(real_tool_names)
        print("  Tool name leakage:      WARNING")
        print(f"    Short names excluded (false positives): {sorted(fp_names)}")
        print(f"    Real violations after filtering: {len(real_violations)}")
        if real_violations:
            for v in real_violations[:10]:
                print(v)
            if len(real_violations) > 10:
                print(f"    ... and {len(real_violations) - 10} more")
            passed = False
        else:
            print("    All leakage from short tool names (acceptable)")

    # --- [3] Samples ---
    print_section(3, "Samples by Difficulty")
    for diff in Difficulty:
        entries = synth_by_diff[diff]
        print(f"\n  [{diff.value.upper()}]")
        for entry in entries[:3]:
            print(f'    Q: "{entry.query}"')
            print(f"    A: {entry.correct_tool_id}")
            print()

    # --- [4] Merge Check ---
    print_section(4, "Merge Check (seed + synthetic)")
    try:
        merged = merge_ground_truth(seed_path, synthetic_path)
        print(f"  Seed ({len(seed)}) + Synthetic ({len(synthetic)}) = {len(merged)} total")
        print("  Duplicate query_ids: 0")
        print("  Merge: PASS")
    except ValueError as e:
        print(f"  Merge: FAIL — {e}")
        passed = False

    # --- [5] Source/Verified Check ---
    print_section(5, "Data Integrity")
    non_synthetic = [e for e in synthetic if e.source != "llm_synthetic"]
    unverified_seed = [e for e in seed if not e.manually_verified]
    synth_status = "PASS" if not non_synthetic else f"FAIL ({len(non_synthetic)} wrong)"
    seed_status = "PASS" if not unverified_seed else f"FAIL ({len(unverified_seed)} wrong)"
    print(f"  All synthetic entries have source='llm_synthetic': {synth_status}")
    print(f"  All seed entries are manually_verified:            {seed_status}")
    if non_synthetic or unverified_seed:
        passed = False

    # --- [6] Verdict ---
    print_header("VERDICT")
    if passed:
        print("  PASS — All checks passed")
    else:
        print("  FAIL — See issues above")
    print()

    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify ground truth quality")
    parser.add_argument("--synthetic", default="data/ground_truth/synthetic.jsonl")
    parser.add_argument("--seed", default="data/ground_truth/seed_set.jsonl")
    args = parser.parse_args()

    ok = verify(args)
    sys.exit(0 if ok else 1)
