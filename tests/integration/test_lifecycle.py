"""Integration tests for US1: Lifecycle Event Handling and US2: Pebble Workload."""

import json

import jubilant
import pytest

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


class TestForceRemove:
    """FR-029: Force remove application cleans up model."""

    @pytest.fixture(autouse=True)
    def _require_destructive(self, request):
        if not request.config.getoption("--run-destructive"):
            pytest.skip("Destructive test — pass --run-destructive to run")

    def test_force_remove_application(self, juju: jubilant.Juju, charm_path, oci_image):
        """Force-removing the app returns the model to a clean state.

        This test deploys a second instance, force-removes it, and verifies
        the model is clean. It does NOT touch the main test deployment.
        """
        alt_app = "norma-force-test"
        juju.deploy(
            str(charm_path),
            app=alt_app,
            resources={"juju-norma-image": oci_image},
        )
        juju.wait(lambda s: alt_app in s.apps and s.apps[alt_app].is_active, timeout=300)

        juju.cli("remove-application", alt_app, "--force", "--no-wait", "--no-prompt")
        juju.wait(lambda s: alt_app not in s.apps, timeout=120)


class TestJujuExecShell:
    """FR-038: Busybox shell in ROCK enables juju exec with shell."""

    def test_juju_exec_shell(self, juju: jubilant.Juju):
        """juju exec runs /bin/sh -c inside the workload container."""
        result = juju.cli(
            "exec",
            "--unit",
            f"{APP}/leader",
            "--",
            "/bin/sh",
            "-c",
            "echo hello-norma",
        )
        assert "hello-norma" in result
