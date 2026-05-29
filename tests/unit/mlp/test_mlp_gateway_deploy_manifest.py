"""Tests for gateway App Runner deploy manifest generation."""

from service.scripts.print_gateway_deploy_manifest import build_gateway_manifest


def test_build_gateway_manifest_reports_required_env() -> None:
    manifest = build_gateway_manifest(
        image_identifier="123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/mlp-gateway:latest",
        gateway_base_url="https://gateway.example.com",
    )

    assert manifest["service_name"] == "mlp-gateway"
    assert manifest["runtime"] == "aws-apprunner"
    assert "GATEWAY_INTERNAL_AUTH_SECRET" in manifest["required_env"]
    assert manifest["image_identifier"].endswith(":latest")
