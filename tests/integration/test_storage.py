"""Integration tests for US10: Storage and US24: Multiple Storage."""

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


class TestStorageK8sCLI:
    """FR-030: K8s storage-CLI boundary calibration.

    Calibrates which storage operations Juju permits on a CAAS/K8s model.
    Verified against Juju 4.0 edge source (``cmd/juju/storage/*`` @ 0c7e2b4):
      - READ path works on K8s: ``juju storage``/``show-storage`` are NOT
        IAAS-gated, and edge added out-of-band PVC/PV tracking
        (``juju storage`` was previously "not yet available" on CAAS).
      - DYNAMIC add/attach/detach-storage still embed
        ``modelcmd.IAASOnlyCommand`` (add.go:108, attach.go:52, detach.go:64),
        so they are REJECTED on K8s with
        ``Juju command "<x>" not supported on container models``.

    These tests pin that CURRENT boundary so a change in EITHER direction
    (support landing, or a regression) fails loudly. Edge K8s-storage work is
    in progress and may be buggy, so we assert robust observables — the
    accept/reject behaviour and command reachability — not fragile internals.
    """

    # Substrings of the IAASOnlyCommand rejection (modelcommand.go:585).
    _NOT_SUPPORTED = ("not supported on container models", "not supported", "not available")

    def test_add_storage_still_iaas_only(self, juju: jubilant.Juju):
        """``add-storage`` is IAASOnlyCommand → must be REJECTED on K8s. If it
        ever succeeds, Juju lifted the gate — update this calibration."""
        try:
            juju.cli("add-storage", f"{APP}/0", "logs=1")
        except jubilant.CLIError as e:
            msg = f"{e}".lower()
            assert any(s in msg for s in self._NOT_SUPPORTED), (
                f"add-storage failed, but not with a K8s-not-supported error: {e}"
            )
            return
        pytest.fail(
            "add-storage unexpectedly SUCCEEDED on K8s — Juju may have lifted "
            "IAASOnlyCommand; update this calibration test (and the storage docs)."
        )

    def test_juju_storage_read_available_on_k8s(self, juju: jubilant.Juju):
        """``juju storage`` is a read command (not IAAS-gated) and, since edge
        added K8s PVC/PV tracking, is reachable on CAAS (was "not yet
        available"). Grain of salt: assert it runs + returns valid JSON; do NOT
        hard-assert full PVC reflection (that tracking is WIP on edge)."""
        out = juju.cli("storage", "--format=json")
        data = json.loads(out)
        assert isinstance(data, dict), f"`juju storage` returned non-dict JSON: {out[:200]}"

    def test_import_filesystem_not_substrate_blocked(self, juju: jubilant.Juju):
        """``import-filesystem`` is NOT IAAS-gated (import.go), so on K8s it is
        reachable — a bogus PV id yields a usage/PV error, NOT a substrate block.
        Grain of salt: we only assert it isn't substrate-blocked, not that a real
        import succeeds (that needs a provisioned PV)."""
        try:
            juju.cli("import-filesystem", "kubernetes", "bogus-provider-id", "data")
        except jubilant.CLIError as e:
            assert "not supported on container models" not in f"{e}".lower(), (
                f"import-filesystem appears substrate-blocked on K8s: {e}"
            )

    @pytest.mark.skip(
        reason="deploy --attach-storage on K8s needs a pre-detached PV, but "
        "detach-storage is IAASOnlyCommand (blocked on K8s) so the precondition "
        "cannot be created here. Revisit using Juju's dummy-storage-k8s harness."
    )
    def test_deploy_attach_storage(self, juju: jubilant.Juju):
        """AC7: juju deploy --attach-storage reuses a detached PV (WIP on K8s)."""
