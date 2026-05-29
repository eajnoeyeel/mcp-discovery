"""Tests for the --confirm-baseline-resuperseded guard in refresh_pool_with_reindex.py.

Covers AC21: script rejects empty / malformed / missing-ADR-file arg.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"


def _import_script():
    """Lazily import the _validate_adr_arg function from the script module."""
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    if str(_REPO_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT / "src"))

    import refresh_pool_with_reindex  # noqa: PLC0415

    return refresh_pool_with_reindex


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestADRGuard:
    """Test _validate_adr_arg function and its integration into the main parser."""

    def test_rejects_empty_confirm_arg(self, tmp_path: Path) -> None:
        """test_rejects_empty_confirm_arg: missing --confirm arg → non-zero exit."""
        with (
            patch("sys.argv", ["refresh_pool_with_reindex.py"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            mod = _import_script()
            import asyncio

            asyncio.run(mod.main())
        # argparse missing required argument → SystemExit(2)
        assert exc_info.value.code != 0

    def test_rejects_malformed_format(self, tmp_path: Path) -> None:
        """test_rejects_malformed_format: ADR-99 (3 digits) → exit != 0.

        The regex ^ADR-\\d{4}$ requires exactly 4 digits, so ADR-99 fails.
        """
        mod = _import_script()
        with pytest.raises(SystemExit) as exc_info:
            mod._validate_adr_arg("ADR-99")
        assert exc_info.value.code != 0

    def test_rejects_missing_adr_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """test_rejects_missing_adr_file: valid format but ADR-9999.md missing → exit != 0."""
        mod = _import_script()
        # Patch _REPO_ROOT so the candidate path points to a non-existent file under tmp_path
        fake_docs_adr = tmp_path / "docs" / "adr"
        fake_docs_adr.mkdir(parents=True)
        # ADR-9999.md is NOT created → file does not exist
        monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            mod._validate_adr_arg("ADR-9999")
        assert exc_info.value.code != 0

    def test_accepts_valid_with_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """test_accepts_valid_with_file: valid format + ADR-0018.md exists → returns Path."""
        mod = _import_script()
        # Create docs/adr/ADR-0018.md under tmp_path
        fake_docs_adr = tmp_path / "docs" / "adr"
        fake_docs_adr.mkdir(parents=True)
        (fake_docs_adr / "ADR-0018.md").write_text("stub", encoding="utf-8")
        monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path)

        result = mod._validate_adr_arg("ADR-0018")
        assert isinstance(result, Path)
        assert result.exists()

    def test_regex_requires_four_digits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """test_regex_requires_four_digits: ensure 3-digit and 5-digit args are rejected."""
        mod = _import_script()
        # Even with a real docs/adr dir, malformed args should fail before file check
        monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path)
        for bad_arg in ["ADR-999", "ADR-99999", "adr-0018", "ADR0018", "0018"]:
            with pytest.raises(SystemExit) as exc_info:
                mod._validate_adr_arg(bad_arg)
            assert exc_info.value.code != 0, f"{bad_arg} should have failed"

    def test_accepts_real_adr0018(self) -> None:
        """test_accepts_real_adr0018: ADR-0018 exists in the real repo → should pass guard."""
        mod = _import_script()
        # Don't monkeypatch _REPO_ROOT — use the real one
        real_adr = _REPO_ROOT / "docs" / "adr" / "ADR-0018.md"
        if not real_adr.exists():
            pytest.skip("docs/adr/ADR-0018.md not present in this checkout")
        result = mod._validate_adr_arg("ADR-0018")
        assert isinstance(result, Path)
