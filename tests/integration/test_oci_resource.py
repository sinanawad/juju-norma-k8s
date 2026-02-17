"""Integration tests for US21: OCI Resource Lifecycle."""

import jubilant

APP = "juju-norma-k8s"


class TestOCIResource:
    """US21: OCI image resource handling."""

    def test_workload_running_with_resource(self, juju: jubilant.Juju):
        """Verify workload is running from the OCI resource."""
        task = juju.run(f"{APP}/leader", "run-check", params={"check": "pebble"})
        assert task.success
        assert task.results["result"] == "pass"

    def test_version_from_workload(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-version")
        assert task.success
        assert task.results.get("workload-version")
