"""Integration tests for US17: Non-Root Security."""

import jubilant

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
