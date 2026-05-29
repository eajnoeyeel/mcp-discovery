"""Test for pool-refresh-nightly.yml workflow structure."""

import re
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def nightly_workflow_path():
    """Path to the nightly workflow file."""
    repo_root = Path(__file__).parent.parent.parent.parent
    return repo_root / ".github" / "workflows" / "pool-refresh-nightly.yml"


def test_nightly_workflow_exists(nightly_workflow_path):
    """Assert that pool-refresh-nightly.yml exists."""
    assert nightly_workflow_path.exists(), f"Workflow file not found at {nightly_workflow_path}"


def test_nightly_workflow_parses(nightly_workflow_path):
    """Assert that the workflow YAML parses without syntax errors."""
    with open(nightly_workflow_path) as f:
        content = f.read()

    # YAML should parse without error
    workflow = yaml.safe_load(content)
    assert workflow is not None, "Workflow YAML is empty or invalid"
    assert "jobs" in workflow, "Workflow has no jobs"


def test_nightly_workflow_has_dispatch_trigger(nightly_workflow_path):
    """Assert that workflow_dispatch trigger is present."""
    with open(nightly_workflow_path) as f:
        content = f.read()

    workflow = yaml.safe_load(content)
    triggers = workflow.get("on", {})

    # Must have workflow_dispatch (NOT schedule)
    assert "workflow_dispatch" in triggers, (
        "workflow_dispatch trigger is missing. This is mandatory for ADR-0018."
    )


def test_nightly_workflow_no_schedule_trigger(nightly_workflow_path):
    """Assert that schedule trigger is NOT present (workflow_dispatch only)."""
    with open(nightly_workflow_path) as f:
        content = f.read()

    workflow = yaml.safe_load(content)
    triggers = workflow.get("on", {})

    # schedule is NOT allowed in this PR (ADR-0019 stub only)
    assert "schedule" not in triggers, (
        "schedule trigger found. Per ADR-0019, nightly workflow must be workflow_dispatch-only "
        "in this PR. Cron enablement is deferred to follow-up ADR acceptance."
    )


def test_nightly_workflow_dispatch_inputs(nightly_workflow_path):
    """Assert that workflow_dispatch has expected inputs."""
    with open(nightly_workflow_path) as f:
        content = f.read()

    workflow = yaml.safe_load(content)
    dispatch = workflow.get("on", {}).get("workflow_dispatch", {})

    assert "inputs" in dispatch, "workflow_dispatch has no inputs"

    inputs = dispatch["inputs"]
    assert "apply_reconcile" in inputs, "Missing apply_reconcile input"
    assert "force_reprobe" in inputs, "Missing force_reprobe input"


def test_nightly_workflow_secret_scan_present(nightly_workflow_path):
    """Assert that secret scan step exists before artifact upload."""
    with open(nightly_workflow_path) as f:
        content = f.read()

    # Check raw YAML for secret-scan step
    assert "secret-scan" in content, "Secret scan step is missing"
    assert "Secret scan" in content, "Secret scan step name is missing"


def test_nightly_workflow_timeout(nightly_workflow_path):
    """Assert that timeout-minutes is set appropriately."""
    with open(nightly_workflow_path) as f:
        content = f.read()

    workflow = yaml.safe_load(content)
    job = list(workflow.get("jobs", {}).values())[0]

    assert "timeout-minutes" in job, "timeout-minutes not set"
    timeout = job["timeout-minutes"]
    assert timeout <= 45, f"timeout-minutes ({timeout}) exceeds recommended 45 minutes"
    assert timeout >= 30, f"timeout-minutes ({timeout}) should be at least 30 minutes"


def test_nightly_workflow_upload_artifact(nightly_workflow_path):
    """Assert that artifact upload step exists with retention-days."""
    with open(nightly_workflow_path) as f:
        content = f.read()

    workflow = yaml.safe_load(content)
    job = list(workflow.get("jobs", {}).values())[0]
    steps = job.get("steps", [])

    # Find upload-artifact step
    upload_step = None
    for step in steps:
        if "upload-artifact" in str(step.get("uses", "")):
            upload_step = step
            break

    assert upload_step is not None, "upload-artifact step is missing"

    # retention-days is inside the 'with' section
    with_section = upload_step.get("with", {})
    assert "retention-days" in with_section, "retention-days not set in upload with"
    assert with_section["retention-days"] == 7, "retention-days should be 7"


def test_nightly_workflow_step_order(nightly_workflow_path):
    """Assert that secret-scan happens before artifact upload."""
    with open(nightly_workflow_path) as f:
        content = f.read()

    # Find positions of key steps
    secret_scan_pos = content.find("Secret scan")
    upload_pos = content.find("Upload probe snapshot")

    assert secret_scan_pos != -1, "Secret scan step not found"
    assert upload_pos != -1, "Upload artifact step not found"
    assert secret_scan_pos < upload_pos, (
        "Secret scan must come BEFORE artifact upload. "
        "This ensures secrets are not leaked in artifacts."
    )


def test_nightly_workflow_no_hardcoded_secrets(nightly_workflow_path):
    """Assert that no hardcoded secrets appear in the workflow file."""
    with open(nightly_workflow_path) as f:
        content = f.read()

    # Check for common secret patterns (basic check)
    secret_patterns = [
        r"api[_-]?key\s*[:=]",
        r"password\s*[:=]",
        r"token\s*[:=].*[A-Za-z0-9]{32,}",
        r"secret\s*[:=].*[A-Za-z0-9]{32,}",
    ]

    for pattern in secret_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        # Filter out comments and description fields
        non_comment_matches = [m for m in matches if not m.startswith("#")]
        assert not non_comment_matches, f"Possible hardcoded secret pattern found: {pattern}"


def test_nightly_workflow_valid_step_names(nightly_workflow_path):
    """Assert that all steps have descriptive names."""
    with open(nightly_workflow_path) as f:
        content = f.read()

    workflow = yaml.safe_load(content)
    job = list(workflow.get("jobs", {}).values())[0]
    steps = job.get("steps", [])

    for step in steps:
        name = step.get("name")
        assert name, "Step is missing a name"
        assert len(name) > 5, f"Step name too short: {name}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
