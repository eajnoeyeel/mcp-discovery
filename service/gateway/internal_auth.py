"""HMAC signing helpers for Lambda -> gateway internal requests."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Mapping

SIGNATURE_HEADER = "X-MLP-Internal-Signature"
TIMESTAMP_HEADER = "X-MLP-Internal-Timestamp"


def _header_value(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def _sign(secret: str, method: str, path: str, body: bytes, timestamp: str) -> str:
    payload = b"\n".join(
        [method.upper().encode("utf-8"), path.encode("utf-8"), timestamp.encode("utf-8"), body]
    )
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def build_internal_auth_headers(
    *, secret: str, method: str, path: str, body: bytes, timestamp: str
) -> dict[str, str]:
    return {
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: _sign(secret, method, path, body, timestamp),
    }


def verify_internal_auth(
    *,
    secret: str,
    method: str,
    path: str,
    body: bytes,
    headers: Mapping[str, str],
    current_time: int | None = None,
    max_age_seconds: int = 300,
) -> bool:
    timestamp = _header_value(headers, TIMESTAMP_HEADER)
    provided = _header_value(headers, SIGNATURE_HEADER)
    if not timestamp or not provided:
        return False

    try:
        timestamp_int = int(timestamp)
    except ValueError:
        return False

    now = int(time.time()) if current_time is None else current_time
    if abs(now - timestamp_int) > max_age_seconds:
        return False

    expected = _sign(secret, method, path, body, timestamp)
    return hmac.compare_digest(provided, expected)
