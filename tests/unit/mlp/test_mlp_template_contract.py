"""Template contract tests for MLP release-time runtime guards."""

from pathlib import Path

import yaml


class _IgnoreTagLoader(yaml.SafeLoader):
    pass


def _ignore_tag(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> None:
    return None


_IgnoreTagLoader.add_multi_constructor("!", _ignore_tag)


def _load_cloudformation_yaml(path: str) -> dict:
    return yaml.load(Path(path).read_text(), Loader=_IgnoreTagLoader)  # noqa: S506


def test_template_contains_core_runtime_guards():
    yaml_text = Path("service/template.yaml").read_text()
    assert "MlpApiKey" in yaml_text
    assert "Tracing: Active" in yaml_text
    assert "SearchLatencyAlarm" in yaml_text
    assert "IndexDLQ" in yaml_text
    assert "IndexDLQConsumerFunction" in yaml_text
    assert "CatalogFunction" in yaml_text
    assert "DashboardFunction" in yaml_text
    assert "/api/platform/stats" in yaml_text
    assert "/api/providers/dashboard" in yaml_text
    assert "/api/providers/servers/discovery" in yaml_text
    assert "/api/providers/tools/{tool_id}/metadata-refresh-preview" in yaml_text
    assert "/api/providers/tools/{tool_id}/metadata-refresh-apply" in yaml_text
    assert "BridgeMcpEndpoint" in yaml_text
    assert "ApiUrl" in yaml_text


def test_template_contains_comprehensive_alarms():
    """Every critical function must have at least one CloudWatch alarm."""
    yaml_text = Path("service/template.yaml").read_text()
    # Index path alarms
    assert "IndexErrorAlarm" in yaml_text
    assert "IndexThrottleAlarm" in yaml_text
    # Execute path alarms
    assert "ExecuteErrorAlarm" in yaml_text
    assert "ExecuteLatencyAlarm" in yaml_text
    # Bridge path alarms
    assert "BridgeErrorAlarm" in yaml_text
    assert "BridgeLatencyAlarm" in yaml_text
    # Register path alarm
    assert "RegisterErrorAlarm" in yaml_text
    # DLQ depth alarms
    assert "IndexDLQDepthAlarm" in yaml_text


def test_template_contains_bridge_warming():
    yaml_text = Path("service/template.yaml").read_text()
    assert "BridgeWarmingRule" in yaml_text
    assert "BridgeWarmingPermission" in yaml_text


def test_template_no_longer_contains_operability_sync_resources():
    yaml_text = Path("service/template.yaml").read_text()
    assert "OperabilitySyncFunction" not in yaml_text
    assert "OperabilitySyncDLQConsumerFunction" not in yaml_text
    assert "OperabilitySyncDLQ" not in yaml_text


def test_template_builds_bridge_as_image():
    yaml_text = Path("service/template.yaml").read_text()
    assert "BridgeFunction:" in yaml_text
    assert "Dockerfile: service/lambdas/bridge/Dockerfile" in yaml_text
    assert 'CONFIDENCE_GAP_THRESHOLD_HYBRID: "0.005"' in yaml_text


def test_template_contains_index_replay():
    yaml_text = Path("service/template.yaml").read_text()
    assert "IndexReplayFunction" in yaml_text


def test_bridge_timeout_accommodates_execute():
    """BridgeFunction timeout must be >= ExecuteFunction timeout."""
    template = _load_cloudformation_yaml("service/template.yaml")
    resources = template["Resources"]
    bridge_timeout = resources["BridgeFunction"]["Properties"].get(
        "Timeout", template["Globals"]["Function"]["Timeout"]
    )
    execute_timeout = resources["ExecuteFunction"]["Properties"]["Timeout"]
    assert bridge_timeout >= execute_timeout, (
        f"BridgeFunction timeout ({bridge_timeout}s) must be >= "
        f"ExecuteFunction timeout ({execute_timeout}s)"
    )


def test_bridge_routes_opt_out_of_default_api_key_authorizer():
    template = _load_cloudformation_yaml("service/template.yaml")
    bridge_events = template["Resources"]["BridgeFunction"]["Properties"]["Events"]

    assert bridge_events["BridgePost"]["Properties"]["Auth"]["Authorizer"] == "NONE"
    assert bridge_events["BridgeGet"]["Properties"]["Auth"]["Authorizer"] == "NONE"


def test_template_deploys_delegated_oauth_routes_and_secret_permissions():
    template = _load_cloudformation_yaml("service/template.yaml")
    resources = template["Resources"]

    assert "MlpPublicApiBaseUrl" in template["Parameters"]
    assert (
        resources["RegisterFunction"]["Properties"]["Environment"]["Variables"][
            "MLP_PUBLIC_API_BASE_URL"
        ]
        is None
    )

    register_events = resources["RegisterFunction"]["Properties"]["Events"]
    assert "/api/oauth/providers/bootstrap/discover" in str(register_events)
    assert "/api/oauth/providers/{provider_key}/enable" in str(register_events)

    oauth_start = resources["OAuthStartFunction"]["Properties"]["Events"]["OAuthStartApi"]
    assert oauth_start["Properties"]["Path"] == "/api/oauth/providers/{provider}/start"
    assert oauth_start["Properties"]["Method"] == "POST"

    oauth_callback = resources["OAuthCallbackFunction"]["Properties"]["Events"]["OAuthCallbackApi"]
    assert oauth_callback["Properties"]["Path"] == "/api/oauth/providers/{provider}/callback"
    assert oauth_callback["Properties"]["Method"] == "GET"
    assert oauth_callback["Properties"]["Auth"]["Authorizer"] == "NONE"

    template_text = Path("service/template.yaml").read_text()
    assert "secretsmanager:CreateSecret" in template_text
    assert "secretsmanager:PutSecretValue" in template_text
    assert "secretsmanager:GetSecretValue" in template_text
    assert "secret:mlp/*" in template_text


def test_template_local_sets_local_event_mode():
    template = _load_cloudformation_yaml("service/template.local.yaml")
    variables = template["Globals"]["Function"]["Environment"]["Variables"]
    assert variables["MLP_EVENT_MODE"] == "local_direct"


def test_docker_compose_local_sets_local_event_mode():
    compose = yaml.safe_load(Path("service/docker-compose.local.yml").read_text())
    assert compose["services"]["backend"]["environment"]["MLP_EVENT_MODE"] == "local_direct"
