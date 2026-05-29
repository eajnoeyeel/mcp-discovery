"""API Key Authorizer Lambda — lightweight static key check.

Validates the ``x-api-key`` header against the ``MLP_API_KEY`` environment
variable.  Uses payload format 2.0 with simple responses so the function
returns a plain boolean instead of a full IAM policy document.

Design rationale (I2 — Denial-of-Wallet protection):
  - HttpApi does not support native Usage Plans / API Keys.
  - A Lambda authorizer is the lightest mechanism that keeps HttpApi
    (cheaper, faster than REST API) while gating every route.
  - The authorizer result is cached by API Gateway for up to 300 s
    (configured via ``AuthorizerResultTtlInSeconds`` in the SAM template),
    so the Lambda is NOT invoked on every single request.
  - CORS preflight (OPTIONS) is handled by API Gateway itself before the
    authorizer runs, so no special bypass is needed.
"""

import os
from typing import Any

# Read once at cold-start; never changes during the lifetime of the container.
_EXPECTED_KEY: str = os.environ.get("MLP_API_KEY", "")


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Return simple authorizer response (payload format 2.0).

    Expected header: ``x-api-key: <key>``

    Returns ``{"isAuthorized": true}`` on match, ``{"isAuthorized": false}``
    otherwise.  API Gateway translates ``false`` into a 403 Forbidden.
    """
    if not _EXPECTED_KEY:
        # Fail-closed: if no key is configured, deny everything.
        return {"isAuthorized": False}

    # Payload format 2.0 lowercases all header names.
    headers: dict[str, str] = event.get("headers") or {}
    provided_key: str = headers.get("x-api-key", "")

    is_authorized: bool = provided_key == _EXPECTED_KEY
    return {"isAuthorized": is_authorized}
