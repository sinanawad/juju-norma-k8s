"""Integration tests for US3: Configuration and US5: Actions."""

import json

import jubilant
import pytest

APP = "juju-norma-k8s"


class TestConfiguration:
    """US3: Config options apply and are queryable."""

    def test_get_config_returns_defaults(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-config")
        assert task.success
        assert task.results["calibration-string"] == "default"
        assert task.results["calibration-int"] == "8080"
        assert task.results["calibration-bool"] == "True"

    @pytest.mark.smoke
    def test_set_string_config(self, juju: jubilant.Juju):
        juju.config(APP, {"calibration-string": "integration-test"})
        juju.wait(jubilant.all_active, timeout=60)
        task = juju.run(f"{APP}/leader", "get-config")
        assert task.results["calibration-string"] == "integration-test"
        # Reset
        juju.config(APP, reset=["calibration-string"])
        juju.wait(jubilant.all_active, timeout=60)

    def test_set_int_config(self, juju: jubilant.Juju):
        juju.config(APP, {"calibration-int": "9090"})
        juju.wait(jubilant.all_active, timeout=60)
        task = juju.run(f"{APP}/leader", "get-config")
        assert task.results["calibration-int"] == "9090"
        # Reset
        juju.config(APP, reset=["calibration-int"])
        juju.wait(jubilant.all_active, timeout=60)

    def test_invalid_config_blocked(self, juju: jubilant.Juju):
        juju.config(APP, {"calibration-int": "0"})
        juju.wait(jubilant.any_blocked, timeout=60)
        status = juju.status()
        unit = next(iter(status.apps[APP].units.values()))
        assert unit.is_blocked
        # Reset to restore active
        juju.config(APP, reset=["calibration-int"])
        juju.wait(jubilant.all_active, timeout=120)


class TestActions:
    """US5: Action execution and error reporting."""

    def test_fail_action(self, juju: jubilant.Juju):
        try:
            juju.run(f"{APP}/leader", "fail-action", params={"message": "test failure"})
            pytest.fail("fail-action should raise TaskError")
        except jubilant.TaskError as e:
            assert "test failure" in e.task.message

    def test_get_event_log_with_filter(self, juju: jubilant.Juju):
        task = juju.run(
            f"{APP}/leader", "get-event-log", params={"event-filter": "config-changed"}
        )
        assert task.success
        events = json.loads(task.results["events"])
        assert all("config-changed" in e["event_name"] for e in events)

    def test_get_event_log_with_limit(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-event-log", params={"limit": 3})
        assert task.success
        events = json.loads(task.results["events"])
        assert len(events) <= 3
