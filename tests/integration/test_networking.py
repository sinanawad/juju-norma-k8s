"""Integration tests for US14: Networking (open ports, bindings)."""

import json

import jubilant

APP = "juju-norma-k8s"


class TestNetworking:
    """US14: Port management and network bindings."""

    def test_port_opened(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "test-networking")
        assert task.success
        ports = json.loads(task.results["opened-ports"])
        assert any("8080" in p for p in ports), "Port 8080 should be open"

    def test_bindings_reported(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "test-networking")
        bindings = json.loads(task.results["bindings"])
        assert len(bindings) >= 1, "At least one binding should exist"

    def test_unit_has_address(self, juju: jubilant.Juju):
        status = juju.status()
        unit = next(iter(status.apps[APP].units.values()))
        assert unit.address, "Unit should have an IP address"
