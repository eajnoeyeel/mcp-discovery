"""Structured logging helpers for MLP Lambda handlers."""

import json
from typing import Any

from loguru import logger


def build_log_payload(event: str, request_id: str, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"event": event, "request_id": request_id}
    payload.update(fields)
    return payload


def log_info(event: str, request_id: str, **fields: Any) -> dict[str, Any]:
    payload = build_log_payload(event, request_id, **fields)
    logger.info(json.dumps(payload))
    return payload
