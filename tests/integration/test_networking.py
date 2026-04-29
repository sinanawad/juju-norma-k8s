"""Integration tests for US14: Networking (open ports, bindings, expose)."""

import contextlib
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

    def test_exposed_key_present(self, juju: jubilant.Juju):
        """FR-033: test-networking reports exposed status key."""
        task = juju.run(f"{APP}/leader", "test-networking")
        assert "exposed" in task.results


class TestExpose:
    """FR-033: Expose and unexpose application via CLI."""

    def _wait_exposed(self, juju: jubilant.Juju, expected: bool, timeout: int = 30):
        """Poll juju status until exposed matches expected value."""
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = juju.cli("status", "--format=json")
            status = json.loads(raw)
            if status["applications"][APP].get("exposed") is expected:
                return
            time.sleep(2)
        raise AssertionError(f"Timed out waiting for exposed={expected}")

    def test_expose_unexpose(self, juju: jubilant.Juju):
        """juju expose/unexpose toggles exposed flag in juju status."""
        try:
            # Juju 3.6 requires juju-external-hostname for K8s expose.
            juju.cli("config", APP, "juju-external-hostname=test.local")
            juju.cli("expose", APP)
            self._wait_exposed(juju, True)

            juju.cli("unexpose", APP)
            self._wait_exposed(juju, False)
        finally:
            with contextlib.suppress(jubilant.CLIError):
                juju.cli("unexpose", APP)
                juju.cli("config", APP, "--reset", "juju-external-hostname")
