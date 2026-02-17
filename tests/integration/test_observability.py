"""Integration tests for US18: COS Observability Integration.

Note: Full COS integration testing requires a deployed COS stack.
These tests validate the charm initializes COS libraries without error.
"""

import jubilant

APP = "juju-norma-k8s"


class TestObservability:
    """US18: Metrics, dashboards, and log forwarding endpoints."""

    def test_charm_active_with_cos_libraries(self, juju: jubilant.Juju):
        """COS libraries (prometheus, grafana, loki) load without error."""
        status = juju.status()
        assert status.apps[APP].is_active

    def test_introspect_no_errors(self, juju: jubilant.Juju):
        """Introspect succeeds, confirming COS library init is stable."""
        task = juju.run(f"{APP}/leader", "introspect")
        assert task.success
