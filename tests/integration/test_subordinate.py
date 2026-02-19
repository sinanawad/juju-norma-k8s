"""Integration tests for US25: Subordinate Charm Integration.

Tests the principal charm's juju-info provides endpoint and the full
subordinate lifecycle: deploy, integrate, verify cohabitation, introspect,
remove relation, and cleanup.

K8s subordinate limitation: subordinate agent installation fails on all
current Juju versions:
  - Juju 3.6: agent hangs at "installing agent" / "allocating" indefinitely
  - Juju 4.x: crashes with "getting principal unit machine information:
    unit ... is not assigned to a machine in the model"

Tests are marked xfail(strict=False) so they auto-detect when the fix lands
on any version. Timeouts are kept short (60s) to avoid wasting CI time on
known failures.
"""

import contextlib
import json
import logging

import jubilant
import pytest

logger = logging.getLogger(__name__)

APP = "juju-norma-k8s"
SUB_APP = "norma-sub"

# K8s subordinates don't work on any current Juju version — mark unconditionally.
_K8S_SUB_XFAIL = pytest.mark.xfail(
    reason="K8s subordinate agent install hangs (3.6) or crashes (4.x)",
    strict=False,
)


def _force_remove_subordinate(juju: jubilant.Juju) -> None:
    """Best-effort removal of the subordinate app.

    Uses --force --no-wait to avoid hanging on stuck subordinate agents.
    Waits up to 60s for the app to disappear.
    """
    status = juju.status()
    if SUB_APP not in status.apps:
        return
    with contextlib.suppress(jubilant.CLIError):
        juju.remove_relation(f"{APP}:juju-info", f"{SUB_APP}:juju-info")
    with contextlib.suppress(jubilant.CLIError):
        juju.cli("remove-application", SUB_APP, "--force", "--no-wait", "--no-prompt")
    with contextlib.suppress(TimeoutError):
        juju.wait(lambda s: SUB_APP not in s.apps, timeout=60)


class TestSubordinateIntegration:
    """US25: Subordinate charm lifecycle via juju-info endpoint."""

    @_K8S_SUB_XFAIL
    def test_subordinate_deployed_and_integrated(
        self,
        juju: jubilant.Juju,
        subordinate_charm_path,
    ):
        """AC1: Subordinate unit auto-created per principal unit, sharing the pod."""
        if subordinate_charm_path is None:
            pytest.skip("Subordinate charm not built (no *subordinate*.charm found)")

        status = juju.status()
        if SUB_APP not in status.apps:
            juju.deploy(str(subordinate_charm_path), app=SUB_APP)

        # Integrate — subordinate units are created automatically.
        with contextlib.suppress(jubilant.CLIError):
            juju.integrate(f"{APP}:juju-info", f"{SUB_APP}:juju-info")

        # Wait for both apps to settle (short timeout — known to hang).
        juju.wait(jubilant.all_active, timeout=120)

        status = juju.status()
        principal_units = list(status.apps[APP].units.keys())
        sub_units = list(status.apps[SUB_APP].units.keys())
        assert len(sub_units) >= 1, "At least one subordinate unit should exist"
        assert len(sub_units) == len(principal_units), (
            f"1:1 mapping: {len(principal_units)} principal, {len(sub_units)} subordinate"
        )

    @_K8S_SUB_XFAIL
    def test_subordinate_scales_with_principal(
        self,
        juju: jubilant.Juju,
        subordinate_charm_path,
    ):
        """AC2: Scaling principal to 3 creates 3 subordinate units."""
        if subordinate_charm_path is None:
            pytest.skip("Subordinate charm not built")

        # Ensure subordinate is integrated first.
        status = juju.status()
        if SUB_APP not in status.apps:
            pytest.skip("Subordinate not deployed (depends on previous test)")

        juju.add_unit(APP, num_units=2)
        juju.wait(jubilant.all_active, timeout=120)

        status = juju.status()
        assert len(status.apps[APP].units) == 3
        assert len(status.apps[SUB_APP].units) == 3, "3 subordinate units for 3 principal"

        # Scale back down.
        juju.remove_unit(APP, num_units=2)
        juju.wait(
            lambda s: len(s.apps[APP].units) == 1,
            timeout=120,
        )

    @_K8S_SUB_XFAIL
    def test_introspect_shows_subordinate_relation(
        self,
        juju: jubilant.Juju,
        subordinate_charm_path,
    ):
        """AC3: Introspect relations section includes juju-info with subordinate data."""
        if subordinate_charm_path is None:
            pytest.skip("Subordinate charm not built")

        status = juju.status()
        if SUB_APP not in status.apps:
            pytest.skip("Subordinate not deployed (depends on previous test)")

        task = juju.run(f"{APP}/leader", "introspect", params={"sections": "relations"})
        assert task.success
        relations = json.loads(task.results["relations"])
        assert "juju-info" in relations, "juju-info endpoint should appear in relations"
        assert len(relations["juju-info"]) >= 1

    @_K8S_SUB_XFAIL
    def test_relation_removal_cleans_up(
        self,
        juju: jubilant.Juju,
        subordinate_charm_path,
    ):
        """AC4: Removing the relation removes subordinate units."""
        if subordinate_charm_path is None:
            pytest.skip("Subordinate charm not built")

        status = juju.status()
        if SUB_APP not in status.apps:
            pytest.skip("Subordinate not deployed (depends on previous test)")

        with contextlib.suppress(jubilant.CLIError):
            juju.remove_relation(f"{APP}:juju-info", f"{SUB_APP}:juju-info")

        # Wait for subordinate units to be removed.
        juju.wait(
            lambda s: SUB_APP not in s.apps or len(s.apps[SUB_APP].units) == 0,
            timeout=120,
        )

        # Principal should return to active.
        juju.wait(jubilant.all_active, timeout=60)

        # Verify relation-broken logged on the principal.
        task = juju.run(
            f"{APP}/leader",
            "get-event-log",
            params={"event-filter": "relation-broken"},
        )
        events = json.loads(task.results["events"])
        assert len(events) >= 1, "relation-broken should be in event ledger"

        # Cleanup subordinate app.
        _force_remove_subordinate(juju)

    def test_active_without_subordinate(self, juju: jubilant.Juju):
        """AC5: Principal reaches active status without subordinate integration.

        This test verifies the principal is active on its own. If a stuck
        subordinate exists from previous tests, force-remove it first.
        """
        _force_remove_subordinate(juju)

        # Check principal unit directly — don't use all_active which would
        # also check any lingering subordinate units.
        status = juju.status()
        principal_unit = next(iter(status.apps[APP].units.values()))
        assert principal_unit.workload_status.current == "active"
