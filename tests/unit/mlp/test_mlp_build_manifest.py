"""Tests for the MLP Lambda build manifest."""

from service.build.manifest import FUNCTIONS, MLP_DIR, MLP_RUNTIME_PACKAGES, SRC_DIR


def test_all_declared_src_modules_exist() -> None:
    missing = []
    for function_name, spec in FUNCTIONS.items():
        for module in spec.src_modules:
            if not (SRC_DIR / module).exists():
                missing.append(f"{function_name}:{module}")

    assert missing == []


def test_all_declared_mlp_runtime_packages_exist() -> None:
    missing = [package for package in MLP_RUNTIME_PACKAGES if not (MLP_DIR / package).exists()]

    assert missing == []


def test_gateway_runtime_is_packaged_for_execute_lambda_internal_auth() -> None:
    assert "gateway" in MLP_RUNTIME_PACKAGES


def test_delegated_oauth_lambdas_are_packaged() -> None:
    assert FUNCTIONS["OAuthStartFunction"].handler_dir == "oauth_start"
    assert FUNCTIONS["OAuthCallbackFunction"].handler_dir == "oauth_callback"
    assert FUNCTIONS["OAuthStartFunction"].dep_group == "lambda-register"
    assert FUNCTIONS["OAuthCallbackFunction"].dep_group == "lambda-register"
