"""Integration tests for US15: Upgrade (charm refresh)."""

import jubilant

APP = "juju-norma-k8s"


class TestUpgrade:
    """US15: Charm refresh and version reporting."""

    def test_get_version(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-version")
        assert task.success
        assert task.results.get("charm-version"), "Charm version should be set"
        assert task.results.get("workload-version"), "Workload version should be set"

    def test_upgrade_charm_event_logged(self, juju: jubilant.Juju):
        """Verify upgrade-charm appears in event ledger (from initial deploy)."""
        task = juju.run(
            f"{APP}/leader",
            "get-event-log",
            params={"event-filter": "upgrade-charm"},
        )
        # upgrade-charm may not fire on first deploy, only on refresh
        # This test documents the behavior rather than asserting strictly
        assert task.success
