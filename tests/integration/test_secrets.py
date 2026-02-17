"""Integration tests for US9: Juju Secrets."""

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
        juju.wait(jubilant.all_active, timeout=60)

        # Verify config reports the secret as set
        task = juju.run(f"{APP}/leader", "get-config")
        assert task.success
        assert task.results["calibration-secret"] == "set"

        # Cleanup
        juju.config(APP, reset=["calibration-secret"])
        juju.wait(jubilant.all_active, timeout=60)
        juju.remove_secret(str(uri))
