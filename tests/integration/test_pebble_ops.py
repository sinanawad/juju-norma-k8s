"""Integration tests for US12: Pebble File/Exec Operations."""

import jubilant

APP = "juju-norma-k8s"


class TestPebbleOps:
    """US12: Full Pebble operation suite."""

    def test_pebble_ops_all_pass(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "test-pebble-ops")
        assert task.success
        results = task.results
        assert results["push"] == "pass"
        assert results["pull"] == "pass"
        assert results["list-files"] == "pass"
        assert results["make-dir"] == "pass"
        assert results["remove-path"] == "pass"
        assert results["exec"] == "pass"

    def test_pebble_ops_summary(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "test-pebble-ops")
        assert "passed" in task.results["summary"]

    def test_pebble_ops_send_signal(self, juju: jubilant.Juju):
        """FR-028: send-signal operation passes in pebble-ops suite."""
        task = juju.run(f"{APP}/leader", "test-pebble-ops")
        assert task.success
        assert task.results.get("send-signal") == "pass"

    def test_pebble_ops_secondary_container(self, juju: jubilant.Juju):
        task = juju.run(
            f"{APP}/leader",
            "test-pebble-ops",
            params={"container": "norma-secondary"},
        )
        assert task.success
        assert task.results["push"] == "pass"
