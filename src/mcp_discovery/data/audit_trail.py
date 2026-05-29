"""Append-only audit journal with SHA-256 hash chain (ADR-0018).

The hash chain is computed over JSONL line content — NOT over git blobs —
making it rebase-safe. Each journal entry stores:
  {"entry": {...}, "prev_hash": "<hex>", "hash": "<hex>"}

The genesis entry uses prev_hash = "0" * 64 (64 zero hex chars).
AuditJournal.verify_chain() recomputes every link and returns
(True, None) for a valid chain or (False, N) for a break at index N.

data/probes/journal.jsonl is append-only on main (protected by CODEOWNERS).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from loguru import logger

_GENESIS_HASH = "0" * 64


class AuditJournal:
    """Append-only, hash-chained audit journal backed by a JSONL file.

    Thread safety: NOT thread-safe. Callers should use external locking for
    concurrent access. The expected use pattern is single-writer (one script run
    at a time), so this is intentional to keep complexity low.
    """

    def __init__(self, journal_path: str | Path) -> None:
        self._path = Path(journal_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_hash(prev_hash: str, entry_json: str) -> str:
        """Compute SHA-256 of prev_hash concatenated with entry_json."""
        payload = prev_hash + entry_json
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _last_hash(self) -> str:
        """Return the hash of the most recent journal line, or the genesis hash."""
        lines = [ln.strip() for ln in self._path.read_text().splitlines() if ln.strip()]
        if not lines:
            return _GENESIS_HASH
        try:
            last = json.loads(lines[-1])
            return last["hash"]
        except (json.JSONDecodeError, KeyError):
            logger.warning(
                f"Could not read last hash from journal {self._path}; "
                "starting new chain from genesis hash"
            )
            return _GENESIS_HASH

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, entry: dict) -> str:
        """Append a new entry to the journal and return the new chain hash.

        The entry dict is serialised as JSON with sorted keys for determinism.
        Hash = SHA-256(prev_hash + entry_json).

        Args:
            entry: Arbitrary dict to record. Must be JSON-serialisable.

        Returns:
            Hex string of the new chain hash.
        """
        entry_json = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        prev_hash = self._last_hash()
        new_hash = self._compute_hash(prev_hash, entry_json)
        line = json.dumps(
            {"entry": entry, "prev_hash": prev_hash, "hash": new_hash},
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        logger.info(
            f"AuditJournal: appended entry to {self._path} "
            f"(prev={prev_hash[:8]}… new={new_hash[:8]}…)"
        )
        return new_hash

    def verify_chain(self) -> tuple[bool, int | None]:
        """Verify the integrity of the entire hash chain.

        Recomputes every hash link from the genesis and compares against the
        stored hashes. Rebase-safe because the chain is over line content, not
        git blob hashes.

        Returns:
            (True, None)  — chain is valid.
            (False, N)    — chain is broken at index N (0-based).
        """
        raw_lines = [ln.strip() for ln in self._path.read_text().splitlines() if ln.strip()]
        if not raw_lines:
            return True, None

        prev_hash = _GENESIS_HASH
        for idx, raw_line in enumerate(raw_lines):
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                logger.error(f"AuditJournal.verify_chain: JSON parse error at index {idx}")
                return False, idx

            stored_prev = record.get("prev_hash", "")
            stored_hash = record.get("hash", "")
            entry = record.get("entry", {})

            if stored_prev != prev_hash:
                logger.error(
                    f"AuditJournal.verify_chain: prev_hash mismatch at index {idx}. "
                    f"Expected {prev_hash[:8]}…, got {stored_prev[:8]}…"
                )
                return False, idx

            entry_json = json.dumps(entry, sort_keys=True, separators=(",", ":"))
            expected_hash = self._compute_hash(prev_hash, entry_json)
            if stored_hash != expected_hash:
                logger.error(
                    f"AuditJournal.verify_chain: hash mismatch at index {idx}. "
                    f"Expected {expected_hash[:8]}…, got {stored_hash[:8]}…"
                )
                return False, idx

            prev_hash = stored_hash

        return True, None

    def read_all(self) -> list[dict]:
        """Return all journal entries in append order.

        Returns:
            List of entry dicts (the 'entry' field from each JSONL line).
        """
        raw_lines = [ln.strip() for ln in self._path.read_text().splitlines() if ln.strip()]
        entries: list[dict] = []
        for idx, raw_line in enumerate(raw_lines):
            try:
                record = json.loads(raw_line)
                entries.append(record.get("entry", {}))
            except json.JSONDecodeError:
                logger.warning(f"AuditJournal.read_all: skipping malformed line at index {idx}")
        return entries

    def __len__(self) -> int:
        return len(self.read_all())
