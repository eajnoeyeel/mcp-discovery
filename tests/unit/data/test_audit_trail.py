"""Unit tests for src/mcp_discovery/data/audit_trail.py.

Tests verify:
  - Valid chain: append N entries → verify_chain() == (True, None).
  - Chain break: corrupt a stored hash → verify_chain() == (False, idx).
  - Rebase safety: hash is over JSONL line content, NOT git blob hashes.
    (Tested implicitly: we can copy the journal file and verify it without
     any git context — chain verification is pure computation over file content.)
  - read_all() returns entries in append order.
  - Empty journal verifies as valid.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_discovery.data.audit_trail import _GENESIS_HASH, AuditJournal


class TestAuditJournalAppend:
    def test_append_returns_hash(self, tmp_path: Path):
        journal = AuditJournal(tmp_path / "j.jsonl")
        h = journal.append({"event": "test", "value": 1})
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex

    def test_append_creates_file(self, tmp_path: Path):
        journal_path = tmp_path / "j.jsonl"
        journal = AuditJournal(journal_path)
        journal.append({"x": 1})
        assert journal_path.exists()
        assert journal_path.stat().st_size > 0

    def test_read_all_returns_entries_in_order(self, tmp_path: Path):
        journal = AuditJournal(tmp_path / "j.jsonl")
        for i in range(5):
            journal.append({"seq": i})
        entries = journal.read_all()
        assert len(entries) == 5
        assert [e["seq"] for e in entries] == list(range(5))

    def test_len_matches_appended_count(self, tmp_path: Path):
        journal = AuditJournal(tmp_path / "j.jsonl")
        for _ in range(7):
            journal.append({"x": "y"})
        assert len(journal) == 7

    def test_genesis_hash_used_for_first_entry(self, tmp_path: Path):
        journal_path = tmp_path / "j.jsonl"
        journal = AuditJournal(journal_path)
        journal.append({"first": True})
        line = json.loads(journal_path.read_text().strip())
        assert line["prev_hash"] == _GENESIS_HASH


class TestAuditJournalVerifyChain:
    def test_valid_chain_5_entries(self, tmp_path: Path):
        """Append 5 entries; verify_chain must return (True, None)."""
        journal = AuditJournal(tmp_path / "j.jsonl")
        for i in range(5):
            journal.append({"step": i, "value": f"data_{i}"})
        valid, break_at = journal.verify_chain()
        assert valid is True
        assert break_at is None

    def test_empty_journal_is_valid(self, tmp_path: Path):
        journal = AuditJournal(tmp_path / "j.jsonl")
        valid, break_at = journal.verify_chain()
        assert valid is True
        assert break_at is None

    def test_chain_break_detected_at_index(self, tmp_path: Path):
        """Corrupt the stored hash of entry index 2; verify_chain must return (False, 2)."""
        journal_path = tmp_path / "j.jsonl"
        journal = AuditJournal(journal_path)
        for i in range(5):
            journal.append({"step": i})

        # Read all lines, corrupt the hash of line 2 (0-based)
        lines = [ln for ln in journal_path.read_text().splitlines() if ln.strip()]
        record = json.loads(lines[2])
        record["hash"] = "deadbeef" * 8  # 64 chars of garbage
        lines[2] = json.dumps(record, sort_keys=True, separators=(",", ":"))
        journal_path.write_text("\n".join(lines) + "\n")

        # Re-instantiate to read fresh
        fresh_journal = AuditJournal(journal_path)
        valid, break_at = fresh_journal.verify_chain()
        assert valid is False
        assert break_at == 2

    def test_chain_break_at_prev_hash_mismatch(self, tmp_path: Path):
        """Tamper with prev_hash field; verify_chain must detect the break."""
        journal_path = tmp_path / "j.jsonl"
        journal = AuditJournal(journal_path)
        for i in range(4):
            journal.append({"idx": i})

        lines = [ln for ln in journal_path.read_text().splitlines() if ln.strip()]
        record = json.loads(lines[1])
        record["prev_hash"] = "00" * 32  # garbage prev_hash
        lines[1] = json.dumps(record, sort_keys=True, separators=(",", ":"))
        journal_path.write_text("\n".join(lines) + "\n")

        fresh_journal = AuditJournal(journal_path)
        valid, break_at = fresh_journal.verify_chain()
        assert valid is False
        assert break_at == 1


class TestAuditJournalRebaseSafety:
    def test_chain_verifies_without_git_context(self, tmp_path: Path):
        """Chain verification is pure computation — no git process or blob hashes needed.

        This test verifies rebase safety by copying the journal to a new location
        (simulating a rebase or branch switch) and confirming verification still passes.
        """
        journal_path = tmp_path / "original" / "j.jsonl"
        journal = AuditJournal(journal_path)
        for i in range(3):
            journal.append({"reconcile": "step", "index": i})

        # Copy to a different path (simulates different git context)
        copy_path = tmp_path / "copy" / "j.jsonl"
        copy_path.parent.mkdir()
        copy_path.write_text(journal_path.read_text())

        copied_journal = AuditJournal(copy_path)
        valid, _ = copied_journal.verify_chain()
        assert valid is True

    def test_identical_entries_produce_identical_hashes(self, tmp_path: Path):
        """Two journals with identical entry sequences must produce the same hashes."""
        j1 = AuditJournal(tmp_path / "j1.jsonl")
        j2 = AuditJournal(tmp_path / "j2.jsonl")

        entries = [{"event": "reconcile", "idx": i} for i in range(3)]
        h1s = [j1.append(e) for e in entries]
        h2s = [j2.append(e) for e in entries]

        assert h1s == h2s

    def test_different_entry_order_produces_different_hashes(self, tmp_path: Path):
        """Entry order matters for the hash chain — reordering breaks the chain."""
        j1 = AuditJournal(tmp_path / "j1.jsonl")
        j2 = AuditJournal(tmp_path / "j2.jsonl")

        j1.append({"a": 1})
        j1.append({"b": 2})
        j2.append({"b": 2})
        j2.append({"a": 1})

        entries_j1 = j1.read_all()
        entries_j2 = j2.read_all()

        # Content of entries differs (different order)
        assert entries_j1 != entries_j2

        lines_j1 = json.loads(j1._path.read_text().splitlines()[-1])
        lines_j2 = json.loads(j2._path.read_text().splitlines()[-1])
        assert lines_j1["hash"] != lines_j2["hash"]
