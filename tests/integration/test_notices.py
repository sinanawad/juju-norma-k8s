"""Integration tests for US13: Pebble Custom Notices.

Verified live on Juju 4.0.12 (2026-06-04): Juju DOES dispatch the
``pebble-custom-notice`` event, but ONLY for notices owned by the **agent uid**
(``juju``). The uniter's pebbleNoticer queries Pebble without ``Users: all``, and
Pebble scopes notices by owner uid, so a notice created by a **non-root workload**
(this charm's ``_daemon_`` uid) is invisible to the noticer and never dispatched.

``trigger-notice`` therefore has two modes:
  * ``via=api`` (default) — the charm records the notice through its own Pebble
    client (agent uid), so the event IS dispatched (``test_notice_event_dispatched``).
  * ``via=workload`` — recorded from inside the workload container (workload uid).
    Fixed on 3.6.25 (juju/juju ``08a5da6e9b`` added ``Users: NoticesUsersAll`` to
    the noticer) so 3.6 delivers it; 4.0.x has not yet received the fix, so
    ``test_workload_uid_notice_not_dispatched`` is a strict-xfail sentinel on
    JUJU_4 that flips to XPASS when the fix forward-ports to 4.0.
"""

import json
import time
import uuid

import jubilant
import pytest

from .conftest import JUJU_4

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
        JUJU_4,
        strict=True,
        reason=(
            "Non-root workload-uid notices: the uniter pebbleNoticer "
            "(pebblenotices.go) queried Pebble without Users: NoticesUsersAll, so "
            "notices owned by the workload uid were invisible to the noticer and "
            "never dispatched. FIXED on 3.6 by juju/juju 08a5da6e9b ('fix(uniter): "
            "include non-root user notices in pebbleNoticer polling', shipped "
            "3.6.25) — so 3.6/stable now dispatches them (positive assertion). 4.0 "
            "has NOT yet received the fix (4.0.x still omits Users:all), so the "
            "sentinel stays a strict-xfail there; it flips to a loud XPASS when the "
            "fix forward-ports to 4.0, signalling it's time to drop this marker."
        ),
    )
    def test_workload_uid_notice_not_dispatched(self, juju: jubilant.Juju):
        """Sentinel: a notice recorded from inside the workload container
        (workload uid, via=workload). Delivered on 3.6.25+ (fixed); NOT delivered
        on 4.0.x (still omits Users: NoticesUsersAll) — hence the JUJU_4 xfail."""
        key = f"norma.dev/workload-{uuid.uuid4().hex[:8]}"
        task = juju.run(f"{APP}/leader", "trigger-notice", params={"key": key, "via": "workload"})
        assert task.success
        assert _dispatched(juju, key), (
            f"workload-uid notice {key} was dispatched — Juju appears to have "
            "fixed the noticer (add Users:all). Promote this to a positive test."
        )
