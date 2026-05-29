"""Print the deploy-time contract for the App Runner gateway."""

from __future__ import annotations

import argparse
import json
from typing import Any

REQUIRED_ENV = [
    "GATEWAY_INTERNAL_AUTH_SECRET",
    "GATEWAY_BASE_URL",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "AWS_REGION",
]


def build_gateway_manifest(*, image_identifier: str, gateway_base_url: str) -> dict[str, Any]:
    """Return the config contract for the App Runner gateway rollout."""

    return {
        "service_name": "mlp-gateway",
        "runtime": "aws-apprunner",
        "image_identifier": image_identifier,
        "gateway_base_url": gateway_base_url,
        "required_env": REQUIRED_ENV,
        "health_endpoint": "/gateway/health",
        "container_port": 8000,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Print the App Runner gateway deploy manifest.")
    parser.add_argument("--image-identifier", required=True)
    parser.add_argument("--gateway-base-url", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_gateway_manifest(
                image_identifier=args.image_identifier,
                gateway_base_url=args.gateway_base_url,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
