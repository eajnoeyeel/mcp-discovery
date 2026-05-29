"""Tests for safe MLP predeployment rehearsal orchestration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from service.build.predeploy import (
    build_check_commands,
    build_check_commands_with_options,
    run_commands,
    summarize_results,
)


def _flatten(commands: list[list[str]]) -> str:
    return "\n".join(" ".join(command) for command in commands)


def test_build_check_commands_includes_required_rehearsal_steps() -> None:
    commands = build_check_commands(
        image_identifier="123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/mlp-gateway:test",
        gateway_base_url="https://gateway.example.com",
    )

    rendered = _flatten(commands)

    assert "service.build.doctor" in rendered
    assert "service.build.build" in rendered
    assert "service.build.smoke" in rendered
    assert "print_gateway_deploy_manifest.py" in rendered
    assert "service.harness.gateway_health_probe --sample" in rendered
    assert "service.harness.live_gateway_transport_proof" in rendered
    assert "test_migration_034_mcp_auth_requirements_uniqueness.py" in rendered
    assert "test_migration_035_replace_mcp_auth_requirements_rpc.py" in rendered
    assert "test_migration_036_oauth_provider_bootstrap_automation.py" in rendered


def test_build_check_commands_avoid_deployment_mutations() -> None:
    commands = build_check_commands(
        image_identifier="example/image:local",
        gateway_base_url="https://gateway.example.com",
    )

    rendered = _flatten(commands)

    assert "aws" not in rendered
    assert "sam deploy" not in rendered
    assert "docker push" not in rendered


def test_build_check_commands_can_include_live_runtime_schema_gate() -> None:
    commands = build_check_commands_with_options(
        image_identifier="example/image:local",
        gateway_base_url="https://gateway.example.com",
        verify_runtime_schema=True,
    )

    rendered = _flatten(commands)

    assert "service/scripts/verify_runtime_schema.py" in rendered
    assert "--verify-mcp-auth-requirements-uniqueness" in rendered


def test_run_commands_collects_pass_fail_results_without_stopping_early(
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0 if command[0] != "fail" else 23,
            stdout=f"stdout for {command[0]}",
            stderr=f"stderr for {command[0]}",
        )

    results = run_commands(
        [["pass"], ["fail"], ["after-failure"]],
        cwd=tmp_path,
        runner=runner,
    )

    assert [command for command, _kwargs in calls] == [["pass"], ["fail"], ["after-failure"]]
    assert all(kwargs["capture_output"] is True for _command, kwargs in calls)
    assert all(kwargs["text"] is True for _command, kwargs in calls)
    assert all(kwargs["cwd"] == tmp_path for _command, kwargs in calls)
    assert results == [
        {
            "command": ["pass"],
            "ok": True,
            "stdout": "stdout for pass",
            "stderr": "stderr for pass",
        },
        {
            "command": ["fail"],
            "ok": False,
            "stdout": "stdout for fail",
            "stderr": "stderr for fail",
        },
        {
            "command": ["after-failure"],
            "ok": True,
            "stdout": "stdout for after-failure",
            "stderr": "stderr for after-failure",
        },
    ]


def test_summarize_results_counts_runs_and_pass_fail_rate() -> None:
    assert summarize_results([]) == {
        "runs": 0,
        "passed": 0,
        "failed": 0,
        "success_rate": 0.0,
    }

    assert summarize_results(
        [
            {"command": ["pass"], "ok": True, "stdout": "", "stderr": ""},
            {"command": ["fail"], "ok": False, "stdout": "", "stderr": ""},
            {"command": ["also-pass"], "ok": True, "stdout": "", "stderr": ""},
        ]
    ) == {
        "runs": 3,
        "passed": 2,
        "failed": 1,
        "success_rate": 2 / 3,
    }
