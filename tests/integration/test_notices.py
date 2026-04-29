"""Integration tests for US13: Pebble Custom Notices.

Note: Neither Juju 3.6 nor 4.0 dispatch pebble-custom-notice events.
The Juju agent does not poll Pebble for custom notices yet.  The first
two tests verify the trigger-notice action works (notice is created in
Pebble); the third is an xfail canary for when dispatch is implemented.
"""

import json

import jubilant
import pytest

APP = "juju-norma-k8s"


class TestNotices:
    """US13: Custom notice trigger and (eventual) dispatch."""

    def test_trigger_notice_action(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "trigger-notice")
        assert task.success
        # Juju 3.6 Pebble may prefix keys with canonical.com/.
        assert task.results["key"].endswith("calibration-test")
        assert task.results["notice-sent"] == "true"

    def test_trigger_notice_with_data(self, juju: jubilant.Juju):
        task = juju.run(
            f"{APP}/leader",
            "trigger-notice",
            params={"data": '{"source": "integration-test"}'},
        )
        assert task.success

    @pytest.mark.xfail(
        reason="Juju agent does not dispatch pebble-custom-notice events (3.6 + 4.0)"
    )
    def test_notice_event_dispatched(self, juju: jubilant.Juju):
        """Verify pebble-custom-notice appears in event ledger."""
        task = juju.run(
            f"{APP}/leader",
            "get-event-log",
            params={"event-filter": "pebble-custom-notice"},
        )
        events = json.loads(task.results["events"])
        assert len(events) >= 1, "pebble-custom-notice should be dispatched"
