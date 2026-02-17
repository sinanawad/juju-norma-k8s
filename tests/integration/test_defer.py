"""Integration tests for US20: Event Deferral."""

import json

import jubilant

APP = "juju-norma-k8s"


class TestDeferral:
    """US20: Arm deferral, trigger event, verify re-emission."""

    def test_arm_deferral(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "test-defer", params={"arm": True})
        assert task.success
        assert task.results["deferral-armed"] == "true"

    def test_deferred_event_logged(self, juju: jubilant.Juju):
        """Trigger config-changed while deferral is armed."""
        # Arm deferral
        juju.run(f"{APP}/leader", "test-defer", params={"arm": True})

        # Trigger a config-changed to be deferred
        juju.config(APP, {"calibration-string": "defer-test"})
        juju.wait(jubilant.all_active, timeout=60)

        # Check event ledger for deferred event (extra.deferred == "true")
        task = juju.run(f"{APP}/leader", "get-event-log")
        events = json.loads(task.results["events"])
        deferred = [e for e in events if e.get("extra", {}).get("deferred") == "true"]
        assert len(deferred) >= 1, "At least one deferred event should appear in ledger"

        # Cleanup
        juju.config(APP, reset=["calibration-string"])
        juju.wait(jubilant.all_active, timeout=60)

    def test_disarm_deferral(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "test-defer", params={"arm": False})
        assert task.success
        assert task.results["deferral-armed"] == "false"
