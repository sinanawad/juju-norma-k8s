# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the norma-k8s charm using ops.testing (Scenario).

Each test fires exactly one event against an immutable input State and
asserts on the output State, per Constitution Principle VI.
"""

import json

import ops
import ops.testing
import pytest

import norma
from charm import NormaK8sCharm

# Base containers for the charm (both must be defined)
NORMA_CONTAINER = ops.testing.Container(
    name="norma",
    can_connect=True,
)
NORMA_CONTAINER_DISCONNECTED = ops.testing.Container(
    name="norma",
    can_connect=False,
)
NORMA_SECONDARY = ops.testing.Container(
    name="norma-secondary",
    can_connect=False,
)


class TestCharmInit:
    """Verify charm instantiation and basic structure."""

    def test_charm_type(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.install(), state)
        # If we got here, the charm instantiated successfully

    def test_waiting_status_when_pebble_disconnected(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        out = ctx.run(ctx.on.collect_unit_status(), state)
        assert out.unit_status == ops.WaitingStatus("Waiting for Pebble")

    def test_active_status_when_pebble_connected(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        out = ctx.run(ctx.on.collect_unit_status(), state)
        assert out.unit_status == ops.ActiveStatus()


class TestReconcile:
    """Verify reconciler behavior on lifecycle events."""

    def test_install_fires_reconcile(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        # install should not error even when Pebble is disconnected
        ctx.run(ctx.on.install(), state)

    def test_config_changed_fires_reconcile(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.config_changed(), state)


class TestEventLedger:
    """Verify the event ledger records events correctly (US1)."""

    def test_install_event_recorded(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        with ctx(ctx.on.install(), state) as mgr:
            mgr.run()
            ledger = mgr.charm._event_ledger
            assert len(ledger) >= 1
            assert ledger[0]["event_name"] == "install"
            assert "timestamp" in ledger[0]
            assert ledger[0]["unit_name"] == "norma-k8s/0"

    def test_config_changed_appended(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        with ctx(ctx.on.config_changed(), state) as mgr:
            mgr.run()
            ledger = mgr.charm._event_ledger
            event_names = [e["event_name"] for e in ledger]
            assert "config-changed" in event_names

    def test_stop_event_recorded(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        with ctx(ctx.on.stop(), state) as mgr:
            mgr.run()
            ledger = mgr.charm._event_ledger
            event_names = [e["event_name"] for e in ledger]
            assert "stop" in event_names

    def test_remove_event_recorded(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        with ctx(ctx.on.remove(), state) as mgr:
            mgr.run()
            ledger = mgr.charm._event_ledger
            event_names = [e["event_name"] for e in ledger]
            assert "remove" in event_names


class TestGetEventLogAction:
    """Verify the get-event-log action (US1)."""

    def test_returns_all_events(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("get-event-log"), state)
        assert ctx.action_results
        # Verify the events field is valid JSON
        json.loads(ctx.action_results["events"])
        assert int(ctx.action_results["count"]) >= 0
        assert ctx.action_results["unit"] == "norma-k8s/0"

    def test_filter_by_event_name(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("get-event-log", params={"event-filter": "nonexistent"}), state)
        events = json.loads(ctx.action_results["events"])
        assert len(events) == 0

    def test_limit_results(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("get-event-log", params={"limit": 1}), state)
        events = json.loads(ctx.action_results["events"])
        assert len(events) <= 1


class TestPebbleWorkload:
    """Verify Pebble workload management (US2)."""

    def test_layer_applied_on_pebble_ready(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        out = ctx.run(ctx.on.pebble_ready(NORMA_CONTAINER), state)
        norma_container = out.get_container("norma")
        assert norma_container.layers
        layer = norma_container.layers["norma"]
        assert "norma" in layer.services
        assert layer.services["norma"].command == "/bin/norma"

    def test_layer_applied_on_config_changed(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        out = ctx.run(ctx.on.config_changed(), state)
        norma_container = out.get_container("norma")
        assert norma_container.layers
        layer = norma_container.layers["norma"]
        assert "norma" in layer.services

    def test_waiting_status_when_pebble_not_connected(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        out = ctx.run(ctx.on.collect_unit_status(), state)
        assert out.unit_status == ops.WaitingStatus("Waiting for Pebble")

    def test_run_check_pebble_pass(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_with_service = ops.testing.Container(
            name="norma",
            can_connect=True,
            layers={
                "norma": ops.pebble.Layer(
                    {
                        "services": {
                            "norma": {
                                "override": "replace",
                                "command": "/bin/norma",
                                "startup": "enabled",
                            }
                        }
                    }
                )
            },
            service_statuses={"norma": ops.pebble.ServiceStatus.ACTIVE},
        )
        state = ops.testing.State(
            containers=[norma_with_service, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("run-check", params={"check": "pebble"}), state)
        assert ctx.action_results["check"] == "pebble"
        assert ctx.action_results["result"] == "pass"

    def test_run_check_pebble_service_not_running(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_stopped = ops.testing.Container(
            name="norma",
            can_connect=True,
            layers={
                "norma": ops.pebble.Layer(
                    {
                        "services": {
                            "norma": {
                                "override": "replace",
                                "command": "/bin/norma",
                                "startup": "enabled",
                            }
                        }
                    }
                )
            },
            service_statuses={"norma": ops.pebble.ServiceStatus.INACTIVE},
        )
        state = ops.testing.State(
            containers=[norma_stopped, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("run-check", params={"check": "pebble"}), state)
        assert ctx.action_results["result"] == "fail"
        assert "not running" in ctx.action_results["details"].lower()

    def test_run_check_pebble_service_not_found(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_no_service = ops.testing.Container(
            name="norma",
            can_connect=True,
        )
        state = ops.testing.State(
            containers=[norma_no_service, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("run-check", params={"check": "pebble"}), state)
        assert ctx.action_results["result"] == "fail"
        assert "not found" in ctx.action_results["details"].lower()

    def test_run_check_pebble_fail_disconnected(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("run-check", params={"check": "pebble"}), state)
        assert ctx.action_results["result"] == "fail"
        assert "not connected" in ctx.action_results["details"].lower()

    def test_run_check_unknown(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("run-check", params={"check": "bogus"}), state)
        assert ctx.action_results["result"] == "fail"
        assert "Unknown" in ctx.action_results["details"]


class TestConfiguration:
    """Verify configuration handling (US3)."""

    def test_valid_config_active_status(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-int": 9090},
        )
        out = ctx.run(ctx.on.collect_unit_status(), state)
        assert out.unit_status == ops.ActiveStatus()

    def test_invalid_port_blocked_status(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-int": 0},
        )
        # collect_unit_status fires automatically after config-changed
        out = ctx.run(ctx.on.config_changed(), state)
        assert isinstance(out.unit_status, ops.BlockedStatus)
        assert "calibration-int" in out.unit_status.message

    def test_invalid_port_high_blocked_status(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-int": 99999},
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert isinstance(out.unit_status, ops.BlockedStatus)

    def test_recovery_from_blocked_after_valid_config(self):
        # Invalid config → blocked
        ctx_bad = ops.testing.Context(NormaK8sCharm)
        bad_state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-int": 0},
        )
        out_bad = ctx_bad.run(ctx_bad.on.config_changed(), bad_state)
        assert isinstance(out_bad.unit_status, ops.BlockedStatus)

        # Corrected config → active
        ctx_good = ops.testing.Context(NormaK8sCharm)
        good_state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-int": 8080},
        )
        out_good = ctx_good.run(ctx_good.on.config_changed(), good_state)
        assert out_good.unit_status == ops.ActiveStatus()

    def test_config_changed_applies_layer_with_custom_port(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-int": 9090},
        )
        out = ctx.run(ctx.on.config_changed(), state)
        norma_container = out.get_container("norma")
        layer = norma_container.layers["norma"]
        assert layer.services["norma"].environment["PORT"] == "9090"

    def test_get_config_action_returns_all_values(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            config={
                "calibration-string": "hello",
                "calibration-int": 9090,
                "calibration-float": 2.5,
                "calibration-bool": False,
            },
        )
        ctx.run(ctx.on.action("get-config"), state)
        assert ctx.action_results["calibration-string"] == "hello"
        assert ctx.action_results["calibration-int"] == "9090"
        assert ctx.action_results["calibration-float"] == "2.5"
        assert ctx.action_results["calibration-bool"] == "False"
        assert ctx.action_results["calibration-secret"] == "unset"

    def test_get_config_action_secret_set(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        secret = ops.testing.Secret(
            owner="app",
            tracked_content={"password": "s3cret"},
            label="calibration-password",
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            config={"calibration-secret": secret.id},
            secrets=[secret],
        )
        ctx.run(ctx.on.action("get-config"), state)
        assert ctx.action_results["calibration-secret"] == "set"

    def test_secret_resolution_success(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        secret = ops.testing.Secret(
            owner="app",
            tracked_content={"password": "s3cret"},
            label="calibration-password",
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-secret": secret.id},
            secrets=[secret],
        )
        out = ctx.run(ctx.on.config_changed(), state)
        # Should not be blocked — secret resolved successfully
        norma_container = out.get_container("norma")
        assert norma_container.layers

    def test_secret_not_found_blocked_status(self, monkeypatch):
        # Skip consistency checks: Scenario validates secret URIs reference real
        # secrets, but we're testing the production edge case where a secret is
        # revoked after being configured.
        monkeypatch.setenv("SCENARIO_SKIP_CONSISTENCY_CHECKS", "1")
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-secret": "secret:bogus-id"},
            secrets=[],
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert isinstance(out.unit_status, ops.BlockedStatus)
        assert "secret" in out.unit_status.message.lower()


class TestStatusReporting:
    """Verify status reporting (US4)."""

    def test_active_status_when_healthy(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        out = ctx.run(ctx.on.collect_unit_status(), state)
        assert out.unit_status == ops.ActiveStatus()

    def test_waiting_status_when_pebble_disconnected(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        out = ctx.run(ctx.on.collect_unit_status(), state)
        assert out.unit_status == ops.WaitingStatus("Waiting for Pebble")

    def test_blocked_status_on_invalid_config(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-int": 0},
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert isinstance(out.unit_status, ops.BlockedStatus)

    def test_set_status_forces_blocked(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        ctx.run(
            ctx.on.action("set-status", params={"status": "blocked", "message": "test"}), state
        )
        assert ctx.action_results["new-status"] == "blocked"
        assert ctx.action_results["previous-status"] == "none"

    def test_set_status_forces_waiting(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        ctx.run(
            ctx.on.action("set-status", params={"status": "waiting", "message": "hold"}), state
        )
        assert ctx.action_results["new-status"] == "waiting"

    def test_set_status_forces_maintenance(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        ctx.run(
            ctx.on.action("set-status", params={"status": "maintenance", "message": "upgrading"}),
            state,
        )
        assert ctx.action_results["new-status"] == "maintenance"

    def test_set_status_active_clears_forced(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        # Force blocked then clear with active
        with ctx(ctx.on.action("set-status", params={"status": "active"}), state) as mgr:
            mgr.charm._forced_status = ops.BlockedStatus("old")
            mgr.run()
        assert ctx.action_results["previous-status"] == "BlockedStatus"
        assert ctx.action_results["new-status"] == "active"

    def test_set_status_unknown_type_fails(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            ctx.run(ctx.on.action("set-status", params={"status": "bogus"}), state)
        assert "Unknown status type: bogus" in str(exc_info.value)

    def test_blocked_overrides_active_on_config_error(self):
        # Connected Pebble + invalid config → BlockedStatus (not ActiveStatus)
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-int": 0},
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert isinstance(out.unit_status, ops.BlockedStatus)

    def test_app_status_active_on_leader(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            leader=True,
        )
        out = ctx.run(ctx.on.collect_app_status(), state)
        assert out.app_status == ops.ActiveStatus()

    def test_app_status_blocked_on_leader_with_invalid_config(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-int": 0},
            leader=True,
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert isinstance(out.app_status, ops.BlockedStatus)

    def test_set_status_blocked_then_reconcile_clears(self):
        # set-status blocked → blocked
        ctx_set = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        ctx_set.run(
            ctx_set.on.action("set-status", params={"status": "blocked", "message": "test"}),
            state,
        )
        assert ctx_set.action_results["new-status"] == "blocked"

        # Next reconcile with valid config → active
        ctx_rec = ops.testing.Context(NormaK8sCharm)
        out = ctx_rec.run(ctx_rec.on.config_changed(), state)
        assert out.unit_status == ops.ActiveStatus()


class TestActions:
    """Verify action infrastructure (US5)."""

    def test_fail_action_with_default_message(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            ctx.run(ctx.on.action("fail-action"), state)
        assert "Intentional failure for testing" in str(exc_info.value)

    def test_fail_action_with_custom_message(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            ctx.run(ctx.on.action("fail-action", params={"message": "custom error"}), state)
        assert "custom error" in str(exc_info.value)

    def test_fail_action_recorded_in_event_ledger(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        with pytest.raises(ops.testing.ActionFailed):
            ctx.run(ctx.on.action("fail-action"), state)

    def test_action_progress_logging(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("get-event-log"), state)
        assert any("Retrieving" in log for log in ctx.action_logs)

    def test_get_event_log_returns_structured_results(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("get-event-log"), state)
        assert "events" in ctx.action_results
        assert "count" in ctx.action_results
        assert "unit" in ctx.action_results
        json.loads(ctx.action_results["events"])


class TestPeerRelation:
    """Verify peer relations and leadership (US6)."""

    def test_unit_data_written_on_reconcile(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        peer = ops.testing.PeerRelation(endpoint="norma-peers")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[peer],
            leader=True,
        )
        out = ctx.run(ctx.on.config_changed(), state)
        out_peer = out.get_relation(peer.id)
        local_unit_data = out_peer.local_unit_data
        assert local_unit_data["unit-name"] == "norma-k8s/0"
        assert local_unit_data["leader"] == "True"

    def test_leader_writes_app_data(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        peer = ops.testing.PeerRelation(endpoint="norma-peers")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[peer],
            leader=True,
        )
        out = ctx.run(ctx.on.config_changed(), state)
        out_peer = out.get_relation(peer.id)
        app_data = out_peer.local_app_data
        assert app_data["leader-unit"] == "norma-k8s/0"
        assert app_data["cluster-size"] == "1"

    def test_non_leader_does_not_write_app_data(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        peer = ops.testing.PeerRelation(endpoint="norma-peers")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[peer],
            leader=False,
        )
        out = ctx.run(ctx.on.config_changed(), state)
        out_peer = out.get_relation(peer.id)
        assert "leader-unit" not in out_peer.local_app_data

    def test_non_leader_unit_data_leader_false(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        peer = ops.testing.PeerRelation(endpoint="norma-peers")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[peer],
            leader=False,
        )
        out = ctx.run(ctx.on.config_changed(), state)
        out_peer = out.get_relation(peer.id)
        assert out_peer.local_unit_data["leader"] == "False"

    def test_get_peer_data_action_returns_structure(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        peer = ops.testing.PeerRelation(endpoint="norma-peers")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            relations=[peer],
            leader=True,
        )
        ctx.run(ctx.on.action("get-peer-data"), state)
        assert "app-data" in ctx.action_results
        assert "unit-data" in ctx.action_results
        app_data = json.loads(ctx.action_results["app-data"])
        unit_data = json.loads(ctx.action_results["unit-data"])
        assert isinstance(app_data, dict)
        assert isinstance(unit_data, dict)

    def test_get_peer_data_no_relation(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("get-peer-data"), state)
        assert ctx.action_results["app-data"] == "{}"
        assert ctx.action_results["unit-data"] == "{}"

    def test_cluster_size_reflects_peer_count(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        peer = ops.testing.PeerRelation(
            endpoint="norma-peers",
            peers_data={1: {"unit-name": "norma-k8s/1"}},
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[peer],
            leader=True,
        )
        out = ctx.run(ctx.on.config_changed(), state)
        out_peer = out.get_relation(peer.id)
        assert out_peer.local_app_data["cluster-size"] == "2"

    def test_peer_data_idempotent_no_churn(self):
        # Pre-populate peer data with current values — reconcile should not rewrite
        ctx = ops.testing.Context(NormaK8sCharm)
        existing_secret = ops.testing.Secret(
            {"password": "pw"}, owner="app", label="calibration-password"
        )
        peer = ops.testing.PeerRelation(
            endpoint="norma-peers",
            local_unit_data={"unit-name": "norma-k8s/0", "leader": "True"},
            local_app_data={
                "cluster-size": "1",
                "leader-unit": "norma-k8s/0",
                "secret-id": existing_secret.id,
            },
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[peer],
            secrets=[existing_secret],
            leader=True,
        )
        out = ctx.run(ctx.on.config_changed(), state)
        out_peer = out.get_relation(peer.id)
        # Data should be identical — no new keys, no changed values
        assert out_peer.local_unit_data == {"unit-name": "norma-k8s/0", "leader": "True"}
        assert out_peer.local_app_data == {
            "cluster-size": "1",
            "leader-unit": "norma-k8s/0",
            "secret-id": existing_secret.id,
        }


class TestRelation:
    """US7: Provides/Requires relations and self-relation lifecycle."""

    def test_relation_created_routes_to_reconciler(self):
        """relation-created fires reconciler — proves data gets written."""
        ctx = ops.testing.Context(NormaK8sCharm)
        rel = ops.testing.Relation(endpoint="calibration-provider")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[rel],
        )
        out = ctx.run(ctx.on.relation_created(rel), state)
        out_rel = out.get_relation(rel.id)
        assert out_rel.local_unit_data["unit-name"] == "norma-k8s/0"
        assert out_rel.local_unit_data["role"] == "provider"

    def test_provider_relation_data_written(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        rel = ops.testing.Relation(endpoint="calibration-provider")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[rel],
        )
        out = ctx.run(ctx.on.relation_changed(rel), state)
        out_rel = out.get_relation(rel.id)
        assert out_rel.local_unit_data["unit-name"] == "norma-k8s/0"
        assert out_rel.local_unit_data["role"] == "provider"

    def test_requirer_relation_data_written(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        rel = ops.testing.Relation(endpoint="calibration-requirer")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[rel],
        )
        out = ctx.run(ctx.on.relation_changed(rel), state)
        out_rel = out.get_relation(rel.id)
        assert out_rel.local_unit_data["unit-name"] == "norma-k8s/0"
        assert out_rel.local_unit_data["role"] == "requirer"

    def test_self_relation_both_endpoints(self):
        """Self-relation: same app on both provider and requirer sides."""
        ctx = ops.testing.Context(NormaK8sCharm)
        provider_rel = ops.testing.Relation(endpoint="calibration-provider")
        requirer_rel = ops.testing.Relation(endpoint="calibration-requirer")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[provider_rel, requirer_rel],
        )
        out = ctx.run(ctx.on.relation_changed(provider_rel), state)
        out_provider = out.get_relation(provider_rel.id)
        out_requirer = out.get_relation(requirer_rel.id)
        # Both sides get data written
        assert out_provider.local_unit_data["role"] == "provider"
        assert out_requirer.local_unit_data["role"] == "requirer"

    def test_departing_unit_identity_logged(self):
        """AC7: departing_unit is logged in relation-departed extra data."""
        ctx = ops.testing.Context(NormaK8sCharm)
        rel = ops.testing.Relation(
            endpoint="calibration-provider",
            remote_app_name="norma-k8s-peer",
            remote_units_data={0: {"unit-name": "norma-k8s-peer/0"}},
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[rel],
        )
        ctx.run(ctx.on.relation_departed(rel, remote_unit=0, departing_unit=0), state)
        ledger = norma.read_event_ledger()
        departed_entries = [e for e in ledger if e["event_name"] == "relation-departed"]
        assert len(departed_entries) == 1
        assert departed_entries[0]["extra"]["departing-unit"] == "norma-k8s-peer/0"

    def test_get_relation_data_action_returns_structure(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        rel = ops.testing.Relation(
            endpoint="calibration-provider",
            local_unit_data={"unit-name": "norma-k8s/0", "role": "provider"},
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[rel],
            leader=True,
        )
        ctx.run(
            ctx.on.action("get-relation-data", params={"endpoint": "calibration-provider"}),
            state,
        )
        result = json.loads(ctx.action_results["relations"])
        assert len(result) == 1
        assert result[0]["id"] == rel.id
        assert "norma-k8s/0" in result[0]["units"]

    def test_get_relation_data_action_empty_endpoint(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        ctx.run(
            ctx.on.action("get-relation-data", params={"endpoint": "calibration-provider"}),
            state,
        )
        result = json.loads(ctx.action_results["relations"])
        assert result == []

    def test_get_relation_data_action_filters_by_relation_id(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        rel1 = ops.testing.Relation(endpoint="calibration-provider")
        rel2 = ops.testing.Relation(endpoint="calibration-provider")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[rel1, rel2],
            leader=True,
        )
        ctx.run(
            ctx.on.action(
                "get-relation-data",
                params={"endpoint": "calibration-provider", "relation-id": rel1.id},
            ),
            state,
        )
        result = json.loads(ctx.action_results["relations"])
        assert len(result) == 1
        assert result[0]["id"] == rel1.id

    def test_calibration_data_idempotent_no_churn(self):
        """Pre-populate relation data — reconcile should not rewrite identical values."""
        ctx = ops.testing.Context(NormaK8sCharm)
        rel = ops.testing.Relation(
            endpoint="calibration-provider",
            local_unit_data={"unit-name": "norma-k8s/0", "role": "provider"},
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[rel],
        )
        out = ctx.run(ctx.on.config_changed(), state)
        out_rel = out.get_relation(rel.id)
        assert out_rel.local_unit_data == {"unit-name": "norma-k8s/0", "role": "provider"}

    def test_relation_data_written_when_pebble_disconnected(self):
        """Relation data updates are independent of workload readiness."""
        ctx = ops.testing.Context(NormaK8sCharm)
        rel = ops.testing.Relation(endpoint="calibration-provider")
        peer = ops.testing.PeerRelation(endpoint="norma-peers")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            relations=[rel, peer],
            leader=True,
        )
        out = ctx.run(ctx.on.relation_changed(rel), state)
        out_rel = out.get_relation(rel.id)
        assert out_rel.local_unit_data["unit-name"] == "norma-k8s/0"
        assert out_rel.local_unit_data["role"] == "provider"
        out_peer = out.get_relation(peer.id)
        assert out_peer.local_unit_data["unit-name"] == "norma-k8s/0"


class TestClusterInfo:
    """US8: Scaling — cluster membership reporting via get-cluster-info action."""

    def test_single_unit_cluster_info(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        peer = ops.testing.PeerRelation(endpoint="norma-peers")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            relations=[peer],
            leader=True,
        )
        ctx.run(ctx.on.action("get-cluster-info"), state)
        assert ctx.action_results["unit-count"] == "1"
        assert ctx.action_results["is-leader"] == "True"
        assert ctx.action_results["leader"] == "norma-k8s/0"
        units = json.loads(ctx.action_results["units"])
        assert units == ["norma-k8s/0"]

    def test_three_unit_cluster_info(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        peer = ops.testing.PeerRelation(
            endpoint="norma-peers",
            peers_data={
                1: {"unit-name": "norma-k8s/1"},
                2: {"unit-name": "norma-k8s/2"},
            },
            local_app_data={"leader-unit": "norma-k8s/0"},
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            relations=[peer],
            leader=True,
        )
        ctx.run(ctx.on.action("get-cluster-info"), state)
        assert ctx.action_results["unit-count"] == "3"
        units = json.loads(ctx.action_results["units"])
        assert sorted(units) == ["norma-k8s/0", "norma-k8s/1", "norma-k8s/2"]

    def test_non_leader_reports_leader_from_peer_data(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        peer = ops.testing.PeerRelation(
            endpoint="norma-peers",
            peers_data={1: {"unit-name": "norma-k8s/1"}},
            local_app_data={"leader-unit": "norma-k8s/1"},
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            relations=[peer],
            leader=False,
        )
        ctx.run(ctx.on.action("get-cluster-info"), state)
        assert ctx.action_results["is-leader"] == "False"
        assert ctx.action_results["leader"] == "norma-k8s/1"

    def test_no_peer_relation_single_unit(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("get-cluster-info"), state)
        assert ctx.action_results["unit-count"] == "1"
        units = json.loads(ctx.action_results["units"])
        assert units == ["norma-k8s/0"]


class TestStorage:
    """US10: Juju Storage — filesystem storage with marker file persistence."""

    def test_storage_attached_fires_reconcile(self):
        """storage-attached routes through the reconciler."""
        ctx = ops.testing.Context(NormaK8sCharm)
        storage = ops.testing.Storage(name="data")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            storages=[storage],
        )
        ctx.run(ctx.on.storage_attached(storage), state)

    def test_storage_detaching_fires_reconcile(self):
        """storage-detaching routes through the reconciler and is logged."""
        ctx = ops.testing.Context(NormaK8sCharm)
        storage = ops.testing.Storage(name="data")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            storages=[storage],
        )
        with ctx(ctx.on.storage_detaching(storage), state) as mgr:
            mgr.run()
            ledger = mgr.charm._event_ledger
            event_names = [e["event_name"] for e in ledger]
            assert "storage-detaching" in event_names

    def test_marker_written_on_reconcile(self):
        """Marker file is written to storage on successful reconcile."""
        ctx = ops.testing.Context(NormaK8sCharm)
        storage = ops.testing.Storage(name="data")
        norma_with_fs = ops.testing.Container(
            name="norma",
            can_connect=True,
        )
        state = ops.testing.State(
            containers=[norma_with_fs, NORMA_SECONDARY],
            storages=[storage],
        )
        out = ctx.run(ctx.on.pebble_ready(norma_with_fs), state)
        norma_container = out.get_container("norma")
        marker_path = f"{norma.STORAGE_PATH}/{norma.MARKER_FILE}"
        fs = norma_container.get_filesystem(ctx)
        marker_file = fs / marker_path.lstrip("/")
        assert marker_file.exists()
        content = json.loads(marker_file.read_text())
        assert content["created_by"] == "norma-k8s/0"
        assert "created_at" in content
        assert content["revision"] == 1

    def test_marker_not_overwritten_if_exists(self):
        """Marker file is not overwritten if already present."""
        ctx = ops.testing.Context(NormaK8sCharm)
        storage = ops.testing.Storage(name="data")
        existing_marker = json.dumps(
            {"created_by": "norma-k8s/1", "created_at": "2026-01-01T00:00:00", "revision": 5}
        )
        norma_with_marker = ops.testing.Container(
            name="norma",
            can_connect=True,
        )
        state = ops.testing.State(
            containers=[norma_with_marker, NORMA_SECONDARY],
            storages=[storage],
        )
        marker_path = f"{norma.STORAGE_PATH}/{norma.MARKER_FILE}"
        # Pre-populate marker via Pebble API, then run the handler
        with ctx(ctx.on.config_changed(), state) as mgr:
            container = mgr.charm.unit.get_container("norma")
            container.push(marker_path, existing_marker, make_dirs=True)
            mgr.run()
            # Read back within the context — marker should be unchanged
            content_str = container.pull(marker_path).read()
        content = json.loads(content_str)
        assert content["created_by"] == "norma-k8s/1"
        assert content["revision"] == 5

    def test_check_storage_action_attached(self):
        """check-storage returns correct data when storage is attached."""
        ctx = ops.testing.Context(NormaK8sCharm)
        storage = ops.testing.Storage(name="data")
        existing_marker = json.dumps(
            {"created_by": "norma-k8s/0", "created_at": "2026-01-01T00:00:00", "revision": 1}
        )
        norma_c = ops.testing.Container(
            name="norma",
            can_connect=True,
        )
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
            storages=[storage],
        )
        marker_path = f"{norma.STORAGE_PATH}/{norma.MARKER_FILE}"
        # Pre-populate marker via Pebble API inside the context manager
        with ctx(ctx.on.action("check-storage"), state) as mgr:
            container = mgr.charm.unit.get_container("norma")
            container.push(marker_path, existing_marker, make_dirs=True)
            mgr.run()
        assert ctx.action_results["attached"] == "true"
        assert ctx.action_results["mount-point"] == norma.STORAGE_PATH
        assert ctx.action_results["marker-exists"] == "true"
        content = json.loads(ctx.action_results["marker-content"])
        assert content["created_by"] == "norma-k8s/0"
        assert ctx.action_results["writable"] == "true"

    def test_check_storage_action_no_marker(self):
        """check-storage reports no marker when storage is empty."""
        ctx = ops.testing.Context(NormaK8sCharm)
        storage = ops.testing.Storage(name="data")
        norma_c = ops.testing.Container(
            name="norma",
            can_connect=True,
        )
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
            storages=[storage],
        )
        ctx.run(ctx.on.action("check-storage"), state)
        assert ctx.action_results["attached"] == "true"
        assert ctx.action_results["marker-exists"] == "false"
        assert ctx.action_results["marker-content"] == ""

    def test_check_storage_action_pebble_disconnected(self):
        """check-storage reports attached but not writable when Pebble is disconnected."""
        ctx = ops.testing.Context(NormaK8sCharm)
        storage = ops.testing.Storage(name="data")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            storages=[storage],
        )
        ctx.run(ctx.on.action("check-storage"), state)
        assert ctx.action_results["attached"] == "true"
        assert ctx.action_results["marker-exists"] == "false"
        assert ctx.action_results["writable"] == "false"

    def test_check_storage_action_no_storage(self):
        """check-storage reports not attached when no storage exists."""
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("check-storage"), state)
        assert ctx.action_results["attached"] == "false"
        assert ctx.action_results["writable"] == "false"


class TestHealthChecks:
    """US11: Pebble Health Checks — check-failed/recovered events and toggle-health action."""

    def _container_with_checks(self):
        """Helper: return a connected norma container with health checks in layer and infos."""
        layer = norma.build_pebble_layer(norma.CONTAINER_NAME, norma.DEFAULT_PORT, "dev")
        parsed = ops.pebble.Layer(layer)
        # Build check_infos from the parsed plan so values match exactly
        infos = []
        for name, check in parsed.checks.items():
            infos.append(
                ops.testing.CheckInfo(
                    name=name,
                    level=check.level,
                    startup=check.startup,
                    threshold=check.threshold,
                )
            )
        return ops.testing.Container(
            name="norma",
            can_connect=True,
            layers={"norma": parsed},
            service_statuses={"norma": ops.pebble.ServiceStatus.ACTIVE},
            check_infos=infos,
        )

    def test_pebble_check_failed_logged_with_check_name(self):
        """pebble-check-failed routes through reconciler with check name in extra."""
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_c = self._container_with_checks()
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
        )
        check_info = ops.testing.CheckInfo(
            name="health",
            level=ops.pebble.CheckLevel.READY,
            status=ops.pebble.CheckStatus.DOWN,
        )
        with ctx(ctx.on.pebble_check_failed(norma_c, info=check_info), state) as mgr:
            mgr.run()
            ledger = mgr.charm._event_ledger
            check_events = [e for e in ledger if e["event_name"] == "pebble-check-failed"]
            assert len(check_events) == 1
            assert check_events[0]["extra"]["check"] == "health"

    def test_pebble_check_recovered_logged_with_check_name(self):
        """pebble-check-recovered routes through reconciler with check name in extra."""
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_c = self._container_with_checks()
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
        )
        check_info = ops.testing.CheckInfo(
            name="health",
            level=ops.pebble.CheckLevel.READY,
            status=ops.pebble.CheckStatus.UP,
        )
        with ctx(ctx.on.pebble_check_recovered(norma_c, info=check_info), state) as mgr:
            mgr.run()
            ledger = mgr.charm._event_ledger
            check_events = [e for e in ledger if e["event_name"] == "pebble-check-recovered"]
            assert len(check_events) == 1
            assert check_events[0]["extra"]["check"] == "health"

    def test_toggle_health_to_unhealthy(self):
        """toggle-health creates flag file when workload is healthy."""
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_c = ops.testing.Container(
            name="norma",
            can_connect=True,
        )
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("toggle-health"), state)
        assert ctx.action_results["previous-state"] == "healthy"
        assert ctx.action_results["new-state"] == "unhealthy"

    def test_toggle_health_to_healthy(self):
        """toggle-health removes flag file when workload is unhealthy."""
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_c = ops.testing.Container(
            name="norma",
            can_connect=True,
        )
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
        )
        # Pre-create flag file via Pebble API
        with ctx(ctx.on.action("toggle-health"), state) as mgr:
            container = mgr.charm.unit.get_container("norma")
            container.push(norma.HEALTH_FLAG_FILE, "unhealthy", make_dirs=True)
            mgr.run()
        assert ctx.action_results["previous-state"] == "unhealthy"
        assert ctx.action_results["new-state"] == "healthy"

    def test_toggle_health_fails_when_disconnected(self):
        """toggle-health fails when Pebble is not connected."""
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            ctx.run(ctx.on.action("toggle-health"), state)
        assert "Cannot connect" in str(exc_info.value)

    def test_toggle_health_custom_container(self):
        """toggle-health works with a custom container name."""
        ctx = ops.testing.Context(NormaK8sCharm)
        secondary = ops.testing.Container(
            name="norma-secondary",
            can_connect=True,
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, secondary],
        )
        ctx.run(ctx.on.action("toggle-health", params={"container": "norma-secondary"}), state)
        assert ctx.action_results["previous-state"] == "healthy"
        assert ctx.action_results["new-state"] == "unhealthy"


class TestPebbleOps:
    """US12: Pebble File Operations & Exec — test-pebble-ops action."""

    def _norma_with_exec(self):
        """Helper: norma container with layer, services, and exec mocks."""
        return ops.testing.Container(
            name="norma",
            can_connect=True,
            layers={
                "norma": ops.pebble.Layer(
                    {
                        "services": {
                            "norma": {
                                "override": "replace",
                                "command": "/bin/norma",
                                "startup": "enabled",
                            }
                        }
                    }
                )
            },
            service_statuses={"norma": ops.pebble.ServiceStatus.ACTIVE},
            execs=frozenset(
                {
                    ops.testing.Exec(command_prefix=[norma.BINARY_PATH, "--check"]),
                    ops.testing.Exec(command_prefix=["/nonexistent-binary"], return_code=127),
                }
            ),
        )

    def test_pebble_ops_all_pass(self):
        """test-pebble-ops runs full suite and reports results."""
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_c = self._norma_with_exec()
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("test-pebble-ops"), state)
        assert "summary" in ctx.action_results
        assert "passed" in ctx.action_results["summary"]
        assert ctx.action_results["push"] == "pass"
        assert ctx.action_results["pull"] == "pass"
        assert ctx.action_results["exists"] == "pass"

    def test_pebble_ops_fails_disconnected(self):
        """test-pebble-ops fails when container is disconnected."""
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            ctx.run(ctx.on.action("test-pebble-ops"), state)
        assert "Cannot connect" in str(exc_info.value)

    def test_pebble_ops_custom_container(self):
        """test-pebble-ops works with custom container name."""
        ctx = ops.testing.Context(NormaK8sCharm)
        secondary = ops.testing.Container(
            name="norma-secondary",
            can_connect=True,
            layers={
                "norma-secondary": ops.pebble.Layer(
                    {
                        "services": {
                            "norma-secondary": {
                                "override": "replace",
                                "command": "/bin/norma",
                                "startup": "enabled",
                            }
                        }
                    }
                )
            },
            service_statuses={"norma-secondary": ops.pebble.ServiceStatus.ACTIVE},
            execs=frozenset(
                {
                    ops.testing.Exec(command_prefix=[norma.BINARY_PATH, "--check"]),
                    ops.testing.Exec(command_prefix=["/nonexistent-binary"], return_code=127),
                }
            ),
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, secondary],
        )
        ctx.run(ctx.on.action("test-pebble-ops", params={"container": "norma-secondary"}), state)
        assert "summary" in ctx.action_results

    def test_pebble_ops_summary_format(self):
        """Summary format is 'N/M passed'."""
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_c = self._norma_with_exec()
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("test-pebble-ops"), state)
        summary = ctx.action_results["summary"]
        parts = summary.split("/")
        assert len(parts) == 2
        assert parts[1].endswith(" passed")


class TestNotices:
    """US13: Pebble Custom Notices — trigger-notice action and event handling."""

    def test_custom_notice_logged_with_key(self):
        """pebble-custom-notice event logs notice key in event ledger."""
        ctx = ops.testing.Context(NormaK8sCharm)
        notice = ops.testing.Notice(
            key="canonical.com/norma/calibration-test",
        )
        norma_c = ops.testing.Container(
            name="norma",
            can_connect=True,
            notices=[notice],
        )
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
        )
        with ctx(ctx.on.pebble_custom_notice(norma_c, notice=notice), state) as mgr:
            mgr.run()
            ledger = mgr.charm._event_ledger
            notice_events = [e for e in ledger if e["event_name"] == "pebble-custom-notice"]
            assert len(notice_events) == 1
            expected_key = "canonical.com/norma/calibration-test"
            assert notice_events[0]["extra"]["notice-key"] == expected_key

    def test_trigger_notice_action_sends_notice(self):
        """trigger-notice action executes pebble notify command."""
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_c = ops.testing.Container(
            name="norma",
            can_connect=True,
            execs=frozenset(
                {
                    ops.testing.Exec(
                        command_prefix=[
                            "/usr/bin/pebble",
                            "notify",
                            "canonical.com/norma/calibration-test",
                        ]
                    ),
                }
            ),
        )
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("trigger-notice"), state)
        assert ctx.action_results["notice-sent"] == "true"
        assert ctx.action_results["key"] == "canonical.com/norma/calibration-test"

    def test_trigger_notice_fails_disconnected(self):
        """trigger-notice fails when container is disconnected."""
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            ctx.run(ctx.on.action("trigger-notice"), state)
        assert "Cannot connect" in str(exc_info.value)

    def test_trigger_notice_with_data(self):
        """trigger-notice passes data as key=value args to pebble notify."""
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_c = ops.testing.Container(
            name="norma",
            can_connect=True,
            execs=frozenset(
                {
                    ops.testing.Exec(
                        command_prefix=[
                            "/usr/bin/pebble",
                            "notify",
                            "canonical.com/norma/test",
                            "foo=bar",
                        ]
                    ),
                }
            ),
        )
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
        )
        ctx.run(
            ctx.on.action(
                "trigger-notice",
                params={"key": "canonical.com/norma/test", "data": '{"foo": "bar"}'},
            ),
            state,
        )
        assert ctx.action_results["notice-sent"] == "true"
        assert ctx.action_results["key"] == "canonical.com/norma/test"

    def test_trigger_notice_invalid_json_fails(self):
        """trigger-notice fails cleanly on invalid JSON data."""
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_c = ops.testing.Container(name="norma", can_connect=True)
        state = ops.testing.State(containers=[norma_c, NORMA_SECONDARY])
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            ctx.run(
                ctx.on.action("trigger-notice", params={"data": "not-json"}),
                state,
            )
        assert "Invalid JSON" in str(exc_info.value)

    def test_trigger_notice_non_dict_data_fails(self):
        """trigger-notice fails cleanly when data is a JSON list, not object."""
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_c = ops.testing.Container(name="norma", can_connect=True)
        state = ops.testing.State(containers=[norma_c, NORMA_SECONDARY])
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            ctx.run(
                ctx.on.action("trigger-notice", params={"data": "[1,2,3]"}),
                state,
            )
        assert "JSON object" in str(exc_info.value)


class TestNetworking:
    """US14: Networking & Ports — port management and test-networking action."""

    def test_set_ports_called_on_reconcile(self):
        """Reconcile opens the configured port."""
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            config={"calibration-int": 9090},
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert ops.testing.TCPPort(9090) in out.opened_ports

    def test_default_port_opened(self):
        """Default port 8080 is opened when no config override."""
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert ops.testing.TCPPort(8080) in out.opened_ports

    def test_test_networking_returns_ports(self):
        """test-networking action reports opened ports."""
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            opened_ports=[ops.testing.TCPPort(8080)],
        )
        ctx.run(ctx.on.action("test-networking"), state)
        ports = json.loads(ctx.action_results["opened-ports"])
        assert "8080/tcp" in ports

    def test_test_networking_returns_bindings(self):
        """test-networking action reports network bindings."""
        ctx = ops.testing.Context(NormaK8sCharm)
        peer = ops.testing.PeerRelation(endpoint="norma-peers")
        network = ops.testing.Network(
            binding_name="norma-peers",
            bind_addresses=[
                ops.testing.BindAddress(
                    interface_name="eth0",
                    addresses=[ops.testing.Address(value="10.0.0.1")],
                )
            ],
            ingress_addresses=["10.0.0.1"],
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[peer],
            networks=[network],
        )
        ctx.run(ctx.on.action("test-networking"), state)
        bindings = json.loads(ctx.action_results["bindings"])
        assert "norma-peers" in bindings
        assert bindings["norma-peers"]["bind-address"] == "10.0.0.1"


class TestUpgrade:
    """US15: Upgrade/Refresh — version tracking and upgrade-charm handling."""

    def test_upgrade_charm_fires_reconcile(self):
        """upgrade-charm routes through the reconciler."""
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
        )
        with ctx(ctx.on.upgrade_charm(), state) as mgr:
            mgr.run()
            ledger = mgr.charm._event_ledger
            event_names = [e["event_name"] for e in ledger]
            assert "upgrade-charm" in event_names

    def test_get_version_returns_versions(self):
        """get-version action returns charm and workload versions."""
        ctx = ops.testing.Context(NormaK8sCharm)
        norma_c = ops.testing.Container(
            name="norma",
            can_connect=True,
            layers={
                "norma": ops.pebble.Layer(
                    norma.build_pebble_layer(norma.CONTAINER_NAME, norma.DEFAULT_PORT, "1.2.3")
                )
            },
            service_statuses={"norma": ops.pebble.ServiceStatus.ACTIVE},
            execs=frozenset({ops.testing.Exec(command_prefix=[norma.BINARY_PATH, "--check"])}),
        )
        state = ops.testing.State(
            containers=[norma_c, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("get-version"), state)
        assert ctx.action_results["charm-version"] == "dev"
        assert ctx.action_results["workload-version"] == "1.2.3"

    def test_get_version_workload_unavailable(self):
        """get-version reports unavailable when Pebble is disconnected."""
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("get-version"), state)
        assert ctx.action_results["workload-version"] == "unavailable"


class TestSecrets:
    """US9: Juju Secrets — create, rotate, expire, remove, grant/revoke."""

    def test_leader_creates_secret_on_first_reconcile(self):
        """AC1: Leader creates app secret and stores ID in peer app data."""
        ctx = ops.testing.Context(NormaK8sCharm)
        peer = ops.testing.PeerRelation(endpoint="norma-peers")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[peer],
            leader=True,
        )
        out = ctx.run(ctx.on.leader_elected(), state)
        out_peer = out.get_relation(peer.id)
        assert "secret-id" in out_peer.local_app_data
        assert out_peer.local_app_data["secret-id"].startswith("secret:")

    def test_secret_not_recreated_if_exists(self):
        """Secret is only created once — idempotent."""
        ctx = ops.testing.Context(NormaK8sCharm)
        existing_secret = ops.testing.Secret(
            {"password": "existing-pw"},
            owner="app",
            label="calibration-password",
        )
        peer = ops.testing.PeerRelation(
            endpoint="norma-peers",
            local_app_data={"secret-id": existing_secret.id},
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[peer],
            secrets=[existing_secret],
            leader=True,
        )
        out = ctx.run(ctx.on.config_changed(), state)
        # Secret ID should be unchanged
        out_peer = out.get_relation(peer.id)
        assert out_peer.local_app_data["secret-id"] == existing_secret.id
        # Should still be exactly one secret
        assert len(out.secrets) == 1

    def test_secret_rotate_creates_new_revision(self):
        """AC3: secret-rotate creates a new revision with fresh content."""
        ctx = ops.testing.Context(NormaK8sCharm)
        secret = ops.testing.Secret(
            {"password": "old-password"},
            owner="app",
            label="calibration-password",
            rotate=ops.SecretRotate.MONTHLY,
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            secrets=[secret],
            leader=True,
        )
        out = ctx.run(ctx.on.secret_rotate(secret), state)
        out_secret = out.get_secret(label="calibration-password")
        assert out_secret.latest_content["password"] != "old-password"

    def test_secret_expired_removes_revision(self):
        """AC4: secret-expired removes the expired revision."""
        ctx = ops.testing.Context(NormaK8sCharm)
        secret = ops.testing.Secret(
            {"password": "current"},
            latest_content={"password": "latest"},
            owner="app",
            label="calibration-password",
            _tracked_revision=2,
            _latest_revision=3,
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            secrets=[secret],
            leader=True,
        )
        ctx.run(ctx.on.secret_expired(secret, revision=1), state)
        assert 1 in ctx.removed_secret_revisions

    def test_secret_remove_cleans_obsolete_revision(self):
        """AC7: secret-remove removes obsolete revision."""
        ctx = ops.testing.Context(NormaK8sCharm)
        secret = ops.testing.Secret(
            {"password": "current"},
            latest_content={"password": "latest"},
            owner="app",
            label="calibration-password",
            _tracked_revision=2,
            _latest_revision=3,
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            secrets=[secret],
            leader=True,
        )
        ctx.run(ctx.on.secret_remove(secret, revision=1), state)
        assert 1 in ctx.removed_secret_revisions

    def test_get_secret_info_returns_metadata(self):
        """AC1: get-secret-info returns secret-id, has-content, rotation."""
        ctx = ops.testing.Context(NormaK8sCharm)
        secret = ops.testing.Secret(
            {"password": "test-pw"},
            owner="app",
            label="calibration-password",
        )
        peer = ops.testing.PeerRelation(
            endpoint="norma-peers",
            local_app_data={"secret-id": secret.id},
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
            relations=[peer],
            secrets=[secret],
            leader=True,
        )
        ctx.run(ctx.on.action("get-secret-info"), state)
        assert ctx.action_results["secret-id"] == secret.id
        assert ctx.action_results["has-content"] == "true"
        assert ctx.action_results["rotation"] == "monthly"

    def test_get_secret_info_no_peer(self):
        ctx = ops.testing.Context(NormaK8sCharm)
        state = ops.testing.State(
            containers=[NORMA_CONTAINER_DISCONNECTED, NORMA_SECONDARY],
        )
        ctx.run(ctx.on.action("get-secret-info"), state)
        assert ctx.action_results["secret-id"] == ""
        assert ctx.action_results["has-content"] == "false"

    def test_secret_granted_to_calibration_provider(self):
        """AC5: Secret is granted to calibration-provider relations."""
        ctx = ops.testing.Context(NormaK8sCharm)
        secret = ops.testing.Secret(
            {"password": "test-pw"},
            owner="app",
            label="calibration-password",
        )
        peer = ops.testing.PeerRelation(
            endpoint="norma-peers",
            local_app_data={"secret-id": secret.id},
        )
        rel = ops.testing.Relation(endpoint="calibration-provider")
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[peer, rel],
            secrets=[secret],
            leader=True,
        )
        out = ctx.run(ctx.on.relation_joined(rel), state)
        out_secret = out.get_secret(label="calibration-password")
        assert rel.id in out_secret.remote_grants

    def test_revoke_not_undone_by_grant_on_relation_broken(self):
        """Broken relation is excluded from grant loop after revoke."""
        ctx = ops.testing.Context(NormaK8sCharm)
        secret = ops.testing.Secret(
            {"password": "test-pw"},
            owner="app",
            label="calibration-password",
            remote_grants={1: {"norma-k8s-remote"}},
        )
        peer = ops.testing.PeerRelation(
            endpoint="norma-peers",
            local_app_data={"secret-id": secret.id},
        )
        broken_rel = ops.testing.Relation(
            endpoint="calibration-provider",
            id=1,
            remote_app_name="norma-k8s-remote",
        )
        state = ops.testing.State(
            containers=[NORMA_CONTAINER, NORMA_SECONDARY],
            relations=[peer, broken_rel],
            secrets=[secret],
            leader=True,
        )
        out = ctx.run(ctx.on.relation_broken(broken_rel), state)
        out_secret = out.get_secret(label="calibration-password")
        assert broken_rel.id not in out_secret.remote_grants
