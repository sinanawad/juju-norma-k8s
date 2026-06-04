"""Integration tests for US19: Cross-Model Relations.

Tests deploy a second norma instance in a separate model, create a
cross-model offer on the ``calibration-provider`` endpoint, consume it
from the second model, integrate, and verify relation data flows.
"""

import contextlib
import time
import uuid

import jubilant
import pytest

APP = "juju-norma-k8s"


class TestCMR:
    """US19: Cross-model relation offer/consume cycle."""

    @pytest.fixture(autouse=True)
    def cmr_setup(self, juju: jubilant.Juju, charm_path, oci_image):
        """Set up a second model with norma for CMR testing."""
        self.model_a = juju
        # juju.model is controller-qualified ("<controller>:<model>"); offer /
        # consume / show-offer URLs need the BARE model name — strip the prefix.
        self.model_a_name = juju.model.split(":")[-1]
        cli = juju.cli_binary if hasattr(juju, "cli_binary") else "juju"

        # Create model B on the SAME controller + cloud as model A. Resolve both
        # from the same env vars conftest uses, NOT by parsing `show-model`: that
        # JSON is keyed by the QUALIFIED model name, so the old bare-name lookup
        # returned {} and fell back to cloud "microk8s" + empty controller — which
        # fails in CI, where the k8s cloud is registered as "mk8s"
        # ("ERROR cloud microk8s not found"). Single source of truth.
        from .conftest import CLOUD_DEFAULT, CONTROLLER_DEFAULT, _env

        self.model_b_name = f"cmr-{uuid.uuid4().hex[:8]}"
        no_model = jubilant.Juju(cli_binary=cli)
        ctrl_name = _env("JUJU_CONTROLLER", CONTROLLER_DEFAULT)
        cloud = _env("JUJU_CLOUD", CLOUD_DEFAULT)
        no_model.cli("add-model", self.model_b_name, cloud, "-c", ctrl_name, include_model=False)
        self.juju_b = jubilant.Juju(model=self.model_b_name, cli_binary=cli)

        # Deploy norma in model B.
        from .conftest import _deploy_with_retry

        _deploy_with_retry(self.juju_b, str(charm_path), oci_image)
        self.juju_b.wait(jubilant.all_active, timeout=300)

        yield

        # Cleanup: remove offer, destroy model B.
        with contextlib.suppress(jubilant.CLIError):
            self.model_a.cli(
                "remove-offer",
                f"{self.model_a_name}.{APP}:calibration-provider",
                "--force",
                include_model=False,
            )
        no_model.cli(
            "destroy-model",
            self.model_b_name,
            "--no-prompt",
            "--destroy-storage",
            include_model=False,
        )

    def _offer(self):
        """Create a CMR offer from model A's calibration-provider."""
        self.model_a.cli(
            "offer",
            f"{self.model_a_name}.{APP}:calibration-provider",
            include_model=False,
        )

    def _consume_and_integrate(self):
        """Consume the offer in model B and integrate."""
        # Use an alias — model B already has a local app with the same name.
        self.juju_b.cli(
            "consume",
            f"{self.model_a_name}.{APP}",
            "remote-norma",
            include_model=False,
        )
        self.juju_b.cli(
            "integrate", "remote-norma:calibration-provider", f"{APP}:calibration-requirer"
        )

    def test_cmr_offer_consume_integrate(self):
        """Full CMR cycle in ONE test: offer -> show-offer -> consume -> integrate
        -> verify relation + cross-model data flow.

        Consolidated from three separate tests so the heavy model-B setup/teardown
        (the autouse `cmr_setup` fixture) runs ONCE rather than 3x: per-test
        `destroy-model` of a CAAS model is slow on K8s and tripled the nightly
        cost (the edge leg timed out at 80 min).
        """
        # US19 offer: create + verify via show-offer.
        self._offer()
        result = self.model_a.cli(
            "show-offer",
            f"{self.model_a_name}.{APP}",
            include_model=False,
        )
        assert "calibration-provider" in result

        # Consume + integrate from model B; verify the relation exists.
        self._consume_and_integrate()
        self.juju_b.wait(jubilant.all_active, timeout=120)
        status = self.juju_b.status()
        app_relations = status.apps[APP].relations
        assert any(
            "calibration" in iface
            for rels in app_relations.values()
            for rel in (rels if isinstance(rels, list) else [rels])
            for iface in ([rel.interface] if hasattr(rel, "interface") else [str(rel)])
        ), f"Expected calibration relation, got: {app_relations}"

        # Cross-model relation data flows to model A. The CMR relation can take a
        # moment to propagate to the offering side after integrate, so poll the
        # introspection rather than asserting once (this was an intermittent flake).
        relations = ""
        for _ in range(18):  # ~90s
            task = self.model_a.run(
                f"{APP}/leader", "introspect", params={"sections": "relations"}
            )
            relations = task.results.get("relations", "") if task.success else ""
            if "calibration-provider" in relations:
                break
            time.sleep(5)
        assert "calibration-provider" in relations, (
            f"calibration-provider relation did not propagate to model A: {relations}"
        )
