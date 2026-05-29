"""Unit tests for secret-scan logic (AC32).

Invariants from plan:
  - Regex: keyword + high-entropy adjacency pattern
    (?i)\b(token|key|auth|secret|bearer)\b.*?[A-Za-z0-9_\\-]{32,}
  - SecretScanFailure on match; NOT on "API key" plain text
  - AC32: "API key metadata" description must NOT trigger scan failure
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from mcp_discovery.data.pool_prober import _scan_for_secrets, _write_cache
from mcp_discovery.models.probe import ProbeErrorKind, ProbeResult, TransportSpec


def _fixture_secret(*parts: str) -> str:
    """Build scanner-positive fixtures without storing scanner-shaped literals."""
    return "".join(parts)


def _make_result(error_message: str | None = None) -> ProbeResult:
    spec = TransportSpec(transport="stdio", server_id="test")
    spec_hash = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()
    return ProbeResult(
        server_id="test",
        success=False,
        spec_hash=spec_hash,
        error_kind=ProbeErrorKind.HANDSHAKE_FAILED,
        error_message=error_message,
    )


class TestSecretScanRegex:
    """Tests for _scan_for_secrets() — keyword + high-entropy adjacency."""

    # --- True positives (must detect) ---

    def test_bearer_token_detected(self) -> None:
        token = _fixture_secret(
            "eyJhbGciOi",
            "JIUzI1NiIs",
            "InR5cCI6Ik",
            "pXVCJ9.dG",
            "VzdDEyMzQ1",
            "Njc4OTA",
        )
        text = f"Authorization: Bearer {token}"
        assert len(_scan_for_secrets(text)) > 0

    def test_api_key_with_high_entropy_detected(self) -> None:
        api_key = _fixture_secret(
            "sk-",
            "abcdefghijklm",
            "nopqrstuvwxyz",
            "1234567890",
            "ABCDEFGH",
        )
        text = f"API key: {api_key}"
        assert len(_scan_for_secrets(text)) > 0

    def test_token_with_long_value_detected(self) -> None:
        token = _fixture_secret(
            "eyJzdWIiOi",
            "J1c2VyMTIz",
            "NDU2Nzg5",
            "MEFCQ0RFR",
            "kdISUpLTE",
            "1OT1BRUlNU",
            "VVZXWFla",
        )
        text = f"token={token}"
        assert len(_scan_for_secrets(text)) > 0

    def test_secret_with_long_value_detected(self) -> None:
        # \b word boundary requires "secret" to start at a word boundary
        value = _fixture_secret(
            "abcdefghijklm",
            "nopqrstuvwxyz",
            "1234567890",
            "ABCDE",
        )
        text = f"secret: {value}"
        assert len(_scan_for_secrets(text)) > 0

    def test_auth_header_with_hash_detected(self) -> None:
        digest = _fixture_secret(
            "abcdef1234",
            "567890abcd",
            "ef123456",
            "7890abcdef12",
        )
        text = f"auth: sha256:{digest}"
        assert len(_scan_for_secrets(text)) > 0

    # --- False negatives (must NOT detect) ---

    def test_ac32_api_key_metadata_no_false_positive(self) -> None:
        """AC32: 'API key metadata' in a plain description must NOT trigger failure."""
        text = "This tool accepts an API key as a parameter for authentication metadata."
        result = _scan_for_secrets(text)
        assert len(result) == 0, f"AC32 FAIL: false positive on plain text: {result}"

    def test_short_value_not_detected(self) -> None:
        """Values under 32 chars must not trigger — avoids false positives on short vars."""
        text = "key=short"
        assert len(_scan_for_secrets(text)) == 0

    def test_keyword_without_value_not_detected(self) -> None:
        text = "The token field is optional."
        assert len(_scan_for_secrets(text)) == 0

    def test_description_with_auth_word_no_false_positive(self) -> None:
        text = "This endpoint requires auth. Provide credentials in the request headers."
        assert len(_scan_for_secrets(text)) == 0

    def test_bearer_keyword_alone_no_false_positive(self) -> None:
        text = "Supports bearer authentication scheme"
        assert len(_scan_for_secrets(text)) == 0


class TestCacheSecretScanIntegration:
    """Integration tests for _write_cache blocking on secret detection."""

    def test_cache_write_blocked_on_bearer_token(self, tmp_path: Path) -> None:
        token = _fixture_secret(
            "eyJhbGciOi",
            "JIUzI1NiIs",
            "InR5cCI6Ik",
            "pXVCJ9.ey",
            "JzdWIiOiJ1",
            "c2VyMTIzN",
            "DU2Nzg5MA",
        )
        result = _make_result(f"Bearer {token}")
        cache_file = tmp_path / "blocked.json"
        _write_cache(result, cache_file)
        assert not cache_file.exists(), "Cache write MUST be blocked when secret detected"

    def test_cache_write_allowed_on_plain_error(self, tmp_path: Path) -> None:
        result = _make_result("Connection refused — server is down")
        cache_file = tmp_path / "allowed.json"
        _write_cache(result, cache_file)
        assert cache_file.exists(), "Cache write MUST succeed when no secrets in result"

    def test_cache_write_allowed_on_api_key_metadata(self, tmp_path: Path) -> None:
        """AC32: 'API key metadata' in error message must NOT block cache write."""
        result = _make_result("Tool requires API key metadata as input parameter.")
        cache_file = tmp_path / "metadata.json"
        _write_cache(result, cache_file)
        assert cache_file.exists(), (
            "AC32 FAIL: 'API key metadata' in description must NOT block cache write"
        )
