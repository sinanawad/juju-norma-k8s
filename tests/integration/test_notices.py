"""Integration tests for US13: Pebble Custom Notices.

Note: Juju 4.0.2 does not dispatch pebble-custom-notice events.
These tests verify the trigger-notice action works; the event dispatch
is a known Juju 4 WIP limitation to re-test later.
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
        assert task.results["key"] == "norma.dev/calibration-test"
        assert task.results["notice-sent"] == "true"

    def test_trigger_notice_with_data(self, juju: jubilant.Juju):
        task = juju.run(
            f"{APP}/leader",
            "trigger-notice",
            params={"data": '{"source": "integration-test"}'},
        )
        assert task.success

    @pytest.mark.xfail(reason="Juju 4.0.2 WIP: custom notices not dispatched")
    def test_notice_event_dispatched(self, juju: jubilant.Juju):
        """Verify pebble-custom-notice appears in event ledger."""
        task = juju.run(
            f"{APP}/leader",
            "get-event-log",
            params={"event-filter": "pebble-custom-notice"},
        )
        events = json.loads(task.results["events"])
        assert len(events) >= 1, "pebble-custom-notice should be dispatched"
