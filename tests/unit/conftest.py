"""Unit test fixtures."""

import pytest

import norma


@pytest.fixture(autouse=True)
def _no_host_side_effects(tmp_path, monkeypatch):
    """Keep every on-disk charm file in a per-test tmp dir.

    The charm reads and writes its ledger, deferral flag and pending re-emission
    marker under /tmp; left on the real host they leak between tests (results then
    depend on test order) and between runs.
    """
    monkeypatch.setattr(norma, "LEDGER_FILE", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(norma, "DEFER_FLAG_FILE", str(tmp_path / "defer"))
    monkeypatch.setattr(norma, "PENDING_REEMIT_FILE", str(tmp_path / "pending-reemit"))
