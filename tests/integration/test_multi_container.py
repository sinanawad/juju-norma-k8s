"""Integration tests for US16: Multi-Container (primary + secondary)."""

import json

import jubilant
import pytest

APP = "juju-norma-k8s"


class TestMultiContainer:
    """US16: Both containers running independently."""

    def test_introspect_shows_both_containers(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "introspect", params={"sections": "containers"})
        assert task.success
        containers = json.loads(task.results["containers"])
        assert "norma" in containers
        assert "norma-secondary" in containers
        assert containers["norma"]["connected"] is True
        assert containers["norma-secondary"]["connected"] is True

    def test_pebble_ops_primary(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "test-pebble-ops", params={"container": "norma"})
        assert task.success
        assert task.results["push"] == "pass"

    @pytest.mark.xfail(
        reason="Juju 3.6: secondary container push gets permission denied",
        strict=False,
    )
    def test_pebble_ops_secondary(self, juju: jubilant.Juju):
        task = juju.run(
            f"{APP}/leader",
            "test-pebble-ops",
            params={"container": "norma-secondary"},
        )
        assert task.success
        assert task.results["push"] == "pass"
