"""Integration tests for US1: Lifecycle Event Handling and US2: Pebble Workload."""

import json

import jubilant

APP = "juju-norma-k8s"


class TestLifecycle:
    """US1: Charm starts, reaches active, records lifecycle events."""

    def test_charm_is_active(self, juju: jubilant.Juju):
        status = juju.status()
        assert status.apps[APP].is_active

    def test_unit_is_active(self, juju: jubilant.Juju):
        status = juju.status()
        units = status.apps[APP].units
        assert len(units) >= 1
        for unit in units.values():
            assert unit.is_active

    def test_event_ledger_has_lifecycle_events(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-event-log")
        assert task.success
        events = json.loads(task.results["events"])
        event_names = [e["event_name"] for e in events]
        # Core lifecycle events must be present
        for expected in ("install", "leader-elected", "config-changed"):
            assert expected in event_names, f"Missing lifecycle event: {expected}"

    def test_event_ledger_ordering(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-event-log")
        events = json.loads(task.results["events"])
        event_names = [e["event_name"] for e in events]
        # install must come before config-changed
        if "install" in event_names and "config-changed" in event_names:
            assert event_names.index("install") < event_names.index("config-changed")


class TestPebbleWorkload:
    """US2: Pebble layer applied, workload running."""

    def test_run_check_pebble_pass(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "run-check", params={"check": "pebble"})
        assert task.success
        assert task.results["result"] == "pass"

    def test_workload_version_reported(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-version")
        assert task.success
        assert task.results.get("workload-version"), "Workload version should be set"

    def test_pebble_ready_in_event_log(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-event-log", params={"event-filter": "pebble-ready"})
        events = json.loads(task.results["events"])
        assert len(events) >= 1, "pebble-ready should appear in event ledger"
