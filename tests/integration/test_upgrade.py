"""Integration tests for US15: Upgrade (charm refresh).

Live-verified behaviour (Juju 4.0.12 K8s, 2026-06-04): `juju refresh` to a new
revision RECREATES the workload pod, which resets the charm's in-memory event
ledger. The fresh unit then dispatches `upgrade-charm` as its first lifecycle
hook (upgrade-charm -> config-changed -> start -> pebble-ready), and never
`install` (install only fires on the original deploy). So we assert the
post-refresh ledger *starts with* upgrade-charm and carries no `install`, rather
than a count delta — the pre-refresh pod already carries its own upgrade-charm.
This pod-recreation-resets-ephemeral-state behaviour is exactly why the charm
keeps no StoredState (constitution) and is a key K8s-vs-machine distinction.
"""

import json
import time

import jubilant

APP = "juju-norma-k8s"


def _ledger(juju: jubilant.Juju) -> list[dict]:
    """Return the charm's in-memory event ledger (newest deploy/refresh)."""
    task = juju.run(f"{APP}/leader", "get-event-log")
    return json.loads(task.results["events"])


def _charm_rev(juju: jubilant.Juju) -> int:
    """Current charm revision, read straight from `juju status` JSON."""
    data = json.loads(juju.cli("status", "--format", "json"))
    return int(data["applications"][APP]["charm-rev"])


class TestUpgrade:
    """US15: Charm refresh, pod recreation, and version reporting."""

    def test_get_version(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-version")
        assert task.success
        assert task.results.get("charm-version"), "Charm version should be set"
        assert task.results.get("workload-version"), "Workload version should be set"

    def test_refresh_recreates_pod_and_fires_upgrade_charm(self, juju: jubilant.Juju, charm_path):
        """`juju refresh` to a new revision recreates the K8s pod and dispatches
        upgrade-charm as the first hook of the fresh unit (US15)."""
        before_rev = _charm_rev(juju)

        juju.cli("refresh", APP, "--path", str(charm_path))

        # K8s pod recreation is slow; poll for the fresh (reset) ledger: it
        # begins with upgrade-charm and — unlike the original deploy — carries
        # no `install`. Detecting the reset this way is robust to whatever the
        # pre-refresh ledger held.
        names: list[str] = []
        for _ in range(72):  # up to ~6 min
            try:
                names = [e["event_name"] for e in _ledger(juju)]
            except (jubilant.TaskError, jubilant.CLIError, TimeoutError):
                # The get-event-log action is unavailable while the pod is being
                # recreated (the whole point of the refresh) — keep polling until
                # the fresh unit answers.
                time.sleep(5)
                continue
            if names and names[0] == "upgrade-charm" and "install" not in names:
                break
            time.sleep(5)
        else:
            raise AssertionError(
                f"refresh did not dispatch upgrade-charm on a recreated pod; final ledger={names}"
            )

        assert names[0] == "upgrade-charm", f"expected upgrade-charm first, got {names}"
        # The recreated unit runs the full lifecycle behind upgrade-charm.
        assert "config-changed" in names, names
        assert "pebble-ready" in names, names
        # Revision bumped and the workload stays identifiable post-refresh (P4-5).
        assert _charm_rev(juju) > before_rev, "charm revision should bump on refresh"
        ver = juju.run(f"{APP}/leader", "get-version")
        assert ver.results.get("workload-version"), "workload version after refresh"

    def test_oci_resource_bound_to_revision(self, juju: jubilant.Juju):
        """US21: the workload image is bound to a tracked resource revision
        (the charm-rev <-> image-rev binding the calibration charm exists to
        exercise)."""
        out = juju.cli("resources", APP)
        # `juju resources <app>` lists juju-norma-image with a revision column.
        assert "juju-norma-image" in out, out
        lines = [ln for ln in out.splitlines() if "juju-norma-image" in ln]
        assert lines, out
        # The revision field (timestamp for attached/local, or a number for
        # CharmHub) must be populated — i.e. an actual revision is bound.
        assert len(lines[0].split()) >= 3, f"no revision bound: {lines[0]!r}"
