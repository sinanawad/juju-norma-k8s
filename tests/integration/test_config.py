"""Integration tests for US3: Configuration and US5: Actions."""

import contextlib
import json

import jubilant
import pytest

APP = "juju-norma-k8s"


class TestConfiguration:
    """US3: Config options apply and are queryable."""

    def test_get_config_returns_defaults(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-config")
        assert task.success
        assert task.results["calibration-string"] == "default"
        assert task.results["calibration-int"] == "8080"
        assert task.results["calibration-bool"] == "True"

    @pytest.mark.smoke
    def test_set_string_config(self, juju: jubilant.Juju):
        juju.config(APP, {"calibration-string": "integration-test"})
        juju.wait(jubilant.all_active, timeout=60)
        task = juju.run(f"{APP}/leader", "get-config")
        assert task.results["calibration-string"] == "integration-test"
        # Reset
        juju.config(APP, reset=["calibration-string"])
        juju.wait(jubilant.all_active, timeout=60)

    def test_set_int_config(self, juju: jubilant.Juju):
        juju.config(APP, {"calibration-int": "9090"})
        juju.wait(jubilant.all_active, timeout=60)
        task = juju.run(f"{APP}/leader", "get-config")
        assert task.results["calibration-int"] == "9090"
        # Reset
        juju.config(APP, reset=["calibration-int"])
        juju.wait(jubilant.all_active, timeout=60)

    def test_invalid_config_blocked(self, juju: jubilant.Juju):
        juju.config(APP, {"calibration-int": "0"})
        juju.wait(jubilant.any_blocked, timeout=60)
        status = juju.status()
        unit = next(iter(status.apps[APP].units.values()))
        assert unit.is_blocked
        # Reset to restore active
        juju.config(APP, reset=["calibration-int"])
        juju.wait(jubilant.all_active, timeout=120)


class TestConfigRejection:
    """P2-4: Juju config-engine SET-TIME rejections (before the charm sees the value).

    Live-captured on 4.0.12: each is rejected by ``juju config`` (exit 1) and the
    application state is unchanged — the unit never leaves active. Unit tests run
    *after* the value is parsed, so only a live deployment can exercise the
    engine's own validation (wrong-type / unknown-key / bad-secret-URI).
    """

    def test_unknown_option_rejected(self, juju: jubilant.Juju):
        with pytest.raises(jubilant.CLIError) as exc:
            juju.config(APP, {"nonexistent-option": "x"})
        assert "unknown option" in str(exc.value).lower(), exc.value

    def test_wrong_type_int_rejected_at_set(self, juju: jubilant.Juju):
        with pytest.raises(jubilant.CLIError) as exc:
            juju.config(APP, {"calibration-int": "not-an-integer"})
        assert "expected int" in str(exc.value).lower(), exc.value

    def test_wrong_type_bool_rejected_at_set(self, juju: jubilant.Juju):
        with pytest.raises(jubilant.CLIError) as exc:
            juju.config(APP, {"calibration-bool": "not-a-bool"})
        assert "expected bool" in str(exc.value).lower(), exc.value

    def test_bad_secret_uri_rejected_as_notvalid(self, juju: jubilant.Juju):
        # A ``type: secret`` option is validated as a secret URI at SET time, so a
        # non-URI is rejected by the engine (NotValid) and never reaches the charm.
        with pytest.raises(jubilant.CLIError) as exc:
            juju.config(APP, {"calibration-secret": "not-a-secret-uri"})
        assert "secret" in str(exc.value).lower(), exc.value


class TestBadBehaviorModesLive:
    """P2-4: status-emitting bad-behavior modes surfaced on a live deployment.

    Runs on a FRESH SINGLE-UNIT app (``norma-badmode``), not the shared
    deployment. A multi-unit app exhibits a juju K8s per-unit status-convergence
    race under rapid config churn: live-confirmed on 4.0.12, a non-leader unit can
    stick in the prior bad-behavior status for minutes after the mode is reset
    (the config value is correct, but that unit's reported workload status lags
    until the next update-status). That makes shared set/reset cycles with an
    ``all_active`` wait unreliable. A single-unit (leader-only) app converges
    deterministically on every transition.

    The destructive modes (hook-error -> agent error; stuck-dying -> Life=Dying)
    and their ``juju resolve`` recovery belong to P2-5; secret-in-relation needs
    an established relation (P2-8). All three — plus every mode here — are pinned
    deterministically by the unit suite (``TestBadBehaviorModes``); this test adds
    live end-to-end confirmation that the status actually surfaces in ``juju``.
    """

    def test_status_modes_surface_on_isolated_app(
        self, juju: jubilant.Juju, charm_path, oci_image
    ):
        app = "norma-badmode"
        # A bare filename ("foo.charm") is ambiguous to `juju deploy` (local vs
        # CharmHub); ensure it reads as a local path. CI passes a slashed path.
        local_charm = str(charm_path)
        if "/" not in local_charm:
            local_charm = f"./{local_charm}"

        def message() -> str:
            return next(iter(juju.status().apps[app].units.values())).workload_status.message

        try:
            juju.cli("deploy", local_charm, app, "--resource", f"juju-norma-image={oci_image}")
            juju.wait(lambda s: app in s.apps and s.apps[app].is_active, timeout=300)

            # active-with-message — active, but carrying a §4c.2-violating message.
            # (active-ness alone settles before the message does, so wait on the
            # message itself.)
            juju.config(app, {"bad-behavior-mode": "active-with-message"})
            juju.wait(
                lambda s: all(
                    u.is_active and u.workload_status.message == "serving on port 8080"
                    for u in s.apps[app].units.values()
                ),
                timeout=120,
            )

            # blocked-no-message — blocked with an un-actionable EMPTY message.
            juju.config(app, {"bad-behavior-mode": "blocked-no-message"})
            juju.wait(lambda s: jubilant.any_blocked(s, app), timeout=120)
            assert message() == "", message()

            # stuck-maintenance — held in maintenance indefinitely.
            juju.config(app, {"bad-behavior-mode": "stuck-maintenance"})
            juju.wait(lambda s: jubilant.any_maintenance(s, app), timeout=120)
            assert "preparing calibration suite" in message()

            # unknown value — the engine accepts any string for a `type: string`
            # option; the CHARM normalises it back to compliant active (logged
            # warning), which also proves recovery out of maintenance.
            juju.config(app, {"bad-behavior-mode": "totally-bogus-mode"})
            juju.wait(
                lambda s: (
                    bool(s.apps[app].units)
                    and all(u.is_active for u in s.apps[app].units.values())
                ),
                timeout=120,
            )
            assert message() == "", message()
        finally:
            with contextlib.suppress(jubilant.CLIError):
                juju.cli("remove-application", app, "--force", "--no-wait", "--no-prompt")
            with contextlib.suppress(jubilant.CLIError, TimeoutError):
                juju.wait(lambda s: app not in s.apps, timeout=180)


class TestActions:
    """US5: Action execution and error reporting."""

    def test_fail_action(self, juju: jubilant.Juju):
        try:
            juju.run(f"{APP}/leader", "fail-action", params={"message": "test failure"})
            pytest.fail("fail-action should raise TaskError")
        except jubilant.TaskError as e:
            assert "test failure" in e.task.message

    def test_get_event_log_with_filter(self, juju: jubilant.Juju):
        task = juju.run(
            f"{APP}/leader", "get-event-log", params={"event-filter": "config-changed"}
        )
        assert task.success
        events = json.loads(task.results["events"])
        assert all("config-changed" in e["event_name"] for e in events)

    def test_get_event_log_with_limit(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-event-log", params={"limit": 3})
        assert task.success
        events = json.loads(task.results["events"])
        assert len(events) <= 3
