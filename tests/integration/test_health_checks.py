"""Integration tests for US11: Pebble Health Checks."""

import json
import time

import jubilant
import pytest

from .conftest import kubectl

APP = "juju-norma-k8s"


def _scrape_norma_healthy(juju: jubilant.Juju) -> str:
    """Read `norma_healthy` from the workload's own /metrics, live.

    Scrapes from inside the norma container (the ROCK vendors busybox, so
    `busybox wget` is available in an otherwise chiselled image) rather than
    trusting the charm's view — this asserts exactly the series Prometheus
    consumes, and therefore what the shipped `norma_healthy == 0` alert fires on.
    """
    probe = kubectl("version", "--client")
    if probe is None or probe.returncode != 0:
        pytest.skip("kubectl (microk8s) unavailable")

    # jubilant's typed accessor, not `juju config --format=json`: for an
    # APPLICATION that returns the bare scalar, not the {"value": ...} envelope
    # `juju model-config` returns — a difference that cost this test a full
    # matrix run.
    port = juju.config(APP).get("calibration-int", 8080)
    ns = juju.model.split(":")[-1]
    out = kubectl(
        "exec",
        f"{APP}-0",
        "-n",
        ns,
        "-c",
        "norma",
        "--",
        "/usr/bin/busybox",
        "wget",
        "-qO-",
        f"localhost:{port}/metrics",
    )
    assert out is not None and out.returncode == 0, f"scrape failed: {out and out.stderr}"
    for line in out.stdout.splitlines():
        if line.startswith("norma_healthy "):
            return line.split()[1]
    raise AssertionError(f"norma_healthy absent from /metrics:\n{out.stdout}")


class TestHealthChecks:
    """US11: Toggle health and observe check-failed/recovered.

    Order-dependent by design: the toggle tests below drive a shared deployment
    from healthy -> unhealthy -> healthy, and the assertions in between observe
    that transition.
    """

    def test_toggle_health_to_unhealthy(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "toggle-health")
        assert task.success
        assert task.results["new-state"] == "unhealthy"

    def test_metrics_report_unhealthy(self, juju: jubilant.Juju):
        """The charm's toggle-health must move `norma_healthy` to 0.

        Regression test for a shipped alert that could never fire: the charm
        toggles health by writing the flag file directly over Pebble, but the
        gauge was only ever Set() from main() and the workload's own HTTP toggle
        handler — so on the charm's path (the only one operators and these tests
        use) it never moved, and `norma_healthy == 0` was unreachable.
        """
        assert _scrape_norma_healthy(juju) == "0", (
            "norma_healthy did not follow the charm's toggle-health — the shipped "
            "alert `norma_healthy == 0` cannot fire"
        )

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

    def test_metrics_report_healthy_again(self, juju: jubilant.Juju):
        """Health must be RESTORABLE, not just droppable.

        The workload used to AND the flag file with an in-memory bool that the
        HTTP toggle flipped in the opposite direction; once those desynchronised
        (a pod restart with the flag file present, or mixing the charm and HTTP
        toggle paths) it was wedged unhealthy forever. This asserts recovery is
        observable in the metric an operator would alert on.
        """
        assert _scrape_norma_healthy(juju) == "1", (
            "norma_healthy did not return to 1 after toggling back — health is not "
            "restorable through the charm's action"
        )

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
