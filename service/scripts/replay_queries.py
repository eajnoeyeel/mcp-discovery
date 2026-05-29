"""Canonical query set for MLP smoke and replay verification."""

from __future__ import annotations

import argparse
import json

QUERIES = [
    "search github repositories",
    "find postgres database tool",
    "look up arxiv papers",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Print the canonical MLP replay query set.")
    parser.add_argument(
        "--format",
        choices=("json", "lines"),
        default="json",
        help="Output format for the query set.",
    )
    args = parser.parse_args()

    if args.format == "lines":
        print("\n".join(QUERIES))
        return

    print(json.dumps({"queries": QUERIES}, indent=2))


if __name__ == "__main__":
    main()
