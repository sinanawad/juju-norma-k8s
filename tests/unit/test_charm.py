# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the norma-k8s charm using ops.testing (Scenario).

Each test fires exactly one event against an immutable input State and
asserts on the output State, per Constitution Principle VI.
"""

import json

import ops
import ops.testing

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
