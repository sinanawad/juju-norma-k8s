"""Integration tests for US13: Pebble Custom Notices.

Juju dispatches the ``pebble-custom-notice`` event for notices owned by the agent
uid AND — since juju/juju ``08a5da6e9b`` added ``Users: NoticesUsersAll`` to the
uniter's pebbleNoticer — by a **non-root workload** uid too. Before that fix
Pebble's per-uid notice scoping hid workload-created notices from the noticer
entirely, so they were never delivered.

``trigger-notice`` exercises both owners:
  * ``via=api`` (default) — recorded through the charm's own Pebble client, i.e.
    the agent uid (``test_notice_event_dispatched``).
  * ``via=workload`` — recorded from inside the workload container, i.e. the
    workload uid (``test_workload_uid_notice_dispatched``).

Both are plain positive assertions on every channel we test. The workload-uid
case carried a strict-xfail sentinel while the fix rolled out; it has now landed
on all three (3.6.25+ / 4.0.13+), the sentinel XPASSed on 4.0/stable when that
channel moved to 4.0.14, and the marker was retired. Version floors, should an
older Juju ever be added to the matrix: **3.6.25** and **4.0.13**.
"""

import json
import time
import uuid

import jubilant

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

    def test_notice_event_dispatched(self, juju: jubilant.Juju):
        """A notice recorded via the charm's Pebble client (agent uid, via=api)
        is delivered to the charm as a pebble-custom-notice event."""
        key = f"norma.dev/dispatch-{uuid.uuid4().hex[:8]}"
        task = juju.run(f"{APP}/leader", "trigger-notice", params={"key": key})
        assert task.success
        assert _dispatched(juju, key), (
            f"pebble-custom-notice for {key} was not dispatched (via=api)"
        )

    def test_workload_uid_notice_dispatched(self, juju: jubilant.Juju):
        """A notice recorded from inside the workload container (workload uid,
        via=workload) is delivered — the case the pebbleNoticer Users:all fix
        (3.6.25+, 4.0.13+) enabled."""
        key = f"norma.dev/workload-{uuid.uuid4().hex[:8]}"
        task = juju.run(f"{APP}/leader", "trigger-notice", params={"key": key, "via": "workload"})
        assert task.success
        assert _dispatched(juju, key), (
            f"workload-uid notice {key} was NOT dispatched — expected delivery on "
            "juju with the pebbleNoticer Users:all fix (3.6.25+, 4.0.13+)."
        )
