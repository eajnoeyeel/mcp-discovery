import pytest


def test_valid_transition_active_to_quarantined():
    from mcp_discovery.operability.lifecycle import transition

    assert transition("active", "quarantined") == "quarantined"


def test_valid_transition_unreachable_to_active():
    from mcp_discovery.operability.lifecycle import transition

    assert transition("unreachable", "active") == "active"


def test_invalid_transition_pending_to_quarantined():
    from mcp_discovery.operability.lifecycle import InvalidTransitionError, transition

    with pytest.raises(InvalidTransitionError):
        transition("pending", "quarantined")


def test_invalid_transition_deprecated_to_active():
    from mcp_discovery.operability.lifecycle import InvalidTransitionError, transition

    with pytest.raises(InvalidTransitionError):
        transition("deprecated", "active")


def test_derive_status_active():
    from mcp_discovery.operability.lifecycle import derive_status

    status = derive_status(
        call_count=50, success_rate=0.95, operational_freshness_days=5, deprecated=False
    )
    assert status == "active"


def test_derive_status_quarantined():
    from mcp_discovery.operability.lifecycle import derive_status

    status = derive_status(
        call_count=50, success_rate=0.05, operational_freshness_days=5, deprecated=False
    )
    assert status == "quarantined"


def test_derive_status_stale():
    from mcp_discovery.operability.lifecycle import derive_status

    status = derive_status(
        call_count=50, success_rate=0.95, operational_freshness_days=100, deprecated=False
    )
    assert status == "stale"


def test_derive_status_deprecated():
    from mcp_discovery.operability.lifecycle import derive_status

    status = derive_status(
        call_count=50, success_rate=0.95, operational_freshness_days=5, deprecated=True
    )
    assert status == "deprecated"


def test_derive_status_cold_start_stays_active():
    from mcp_discovery.operability.lifecycle import derive_status

    status = derive_status(
        call_count=3, success_rate=0.0, operational_freshness_days=None, deprecated=False
    )
    assert status == "active"
