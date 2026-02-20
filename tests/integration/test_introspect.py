"""Integration tests for US22: Introspect Action."""

import json

import jubilant

APP = "juju-norma-k8s"


class TestIntrospect:
    """US22: Comprehensive structured introspection report."""

    def test_all_sections_returned(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "introspect")
        assert task.success
        results = task.results
        assert "timestamp" in results
        assert "unit" in results
        expected_sections = [
            "identity",
            "version",
            "leadership",
            "config",
            "event-ledger",
            "relations",
            "storage",
            "containers",
            "secrets",
        ]
        for section in expected_sections:
            assert section in results, f"Missing section: {section}"

    def test_section_filter(self, juju: jubilant.Juju):
        task = juju.run(
            f"{APP}/leader",
            "introspect",
            params={"sections": "config,identity"},
        )
        assert task.success
        assert "config" in task.results
        assert "identity" in task.results
        assert "storage" not in task.results

    def test_identity_section(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "introspect", params={"sections": "identity"})
        identity = json.loads(task.results["identity"])
        assert "unit-name" in identity
        assert "app-name" in identity
        assert identity["app-name"] == APP

    def test_config_section(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "introspect", params={"sections": "config"})
        config = json.loads(task.results["config"])
        assert "calibration-string" in config
        assert "calibration-int" in config

    def test_leadership_section(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "introspect", params={"sections": "leadership"})
        leadership = json.loads(task.results["leadership"])
        assert "is-leader" in leadership

    def test_event_ledger_section(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "introspect", params={"sections": "event-ledger"})
        ledger = json.loads(task.results["event-ledger"])
        assert "count" in ledger
        assert "events" in ledger
        assert ledger["count"] >= 1

    def test_goal_state_section(self, juju: jubilant.Juju):
        """FR-035: Introspect includes goal-state from hook tool."""
        task = juju.run(f"{APP}/leader", "introspect", params={"sections": "goal-state"})
        assert task.success
        goal_state = json.loads(task.results["goal-state"])
        # In a live deployment, goal-state returns units and relations
        if "status" not in goal_state:
            assert "units" in goal_state or "relations" in goal_state
        # If unavailable, verify graceful fallback
        else:
            assert goal_state["status"] in ("unavailable",)
