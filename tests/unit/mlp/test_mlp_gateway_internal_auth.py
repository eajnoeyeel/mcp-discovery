"""Tests for gateway internal API request signing."""

from service.gateway.internal_auth import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    build_internal_auth_headers,
    verify_internal_auth,
)


def test_build_internal_auth_headers_includes_signature_and_timestamp() -> None:
    headers = build_internal_auth_headers(
        secret="shared-secret",
        method="POST",
        path="/gateway/execute",
        body=b'{"server_id":"srv"}',
        timestamp="1700000000",
    )

    assert headers[TIMESTAMP_HEADER] == "1700000000"
    assert headers[SIGNATURE_HEADER]


def test_verify_internal_auth_accepts_matching_signature() -> None:
    body = b'{"server_id":"srv"}'
    headers = build_internal_auth_headers(
        secret="shared-secret",
        method="POST",
        path="/gateway/execute",
        body=body,
        timestamp="1700000000",
    )

    assert verify_internal_auth(
        secret="shared-secret",
        method="POST",
        path="/gateway/execute",
        body=body,
        headers=headers,
        current_time=1700000000,
    )


def test_verify_internal_auth_rejects_stale_timestamp() -> None:
    body = b'{"server_id":"srv"}'
    headers = build_internal_auth_headers(
        secret="shared-secret",
        method="POST",
        path="/gateway/execute",
        body=body,
        timestamp="1700000000",
    )

    assert not verify_internal_auth(
        secret="shared-secret",
        method="POST",
        path="/gateway/execute",
        body=body,
        headers=headers,
        current_time=1700000601,
        max_age_seconds=300,
    )


def test_verify_internal_auth_rejects_tampered_body() -> None:
    headers = build_internal_auth_headers(
        secret="shared-secret",
        method="POST",
        path="/gateway/execute",
        body=b'{"server_id":"srv"}',
        timestamp="1700000000",
    )

    assert not verify_internal_auth(
        secret="shared-secret",
        method="POST",
        path="/gateway/execute",
        body=b'{"server_id":"other"}',
        headers=headers,
        current_time=1700000000,
    )
