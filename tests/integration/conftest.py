"""Integration test fixtures for juju-norma-k8s charm (jubilant-based).

Usage modes:
    1. Existing deployment (fastest local iteration):
       JUJU_MODEL=us24-test make integration

    2. Fresh temp model (default, requires working juju + microk8s):
       make integration

    3. Custom juju binary:
       JUJU_CLI=~/go/bin/juju make integration

    4. Full auto-setup on a fresh machine:
       SETUP_ENVIRONMENT=1 make integration

Environment variables:
    SETUP_ENVIRONMENT   Set to "1" to auto-install snaps + bootstrap controller.
    JUJU_CHANNEL        Juju snap channel (default: "3.6/stable").
    MICROK8S_CHANNEL    microk8s snap channel (default: "1.34-strict/stable").
    JUJU_CLI            Path to juju binary (default: "juju").
    JUJU_MODEL          Reuse an existing model (skip deploy).
    JUJU_CONTROLLER     Controller name (default: "microk8s-localhost").
    CHARM_PATH          Path to .charm file or directory containing one.
    NORMA_IMAGE         OCI image URI (default: "localhost:32000/norma:0.1.0").
    KEEP_MODEL          Set to "1" to keep the model after tests (debugging).
"""

import logging
import os
import pathlib
import uuid

import jubilant
import pytest

from .setup_env import SetupError, check_prerequisites, ensure_environment

logger = logging.getLogger(__name__)

APP = "juju-norma-k8s"
CHARM_FILE_GLOB = "*norma-k8s_*.charm"
OCI_IMAGE_DEFAULT = "localhost:32000/norma:0.1.0"
RESOURCE_NAME = "juju-norma-image"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ------------------------------------------------------------------
# Session-scoped fixtures
# ------------------------------------------------------------------


@pytest.fixture(scope="session")
def environment_ready():
    """Ensure integration test prerequisites are available.

    When ``SETUP_ENVIRONMENT=1`` is set, install snaps and bootstrap a
    controller automatically.  Otherwise just verify that the tools are
    present and skip the entire session if they are not.
    """
    juju_cli = _env("JUJU_CLI", "juju")
    controller = _env("JUJU_CONTROLLER", "microk8s-localhost")

    if _env("SETUP_ENVIRONMENT") == "1":
        try:
            ensure_environment(
                juju_channel=_env("JUJU_CHANNEL", "3.6/stable"),
                microk8s_channel=_env("MICROK8S_CHANNEL", "1.34-strict/stable"),
                controller=controller,
                juju_cli=juju_cli,
            )
        except SetupError as exc:
            pytest.fail(f"Environment setup failed: {exc}")
    else:
        missing = check_prerequisites(juju_cli)
        if missing:
            pytest.skip(f"Prerequisites missing (set SETUP_ENVIRONMENT=1): {', '.join(missing)}")


@pytest.fixture(scope="session")
def charm_path() -> pathlib.Path:
    """Locate the built .charm file."""
    env = _env("CHARM_PATH")
    if env:
        p = pathlib.Path(env)
        if p.is_dir():
            charms = sorted(p.glob(CHARM_FILE_GLOB))
            assert charms, f"No {CHARM_FILE_GLOB} found in {p}"
            return charms[-1]
        return p
    charms = sorted(pathlib.Path(".").glob(CHARM_FILE_GLOB))
    assert charms, f"No {CHARM_FILE_GLOB} found; run charmcraft pack"
    return charms[-1]


@pytest.fixture(scope="session")
def oci_image() -> str:
    """OCI image URI for the norma workload."""
    return _env("NORMA_IMAGE", OCI_IMAGE_DEFAULT)


@pytest.fixture(scope="session")
def juju(environment_ready, charm_path, oci_image):
    """Provide a Juju instance with the charm deployed.

    Supports three modes:
    - JUJU_MODEL set: reuse that model (charm must be deployed already).
    - JUJU_CLI set (no JUJU_MODEL): manual model lifecycle because
      jubilant.temp_model() does not accept a cli_binary parameter.
    - Default: jubilant.temp_model() with automatic cleanup.
    """
    model = _env("JUJU_MODEL")
    cli = _env("JUJU_CLI")
    controller = _env("JUJU_CONTROLLER", "microk8s-localhost")
    keep = _env("KEEP_MODEL") == "1"

    if model:
        j = jubilant.Juju(model=model, cli_binary=cli or "juju")
        status = j.status()
        assert APP in status.apps, f"{APP} not found in model {model}"
        yield j
        return

    if cli:
        # Manual lifecycle — temp_model() ignores cli_binary.
        model_name = f"test-{uuid.uuid4().hex[:8]}"
        j = jubilant.Juju(cli_binary=cli)
        j.cli("add-model", model_name, controller)
        j = jubilant.Juju(model=model_name, cli_binary=cli)
        try:
            j.deploy(
                str(charm_path),
                app=APP,
                resources={RESOURCE_NAME: oci_image},
            )
            j.wait(jubilant.all_active, timeout=300)
            yield j
        finally:
            if not keep:
                j.cli("destroy-model", model_name, "--no-prompt", "--destroy-storage")
        return

    # Default path — let jubilant manage the model.
    with jubilant.temp_model(controller=controller) as j:
        j.deploy(
            str(charm_path),
            app=APP,
            resources={RESOURCE_NAME: oci_image},
        )
        j.wait(jubilant.all_active, timeout=300)
        yield j
