"""Integration tests for US8: Scaling (add/remove units) + leadership."""

import contextlib
import json
import time

import jubilant
import pytest

from .conftest import kubectl

APP = "juju-norma-k8s"


def _wait_peer_convergence(juju: jubilant.Juju, expected: int, timeout: int = 180) -> dict:
    """Poll get-cluster-info until peer membership reaches ``expected`` units.

    ``unit-count`` is ``1 (self) + len(peer.units)`` (src/charm.py:806-808), i.e.
    **peer-relation membership**, which lags unit *activity*: a unit reaches
    ``active`` before the leader has necessarily observed its relation-joined.
    Asserting immediately after ``wait(all active)`` therefore races, and did —
    ``unit-count`` came back "2" instead of "3" on three separate nightlies
    (2026-08-18 on 4.0/stable, 2026-08-29 and 2026-09-02 on 4.0/edge).

    Polling keeps the assertion strong — convergence is still required, and a
    genuine failure to converge still fails — while making the lag an observed
    property rather than an assumed-instant one. The scale-down sibling already
    documented this lag; the scale-up path had not accounted for it.

    Returns the converged action results, so callers can assert on them.
    """
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        task = juju.run(f"{APP}/leader", "get-cluster-info")
        assert task.success
        last = task.results["unit-count"]
        if last == str(expected):
            return task.results
        time.sleep(5)
    raise AssertionError(
        f"peer membership did not converge to {expected} units within {timeout}s "
        f"(last unit-count={last!r}) — the leader never observed all peers joining"
    )


class TestScaling:
    """US8: Scale up and down, verify cluster info."""

    def test_scale_to_three(self, juju: jubilant.Juju):
        juju.add_unit(APP, num_units=2)

        def three_units_active(status: jubilant.Status) -> bool:
            app = status.apps.get(APP)
            if app is None or len(app.units) < 3:
                return False
            return all(u.is_active for u in app.units.values())

        juju.wait(three_units_active, timeout=300)
        status = juju.status()
        assert len(status.apps[APP].units) == 3

    def test_cluster_info_reflects_scale(self, juju: jubilant.Juju):
        results = _wait_peer_convergence(juju, 3)
        assert results["unit-count"] == "3"

    def test_peer_data_all_units(self, juju: jubilant.Juju):
        # Same peer-membership lag as above. Converge explicitly rather than
        # relying on the preceding test having already waited it out — that made
        # this test's correctness depend on class execution order.
        _wait_peer_convergence(juju, 3)
        task = juju.run(f"{APP}/leader", "get-peer-data")
        unit_data = json.loads(task.results["unit-data"])
        assert len(unit_data) == 3, "All 3 units should have peer data"

    def test_scale_back_to_one(self, juju: jubilant.Juju):
        juju.remove_unit(APP, num_units=2)
        # Wait for exactly 1 unit — Juju 3.6 unit removal propagates slower.
        juju.wait(
            lambda s: len(s.apps[APP].units) == 1,
            timeout=300,
        )
        status = juju.status()
        assert len(status.apps[APP].units) == 1

    def test_cluster_info_after_scale_down(self, juju: jubilant.Juju):
        # Ensure scale-down completed and charm has reconciled.
        juju.wait(
            lambda s: len(s.apps[APP].units) == 1,
            timeout=120,
        )
        juju.wait(jubilant.all_active, timeout=120)
        task = juju.run(f"{APP}/leader", "get-cluster-info")
        # planned-units reflects the Juju-side scale target;
        # unit-count is based on peer relation membership which may lag.
        assert task.results["planned-units"] == "1"


class TestLeaderAndPodRecreation:
    """P2-3: K8s leadership + pod-recreation identity.

    Live-verified (4.0.12 K8s): `juju remove-unit <named>` is rejected (K8s
    scales by count only), so removing the leader — and thus machine-style
    leader re-election — cannot be exercised on K8s. Deleting the leader's pod
    recreates the SAME unit (statefulset identity persists) and leadership is
    retained (no spurious re-election within the recreation window).
    """

    def test_remove_named_unit_rejected_on_k8s(self, juju: jubilant.Juju):
        """K8s rejects removing a NAMED unit — a machine-only operation. This is
        why leader re-election via leader removal is not a K8s scenario."""
        with pytest.raises(jubilant.CLIError) as exc:
            juju.cli("remove-unit", f"{APP}/0")
        assert "named units" in str(exc.value).lower(), exc.value

    def test_leader_pod_recreation_preserves_identity_and_leadership(
        self, juju: jubilant.Juju, charm_path, oci_image
    ):
        """Deleting a unit's pod recreates the SAME unit (statefulset identity
        persists) and it stays the leader — the K8s analogue of leader resilience
        and a check that the charm holds no StoredState.

        Runs on a SEPARATE app: the pod recreation resets the charm's in-memory
        event ledger, so doing it on the shared deployment would wipe deploy-only
        events (e.g. storage-attached) that later tests assert on.
        """
        probe = kubectl("version", "--client")
        if probe is None or probe.returncode != 0:
            pytest.skip("kubectl (microk8s) unavailable")
        app = "norma-recreate"
        ns = juju.model.split(":")[-1]
        try:
            juju.cli(
                "deploy",
                str(charm_path),
                app,
                "--resource",
                f"juju-norma-image={oci_image}",
            )
            juju.wait(lambda s: app in s.apps and s.apps[app].is_active, timeout=300)

            pod = f"{app}-0"
            uid = kubectl("get", "pod", pod, "-n", ns, "-o", "jsonpath={.metadata.uid}")
            before = uid.stdout.strip() if uid else ""

            kubectl("delete", "pod", pod, "-n", ns, "--wait=false")

            # Wait until the statefulset recreates the pod (new UID) + unit active.
            recreated = False
            for _ in range(60):  # ~5 min
                r = kubectl("get", "pod", pod, "-n", ns, "-o", "jsonpath={.metadata.uid}")
                now = r.stdout.strip() if r else ""
                a = juju.status().apps.get(app)
                unit = a.units.get(f"{app}/0") if a else None
                if now and now != before and unit is not None and unit.is_active:
                    recreated = True
                    break
                time.sleep(5)
            assert recreated, f"pod {pod} was not recreated / unit not active"

            # Identity persists: same unit, active, and still the leader.
            units = juju.status().apps[app].units
            assert f"{app}/0" in units and units[f"{app}/0"].is_active
            leaders = [u for u, v in units.items() if getattr(v, "leader", False)]
            assert leaders == [f"{app}/0"], f"unexpected leadership after recreation: {leaders}"
            # Peer data still readable — the charm reconciled with no StoredState.
            assert juju.run(f"{app}/leader", "get-peer-data").success
        finally:
            with contextlib.suppress(jubilant.CLIError):
                juju.cli("remove-application", app, "--force", "--no-wait", "--no-prompt")
            with contextlib.suppress(jubilant.CLIError, TimeoutError):
                juju.wait(lambda s: app not in s.apps, timeout=180)
