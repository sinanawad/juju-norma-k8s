"""Integration tests for US11: Pebble Health Checks."""

import json
import time

import jubilant

APP = "juju-norma-k8s"


class TestHealthChecks:
    """US11: Toggle health and observe check-failed/recovered."""

    def test_toggle_health_to_unhealthy(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "toggle-health")
        assert task.success
        assert task.results["new-state"] == "unhealthy"

    def test_check_failed_event_after_toggle(self, juju: jubilant.Juju):
        """Wait for Pebble check to detect unhealthy state."""
        # Health check period is 10s with threshold 3, so wait ~40s
        time.sleep(40)
        task = juju.run(
            f"{APP}/leader",
            "get-event-log",
            params={"event-filter": "pebble-check-failed"},
        )
        events = json.loads(task.results["events"])
        assert len(events) >= 1, "pebble-check-failed should fire after health toggle"

    def test_toggle_health_back_to_healthy(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "toggle-health")
        assert task.success
        assert task.results["new-state"] == "healthy"

    def test_check_recovered_event(self, juju: jubilant.Juju):
        """Wait for Pebble to detect recovery."""
        time.sleep(15)
        task = juju.run(
            f"{APP}/leader",
            "get-event-log",
            params={"event-filter": "pebble-check-recovered"},
        )
        events = json.loads(task.results["events"])
        assert len(events) >= 1, "pebble-check-recovered should fire after health restore"
        # Ensure charm returns to active
        juju.wait(jubilant.all_active, timeout=60)
