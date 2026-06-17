"""Integration tests for US15: Upgrade (charm refresh).

Live investigation (Juju 4.0.12 K8s, 2026-06-17) of what `juju refresh` to a
rebuilt local charm actually does, observed over repeated cycles:

- The charm REVISION always bumps (local-charm refresh increments every time).
  This is the one deterministic signal that the refresh took effect.
- The workload pod is recreated, which resets the charm's ephemeral /tmp event
  ledger — BUT this is nondeterministic to observe:
    * timing varies (seconds locally, sometimes minutes under CI load), and
    * the recreated pod's reset ledger sometimes begins with `upgrade-charm`
      and sometimes with `start` — the `upgrade-charm` hook can be dispatched
      to the *terminating old pod*, so it is not reliably present on the new
      pod's fresh ledger.

So this suite asserts only the deterministic facts (revision bump + the charm
reconciling back to active + workload version still reported). That the charm
RECORDS `upgrade-charm` on the upgrade is covered deterministically by the unit
suite (test_charm.py::TestUpgrade::test_upgrade_charm_fires_reconcile); asserting
it against a live recreated pod was an intermittent CI flake and is intentionally
not done here.
"""

import time

import jubilant

APP = "juju-norma-k8s"


class TestUpgrade:
    """US15: Charm refresh and version reporting."""

    def test_get_version(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-version")
        assert task.success
        assert task.results.get("charm-version"), "Charm version should be set"
        assert task.results.get("workload-version"), "Workload version should be set"

    def test_refresh_bumps_revision_and_charm_survives(self, juju: jubilant.Juju, charm_path):
        """`juju refresh` to the rebuilt local charm bumps the charm revision and
        the charm reconciles back to active with its workload version still
        reported (US15 + P4-5 image distinguishability survives a refresh).

        The revision bump is the deterministic "refresh took effect" signal; the
        K8s pod recreation it triggers is real but nondeterministic to observe
        (see module docstring), so it is not asserted here.
        """
        before_rev = juju.status().apps[APP].charm_rev

        juju.cli("refresh", APP, "--path", str(charm_path))

        # The refresh recreates the workload pod asynchronously, and during that
        # window the leader cannot run actions (the action errors / times out).
        # Poll get-version THROUGH that window — tolerating the gap — until the
        # unit answers with its workload version. This proves the charm + workload
        # survive the refresh and stay identifiable (P4-5) without depending on the
        # nondeterministic ledger-reset / upgrade-charm ordering (see module
        # docstring). A single get-version call here raced the recreation and
        # flaked all three legs.
        workload_version = ""
        deadline = time.monotonic() + 420  # ~7 min; K8s recreation can be slow under load
        while time.monotonic() < deadline:
            try:
                task = juju.run(f"{APP}/leader", "get-version", wait=30)
                workload_version = task.results.get("workload-version", "")
            except (jubilant.TaskError, jubilant.CLIError, TimeoutError, ValueError):
                time.sleep(5)
                continue
            if workload_version:
                break
            time.sleep(5)

        assert workload_version, "workload did not report a version within 7min after refresh"
        # Deterministic signal that the refresh actually took effect.
        after_rev = juju.status().apps[APP].charm_rev
        assert after_rev > before_rev, f"rev should bump: {before_rev} -> {after_rev}"

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
