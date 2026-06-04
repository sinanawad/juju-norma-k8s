"""Integration tests for US4: Status Reporting."""

import jubilant

APP = "juju-norma-k8s"


class TestStatusReporting:
    """US4: Status can be forced and recovers."""

    def test_active_with_no_message(self, juju: jubilant.Juju):
        status = juju.status()
        unit = next(iter(status.apps[APP].units.values()))
        assert unit.is_active
        assert unit.workload_status.message == ""

    def test_set_status_blocked(self, juju: jubilant.Juju):
        task = juju.run(
            f"{APP}/leader",
            "set-status",
            params={"status": "blocked", "message": "integration test block"},
        )
        assert task.success
        juju.wait(jubilant.any_blocked, timeout=30)
        status = juju.status()
        unit = next(iter(status.apps[APP].units.values()))
        assert unit.is_blocked
        assert "integration test block" in unit.workload_status.message
        # Clear by setting active
        juju.run(f"{APP}/leader", "set-status", params={"status": "active"})
        juju.wait(jubilant.all_active, timeout=60)

    def test_set_status_waiting(self, juju: jubilant.Juju):
        juju.run(
            f"{APP}/leader",
            "set-status",
            params={"status": "waiting", "message": "test wait"},
        )
        # 30s was too tight under CI load (intermittent flake): the forced
        # status still round-trips through a reconcile + status collection.
        juju.wait(jubilant.any_waiting, timeout=120)
        # Clear
        juju.run(f"{APP}/leader", "set-status", params={"status": "active"})
        juju.wait(jubilant.all_active, timeout=120)

    def test_set_status_maintenance(self, juju: jubilant.Juju):
        juju.run(
            f"{APP}/leader",
            "set-status",
            params={"status": "maintenance", "message": "test maint"},
        )
        juju.wait(jubilant.any_maintenance, timeout=30)
        # Clear
        juju.run(f"{APP}/leader", "set-status", params={"status": "active"})
        juju.wait(jubilant.all_active, timeout=60)
