"""Minimal local-only stdio echo fixture for gateway transport proofing."""

from __future__ import annotations

import json
import sys


def main() -> None:
    for line in sys.stdin:
        payload = json.loads(line)
        if payload.get("method") == "ping":
            sys.stdout.write(json.dumps({"ok": True, "echo": "pong"}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
