"""Integration tests for US6: Peer Relations and US7: Provides/Requires Relations."""

import json

import jubilant
import pytest

APP = "juju-norma-k8s"
PEER_APP = "juju-norma-k8s-peer"


class TestPeerRelation:
    """US6: Peer relation data exchange."""

    @pytest.mark.smoke
    def test_get_peer_data_returns_structure(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-peer-data")
        assert task.success
        assert "app-data" in task.results
        assert "unit-data" in task.results

    def test_leader_app_data_populated(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-peer-data")
        app_data = json.loads(task.results["app-data"])
        assert "leader-unit" in app_data, "Leader unit should be written to app data"

    def test_unit_data_has_entries(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-peer-data")
        unit_data = json.loads(task.results["unit-data"])
        # At least one unit should have data
        assert len(unit_data) >= 1


class TestProvidesRequiresRelation:
    """US7: Two-instance relation via calibration interface.

    Deploy a second app, integrate, verify relation data + events,
    remove the relation, verify relation-broken, then clean up.
    This is a single test because the steps are sequential and
    order-dependent — splitting them would create hidden coupling.
    """

    def test_relation_lifecycle(self, juju: jubilant.Juju, charm_path, oci_image):
        # --- Deploy second instance ---
        status = juju.status()
        if PEER_APP not in status.apps:
            juju.deploy(
                str(charm_path),
                app=PEER_APP,
                resources={"juju-norma-image": oci_image},
            )
            juju.wait(jubilant.all_active, timeout=300)

        try:
            # --- Integrate ---
            juju.integrate(
                f"{APP}:calibration-provider",
                f"{PEER_APP}:calibration-requirer",
            )
            juju.wait(jubilant.all_active, timeout=60)

            # --- Verify provider has relation data ---
            task = juju.run(
                f"{APP}/leader",
                "get-relation-data",
                params={"endpoint": "calibration-provider"},
            )
            assert task.success
            relations = json.loads(task.results["relations"])
            assert len(relations) >= 1, "Provider should have at least one relation"

            # --- Verify relation event logged ---
            task = juju.run(
                f"{APP}/leader",
                "get-event-log",
                params={"event-filter": "relation"},
            )
            events = json.loads(task.results["events"])
            event_names = [e["event_name"] for e in events]
            assert any("relation-created" in n for n in event_names)

            # --- Remove relation ---
            try:
                juju.remove_relation(
                    f"{APP}:calibration-provider",
                    f"{PEER_APP}:calibration-requirer",
                )
                juju.wait(jubilant.all_active, timeout=60)
            except jubilant.CLIError:
                pass  # Relation may already be removed

            # --- Verify relation-broken logged ---
            task = juju.run(
                f"{APP}/leader",
                "get-event-log",
                params={"event-filter": "relation-broken"},
            )
            events = json.loads(task.results["events"])
            assert len(events) >= 1, "relation-broken should be in ledger"

        finally:
            # --- Cleanup: remove the peer app ---
            status = juju.status()
            if PEER_APP in status.apps:
                juju.cli("remove-application", PEER_APP, "--no-prompt")
                juju.wait(
                    lambda s: PEER_APP not in s.apps,
                    timeout=120,
                )
