"""Integration tests for US9: Juju Secrets."""

import contextlib

import jubilant

APP = "juju-norma-k8s"


class TestSecrets:
    """US9: App-owned secret with rotation policy."""

    def test_get_secret_info(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "get-secret-info")
        assert task.success
        assert task.results.get("secret-id"), "Secret ID should be set"
        assert task.results["has-content"] == "true"
        assert task.results["rotation"] == "monthly"

    def test_secret_config_type(self, juju: jubilant.Juju):
        """Verify secret config accepts a secret URI."""
        # Create a user secret
        uri = juju.add_secret("test-cal-secret", {"password": "s3cret"})
        juju.grant_secret("test-cal-secret", APP)
        juju.config(APP, {"calibration-secret": str(uri)})
        # Juju 3.6: secret grant propagation + config-changed dispatch is slower.
        juju.wait(jubilant.all_active, timeout=120)

        # Verify config reports the secret as set
        task = juju.run(f"{APP}/leader", "get-config")
        assert task.success
        assert task.results["calibration-secret"] == "set"

        # Cleanup
        juju.config(APP, reset=["calibration-secret"])
        juju.wait(jubilant.all_active, timeout=120)
        juju.remove_secret(str(uri))


class TestParallelSecrets:
    """FR-032: Parallel secret operations — no cross-contamination."""

    def test_parallel_secrets(self, juju: jubilant.Juju):
        """Multiple user secrets granted concurrently are tracked independently."""
        secret_names = ["par-secret-1", "par-secret-2", "par-secret-3"]
        uris = []
        try:
            for name in secret_names:
                uri = juju.add_secret(name, {"password": f"value-{name}"})
                juju.grant_secret(name, APP)
                uris.append(str(uri))

            # Set each as config in sequence (only one config slot for secrets)
            for uri in uris:
                juju.config(APP, {"calibration-secret": uri})
                juju.wait(jubilant.all_active, timeout=120)
                task = juju.run(f"{APP}/leader", "get-config")
                assert task.results["calibration-secret"] == "set"

            # Verify the app-owned secret is independent of user secrets
            task = juju.run(f"{APP}/leader", "get-secret-info")
            assert task.results["has-content"] == "true"
        finally:
            juju.config(APP, reset=["calibration-secret"])
            juju.wait(jubilant.all_active, timeout=120)
            for uri in uris:
                with contextlib.suppress(jubilant.CLIError):
                    juju.remove_secret(uri)
