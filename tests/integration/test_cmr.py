"""Integration tests for US19: Cross-Model Relations.

Tests deploy a second norma instance in a separate model, create a
cross-model offer on the ``calibration-provider`` endpoint, consume it
from the second model, integrate, and verify relation data flows.
"""

import contextlib
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
                f"{self.model_a.model}.{APP}:calibration-provider",
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
        model = self.model_a.model
        self.model_a.cli(
            "offer",
            f"{model}.{APP}:calibration-provider",
            include_model=False,
        )

    def _consume_and_integrate(self):
        """Consume the offer in model B and integrate."""
        model_a = self.model_a.model
        # Use an alias — model B already has a local app with the same name.
        self.juju_b.cli(
            "consume",
            f"{model_a}.{APP}",
            "remote-norma",
            include_model=False,
        )
        self.juju_b.cli(
            "integrate", "remote-norma:calibration-provider", f"{APP}:calibration-requirer"
        )

    def test_cmr_offer_create(self):
        """Create an offer on the calibration-provider endpoint."""
        self._offer()
        result = self.model_a.cli(
            "show-offer",
            f"{self.model_a.model}.{APP}",
            include_model=False,
        )
        assert "calibration-provider" in result

    def test_cmr_consume_and_integrate(self):
        """Consume the offer from model B and integrate."""
        self._offer()
        self._consume_and_integrate()
        self.juju_b.wait(jubilant.all_active, timeout=120)

        # Verify relation exists.
        status = self.juju_b.status()
        app_relations = status.apps[APP].relations
        assert any(
            "calibration" in iface
            for rels in app_relations.values()
            for rel in (rels if isinstance(rels, list) else [rels])
            for iface in ([rel.interface] if hasattr(rel, "interface") else [str(rel)])
        ), f"Expected calibration relation, got: {app_relations}"

    def test_cmr_relation_data_exchange(self):
        """Verify relation data flows across models."""
        self._offer()
        self._consume_and_integrate()
        self.juju_b.wait(jubilant.all_active, timeout=120)

        # Check relation data via introspect action on model A.
        task = self.model_a.run(f"{APP}/leader", "introspect", params={"sections": "relations"})
        assert task.success
        assert "calibration-provider" in task.results.get("relations", "")
