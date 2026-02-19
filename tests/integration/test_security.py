"""Integration tests for US17: Non-Root Security and FR-039: Credential-Get."""

import contextlib

import jubilant
import pytest

APP = "juju-norma-k8s"


class TestSecurity:
    """US17: Non-root execution and security posture."""

    def test_check_security_returns_uid(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "check-security")
        assert task.success
        assert task.results.get("charm-uid"), "Charm UID should be reported"
        # Non-root: UID should not be 0
        assert task.results["charm-uid"] != "0", "Charm should run as non-root"

    def test_check_security_gid(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "check-security")
        assert task.results.get("charm-gid"), "Charm GID should be reported"

    def test_check_security_workload_uid(self, juju: jubilant.Juju):
        task = juju.run(f"{APP}/leader", "check-security")
        workload_uid = task.results.get("workload-uid")
        if workload_uid and workload_uid != "unavailable":
            assert workload_uid != "0", "Workload should run as non-root"

    def test_check_security_credential_keys_present(self, juju: jubilant.Juju):
        """FR-039: check-security includes credential-get result keys."""
        task = juju.run(f"{APP}/leader", "check-security")
        assert "credential-endpoint" in task.results
        assert "credential-auth-type" in task.results
        assert "k8s-api-reachable" in task.results


class TestCredentialGet:
    """FR-039: Credential-get hook tool exercise via check-security action."""

    def test_credential_get_with_trust(self, juju: jubilant.Juju):
        """With --trust, credential-get returns K8s cloud credentials."""
        # Grant trust if not already granted
        with contextlib.suppress(jubilant.CLIError):
            juju.cli("trust", APP, "--scope=cluster")

        task = juju.run(f"{APP}/leader", "check-security")
        assert task.success
        assert task.results.get("trust-available") == "true", "Trust should be available"
        assert task.results["cloud-type"], "Cloud type should be reported"
        assert task.results["credential-endpoint"], "Endpoint should be reported"
        assert task.results["credential-auth-type"], "Auth type should be reported"

    def test_credential_get_without_trust(self, juju: jubilant.Juju):
        """Without --trust, credential-get reports unavailable gracefully.

        This test can only give signal when trust has NOT been granted.
        Since trust is irrevocable in a shared model, skip explicitly
        when the prior test has already granted trust.
        """
        task = juju.run(f"{APP}/leader", "check-security")
        if task.results.get("trust-available") == "true":
            pytest.skip("Trust already granted (irrevocable in shared model)")
        assert task.results["credential-endpoint"] == ""
        assert task.results["k8s-api-reachable"] == "false"
