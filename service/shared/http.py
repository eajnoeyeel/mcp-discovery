"""HTTP response helpers for MLP Lambda handlers."""

import json
from typing import Any


def json_response(status_code: int, body: Any) -> dict[str, Any]:
    # Use default=str so Lambda/API Gateway responses stay resilient when handlers
    # include small non-JSON-serializable values in error or debug payloads.
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def error_response(status_code: int, message: str) -> dict[str, Any]:
    return json_response(status_code, {"error": message})
