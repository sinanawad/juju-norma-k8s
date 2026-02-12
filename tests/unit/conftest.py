# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit test fixtures."""

import pathlib

import pytest

import norma


@pytest.fixture(autouse=True)
def _clean_event_ledger():
    """Remove the event ledger file before each test to prevent cross-test pollution."""
    ledger = pathlib.Path(norma.LEDGER_FILE)
    ledger.unlink(missing_ok=True)
    yield
    ledger.unlink(missing_ok=True)
