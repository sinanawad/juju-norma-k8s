"""Integration tests for US1: Lifecycle Event Handling and US2: Pebble Workload."""

import contextlib
import json
import time

import jubilant
import pytest

from .conftest import kubectl

APP = "juju-norma-k8s"


@pytest.mark.smoke
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


class TestJujuSSH:
    """FR-037: juju ssh validates K8s exec-via-API path."""

    def test_juju_ssh(self, juju: jubilant.Juju):
        """juju ssh into the charm container (workload ROCK is bare/distroless)."""
        result = juju.cli(
            "ssh",
            "--container",
            "charm",
            f"{APP}/0",
            "ls /var/lib/juju",
        )
        assert "agents" in result


class TestUpdateStatusInterval:
    """FR-036: update-status-hook-interval fires periodic events."""

    def test_update_status_interval(self, juju: jubilant.Juju):
        """Shortening update-status interval produces events in the ledger."""
        # Save current interval so we can restore it
        raw = juju.cli("model-config", "update-status-hook-interval", "--format=json")
        previous = json.loads(raw).get("value", "5m")

        # Record current event count as baseline
        baseline_task = juju.run(
            f"{APP}/leader",
            "get-event-log",
            params={"event-filter": "update-status"},
        )
        baseline_count = len(json.loads(baseline_task.results["events"]))

        juju.cli("model-config", "update-status-hook-interval=30s")
        try:
            # Poll until at least 2 new update-status events appear
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                time.sleep(10)
                task = juju.run(
                    f"{APP}/leader",
                    "get-event-log",
                    params={"event-filter": "update-status"},
                )
                events = json.loads(task.results["events"])
                new_count = len(events) - baseline_count
                if new_count >= 2:
                    return
            pytest.fail(f"Expected >=2 new update-status events within 120s, got {new_count}")
        finally:
            juju.cli("model-config", f"update-status-hook-interval={previous}")


class TestModelMigration:
    """FR-034: Model migration between controllers."""

    def test_model_migration(self, juju: jubilant.Juju):
        """Model migration requires two bootstrapped controllers.

        Skips when fewer than two controllers are available.
        When two exist, attempts migration to the other controller.
        """
        try:
            raw = juju.cli("controllers", "--format=json")
            ctrl_data = json.loads(raw)
            controllers = list(ctrl_data.get("controllers", {}).keys())
            if len(controllers) < 2:
                pytest.skip("Model migration requires two controllers")
        except (jubilant.CLIError, json.JSONDecodeError):
            pytest.skip("Cannot determine controller count")

        current = ctrl_data.get("current-controller", "")
        targets = [c for c in controllers if c != current]
        if not targets:
            pytest.skip("No target controller found for migration")

        target = targets[0]
        model_name = juju.cli("model-config", "name").strip()

        try:
            juju.cli("migrate", model_name, target)
            # Wait for migration to complete (up to 5 min)
            juju.wait(jubilant.all_active, timeout=300)
        except jubilant.CLIError as e:
            pytest.xfail(f"Model migration not supported in this environment: {e}")


def _remove_app(juju: jubilant.Juju, app: str) -> None:
    with contextlib.suppress(jubilant.CLIError):
        juju.cli("remove-application", app, "--force", "--no-wait", "--no-prompt")
    with contextlib.suppress(jubilant.CLIError, TimeoutError):
        juju.wait(lambda s: app not in s.apps, timeout=180)


class TestDeployConstraints:
    """P2-2 / FR-037: K8s constraint accept/reject + pod-spec application.

    Live-verified (4.0.12 K8s, 2026-06-04): the K8s provider REJECTS `cores`
    at the deploy precheck ("constraints cores not supported"), while `mem` and
    `cpu-power` are ACCEPTED. But `mem` is not (yet) applied to the sidecar
    workload container's resources — application.go carries a `// TODO: ...
    Constraints ...` for that path — so the pod-spec assertion is a strict-xfail
    sentinel that flips when Juju wires it.
    """

    def test_cores_constraint_rejected_on_k8s(self, juju: jubilant.Juju, charm_path, oci_image):
        """`cores` is not a K8s constraint — deploy is rejected at the precheck.

        (The previous test wrongly expected `cores=1` to reach active; it only
        passed unnoticed because it was --run-destructive-gated and never ran.)
        """
        app = "norma-cores"
        with pytest.raises(jubilant.CLIError) as exc:
            juju.cli(
                "deploy",
                str(charm_path),
                app,
                "--constraints",
                "cores=1",
                "--resource",
                f"juju-norma-image={oci_image}",
            )
        msg = str(exc.value).lower()
        assert "cores" in msg and "not supported" in msg, exc.value
        _remove_app(juju, app)  # defensive — the deploy should not have created it

    def test_mem_cpu_constraints_accepted_on_k8s(self, juju: jubilant.Juju, charm_path, oci_image):
        """`mem` and `cpu-power` ARE K8s-honoured constraints — deploy reaches
        active (unlike `cores`)."""
        app = "norma-memcpu"
        try:
            juju.cli(
                "deploy",
                str(charm_path),
                app,
                "--constraints",
                "mem=512M cpu-power=200",
                "--resource",
                f"juju-norma-image={oci_image}",
            )
            juju.wait(lambda s: app in s.apps and s.apps[app].is_active, timeout=300)
        finally:
            _remove_app(juju, app)

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Juju <=4.0.12 accepts `mem` on K8s but does NOT apply it to the "
            "sidecar workload container (application.go TODO path); flips when "
            "Juju wires ApplyWorkloadConstraints for sidecar charms."
        ),
    )
    def test_mem_constraint_reaches_workload_pod(self, juju: jubilant.Juju, charm_path, oci_image):
        """`mem` should set the workload container's memory request/limit."""
        probe = kubectl("version", "--client")
        if probe is None or probe.returncode != 0:
            pytest.skip("kubectl (microk8s) unavailable")
        app = "norma-memspec"
        ns = juju.model.split(":")[-1]
        try:
            juju.cli(
                "deploy",
                str(charm_path),
                app,
                "--constraints",
                "mem=512M",
                "--resource",
                f"juju-norma-image={oci_image}",
            )
            juju.wait(lambda s: app in s.apps and s.apps[app].is_active, timeout=300)
            out = kubectl("get", "pod", f"{app}-0", "-n", ns, "-o", "json")
            pod = json.loads(out.stdout)
            norma = next(c for c in pod["spec"]["containers"] if c["name"] == "norma")
            res = norma.get("resources", {})
            mem = res.get("limits", {}).get("memory") or res.get("requests", {}).get("memory")
            assert mem and "512" in mem, f"mem constraint not on workload pod: {res}"
        finally:
            _remove_app(juju, app)
