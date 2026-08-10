"""Integration tests for US13: Pebble Custom Notices.

Juju dispatches the ``pebble-custom-notice`` event, but historically only for
notices owned by the **agent uid** (``juju``): the uniter's pebbleNoticer queried
Pebble without ``Users: all``, and Pebble scopes notices by owner uid, so a notice
created by a **non-root workload** (this charm's ``_daemon_`` uid) was invisible
to the noticer and never dispatched.

``trigger-notice`` therefore has two modes:
  * ``via=api`` (default) — the charm records the notice through its own Pebble
    client (agent uid), so the event IS dispatched (``test_notice_event_dispatched``).
  * ``via=workload`` — recorded from inside the workload container (workload uid).
    Fixed by juju/juju ``08a5da6e9b`` (adds ``Users: NoticesUsersAll``), which
    shipped in **3.6.25** and forward-ported to 4.0 in **4.0.13**. So 3.6/stable
    and 4.0/edge deliver it; 4.0/stable (4.0.12) does not yet, which is why
    ``test_workload_uid_notice_dispatched`` keeps a strict-xfail sentinel there.
"""

import json
import time
import uuid

import jubilant
import pytest

from .conftest import JUJU_4, JUJU_EDGE

APP = "juju-norma-k8s"


def _dispatched(juju: jubilant.Juju, key: str, *, attempts: int = 6) -> bool:
    """Poll the charm's event ledger for a dispatched pebble-custom-notice."""
    for _ in range(attempts):
        log = juju.run(
            f"{APP}/leader",
            "get-event-log",
            params={"event-filter": "pebble-custom-notice"},
        )
        events = json.loads(log.results["events"])
        if any(e.get("extra", {}).get("notice-key") == key for e in events):
            return True
        time.sleep(5)
    return False


class TestNotices:
    """US13: Custom notice trigger and dispatch."""

    def test_trigger_notice_action(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "trigger-notice")
        assert task.success
        # Juju 3.6 Pebble may prefix keys with canonical.com/.
        assert task.results["key"].endswith("calibration-test")
        assert task.results["notice-sent"] == "true"

    @pytest.mark.skipif(
        not JUJU_4,
        reason="pebble-custom-notice dispatch verified on 4.0; 3.6 behaviour unverified",
    )
    def test_notice_event_dispatched(self, juju: jubilant.Juju):
        """A notice recorded via the charm's Pebble client (agent uid, via=api)
        is delivered to the charm as a pebble-custom-notice event."""
        key = f"norma.dev/dispatch-{uuid.uuid4().hex[:8]}"
        task = juju.run(f"{APP}/leader", "trigger-notice", params={"key": key})
        assert task.success
        assert _dispatched(juju, key), (
            f"pebble-custom-notice for {key} was not dispatched (via=api)"
        )

    @pytest.mark.xfail(
        JUJU_4 and not JUJU_EDGE,
        strict=True,
        reason=(
            "Non-root workload-uid notices: the uniter pebbleNoticer "
            "(pebblenotices.go) queried Pebble without Users: NoticesUsersAll, so "
            "notices owned by the workload uid were invisible to the noticer and "
            "never dispatched. FIXED by juju/juju 08a5da6e9b ('fix(uniter): include "
            "non-root user notices in pebbleNoticer polling'), which shipped in "
            "3.6.25 and forward-ported to 4.0 in 4.0.13 — so 3.6/stable and "
            "4.0/edge dispatch them (positive assertion). 4.0/stable is still on "
            "4.0.12 (no fix), so the sentinel stays a strict-xfail there; it flips "
            "to a loud XPASS once stable ships 4.0.13+, signalling it's time to "
            "drop this marker entirely."
        ),
    )
    def test_workload_uid_notice_dispatched(self, juju: jubilant.Juju):
        """A notice recorded from inside the workload container (workload uid,
        via=workload) is delivered. Holds on 3.6.25+ and 4.0.13+; still xfails on
        4.0/stable (4.0.12), which predates the forward-port."""
        key = f"norma.dev/workload-{uuid.uuid4().hex[:8]}"
        task = juju.run(f"{APP}/leader", "trigger-notice", params={"key": key, "via": "workload"})
        assert task.success
        assert _dispatched(juju, key), (
            f"workload-uid notice {key} was NOT dispatched — expected delivery on "
            "juju with the pebbleNoticer Users:all fix (3.6.25+, 4.0.13+)."
        )
