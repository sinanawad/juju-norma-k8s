"""Integration tests for US8: Scaling (add/remove units)."""

import json

import jubilant

APP = "juju-norma-k8s"


class TestScaling:
    """US8: Scale up and down, verify cluster info."""

    def test_scale_to_three(self, juju: jubilant.Juju):
        juju.add_unit(APP, num_units=2)
        juju.wait(jubilant.all_active, timeout=300)
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
        juju.wait(jubilant.all_active, timeout=180)
        status = juju.status()
        assert len(status.apps[APP].units) == 1

    def test_cluster_info_after_scale_down(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-cluster-info")
        assert task.results["unit-count"] == "1"
