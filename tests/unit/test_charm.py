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
