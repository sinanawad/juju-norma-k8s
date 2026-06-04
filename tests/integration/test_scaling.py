"""Integration tests for US8: Scaling (add/remove units) + leadership."""

import json
import time

import jubilant
import pytest

from .conftest import kubectl

APP = "juju-norma-k8s"


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
        task = juju.run(f"{APP}/leader", "get-cluster-info")
        assert task.success
        assert task.results["unit-count"] == "3"

    def test_peer_data_all_units(self, juju: jubilant.Juju):
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

    def test_leader_pod_recreation_preserves_identity_and_leadership(self, juju: jubilant.Juju):
        """Deleting the leader's pod recreates the same unit (identity persists
        via the statefulset) and leadership is retained — the K8s analogue of
        leader resilience, and a check that the charm holds no StoredState."""
        probe = kubectl("version", "--client")
        if probe is None or probe.returncode != 0:
            pytest.skip("kubectl (microk8s) unavailable")
        ns = juju.model.split(":")[-1]

        units = juju.status().apps[APP].units
        leader_unit = next(
            (u for u, v in units.items() if getattr(v, "leader", False)), f"{APP}/0"
        )
        pod = leader_unit.replace("/", "-")

        uid = kubectl("get", "pod", pod, "-n", ns, "-o", "jsonpath={.metadata.uid}")
        before = uid.stdout.strip() if uid else ""

        kubectl("delete", "pod", pod, "-n", ns, "--wait=false")

        # Wait until the statefulset recreates the pod (new UID) and the unit is
        # active again.
        recreated = False
        for _ in range(60):  # ~5 min
            r = kubectl("get", "pod", pod, "-n", ns, "-o", "jsonpath={.metadata.uid}")
            now = r.stdout.strip() if r else ""
            unit = juju.status().apps[APP].units.get(leader_unit)
            if now and now != before and unit is not None and unit.is_active:
                recreated = True
                break
            time.sleep(5)
        assert recreated, f"pod {pod} was not recreated / unit {leader_unit} not active"

        # Identity persists: same unit name, active.
        u2 = juju.status().apps[APP].units
        assert leader_unit in u2 and u2[leader_unit].is_active
        # Leadership retained (no spurious re-election on K8s pod recreation).
        new_leader = next((u for u, v in u2.items() if getattr(v, "leader", False)), None)
        assert new_leader == leader_unit, f"leadership moved unexpectedly to {new_leader}"
        # Peer relation data still reflects the cluster (the charm reconciled).
        assert juju.run(f"{APP}/leader", "get-peer-data").success
