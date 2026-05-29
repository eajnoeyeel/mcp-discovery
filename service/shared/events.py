"""Shared event parsing helpers for MLP Lambda handlers."""

import json
from typing import Any

from pydantic import BaseModel


class RequestContext(BaseModel):
    """Normalized Lambda request context."""

    request_id: str = "local"
    remaining_time_ms: int = 30_000
    http_method: str = "POST"


def parse_event_body(event: dict[str, Any]) -> dict[str, Any]:
    """Return the request body as a dict.

    API Gateway events commonly encode the body as JSON text. If the body is
    already a dict, return it unchanged. Otherwise fall back to the event.
    """
    raw_body = event.get("body")
    if isinstance(raw_body, str):
        return json.loads(raw_body or "{}")
    if isinstance(raw_body, dict):
        return raw_body
    return event


def build_request_context(event: dict[str, Any], context: Any) -> RequestContext:
    """Extract request metadata from an AWS Lambda invocation."""
    request_context = event.get("requestContext", {})
    http_context = request_context.get("http", {})
    return RequestContext(
        request_id=getattr(context, "aws_request_id", "local"),
        remaining_time_ms=getattr(context, "get_remaining_time_in_millis", lambda: 30_000)(),
        http_method=http_context.get("method", "POST"),
    )
