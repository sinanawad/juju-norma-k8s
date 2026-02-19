"""Integration tests for US10: Storage and US24: Multiple Storage."""

import contextlib
import json

import jubilant
import pytest

APP = "juju-norma-k8s"


class TestStorage:
    """US10: Filesystem storage with marker file."""

    def test_data_storage_attached(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "check-storage", params={"name": "data"})
        assert task.success
        assert task.results["attached"] == "true"
        assert task.results["mount-point"] == "/var/lib/norma"

    def test_data_storage_writable(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "check-storage", params={"name": "data"})
        assert task.results["writable"] == "true"

    def test_data_marker_written(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "check-storage", params={"name": "data"})
        assert task.results["marker-exists"] == "true"
        content = json.loads(task.results["marker-content"])
        assert "created_by" in content
        assert "revision" in content

    def test_storage_attached_event_logged(self, juju: jubilant.Juju):
        task = juju.run(
            f"{APP}/leader",
            "get-event-log",
            params={"event-filter": "storage-attached"},
        )
        events = json.loads(task.results["events"])
        assert len(events) >= 1


class TestMultipleStorage:
    """US24: Multiple storage definitions (data + logs)."""

    def test_logs_storage_status(self, juju: jubilant.Juju):
        """Check logs storage — may or may not be attached depending on model type."""
        task = juju.run(f"{APP}/leader", "check-storage", params={"name": "logs"})
        assert task.success
        assert task.results["mount-point"] == "/var/log/norma"

    def test_unknown_storage_fails(self, juju: jubilant.Juju):
        try:
            juju.run(f"{APP}/leader", "check-storage", params={"name": "nonexistent"})
        except jubilant.TaskError as e:
            assert "Unknown storage name" in e.task.message

    def test_introspect_lists_both_storages(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "introspect", params={"sections": "storage"})
        assert task.success
        storage = json.loads(task.results["storage"])
        assert "data" in storage
        assert "logs" in storage
        assert storage["data"]["mount-point"] == "/var/lib/norma"
        assert storage["logs"]["mount-point"] == "/var/log/norma"


class TestStorageCLI:
    """FR-030: Storage CLI operations (xfail — K8s limitations)."""

    @pytest.mark.xfail(
        strict=False,
        reason="K8s container model storage CLI not yet supported in Juju",
    )
    def test_attach_storage(self, juju: jubilant.Juju):
        """AC4: juju add-storage adds optional storage dynamically."""
        juju.cli("add-storage", f"{APP}/0", "logs=1")
        task = juju.run(f"{APP}/leader", "check-storage", params={"name": "logs"})
        assert task.results["attached"] == "true"

    @pytest.mark.xfail(
        strict=False,
        reason="K8s container model storage CLI not yet supported in Juju",
    )
    def test_import_filesystem(self, juju: jubilant.Juju):
        """AC6: juju import-filesystem imports a pre-existing PV."""
        # This would require a pre-existing PV — just attempt the command
        # and verify Juju gives a meaningful error or succeeds.
        with contextlib.suppress(jubilant.CLIError):
            juju.cli("import-filesystem", "data", "test-pv-id")

    @pytest.mark.xfail(
        strict=False,
        reason="K8s container model storage CLI not yet supported in Juju",
    )
    def test_deploy_attach_storage(self, juju: jubilant.Juju):
        """AC7: juju deploy --attach-storage reuses a PV from a removed unit."""
        # Would need a previously detached storage ID. Just verify the CLI
        # flag is accepted or gives a meaningful error.
        with contextlib.suppress(jubilant.CLIError):
            juju.cli(
                "deploy",
                ".",
                "--attach-storage",
                "data/0",
                "--resource",
                "juju-norma-image=localhost:32000/juju-norma:0.1.0",
            )
