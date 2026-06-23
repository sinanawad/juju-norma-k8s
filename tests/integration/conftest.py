"""Integration test fixtures for juju-norma-k8s charm (jubilant-based).

Usage modes:
    1. Existing deployment (fastest local iteration):
       JUJU_MODEL=us24-test make integration

    2. Fresh temp model (default, requires working juju + microk8s):
       make integration

    3. Custom juju binary with fresh controller:
       JUJU_CLI=~/go/bin/juju JUJU_CONTROLLER=k8s make integration

    4. Full auto-setup on a fresh machine:
       SETUP_ENVIRONMENT=1 make integration

Environment variables:
    SETUP_ENVIRONMENT   Set to "1" to auto-install snaps + bootstrap controller.
    FRESH_CONTROLLER    Set to "1" to destroy and re-bootstrap the controller
                        before tests (ensures jujud matches the client version).
    JUJU_CHANNEL        Juju snap channel (default: "3.6/stable").
    MICROK8S_CHANNEL    microk8s snap channel (default: "1.34-strict/stable").
    JUJU_CLI            Path to juju binary (default: "juju").
    JUJU_MODEL          Reuse an existing model (skip deploy).
    JUJU_CONTROLLER     Controller name (default: "microk8s-localhost").
    JUJU_CLOUD          Cloud name for add-model (default: "microk8s").
    CHARM_PATH          Path to .charm file or directory containing one.
    NORMA_IMAGE         OCI image URI (default: "ghcr.io/sinanawad/juju-norma:latest").
    KEEP_MODEL          Set to "1" to keep the model after tests (debugging).
"""

import logging
import os
import pathlib
import subprocess
import time
import uuid

import jubilant
import pytest

from .setup_env import SetupError, bootstrap_controller, check_prerequisites, ensure_environment

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    """Register custom CLI flags for integration tests."""
    parser.addoption(
        "--run-destructive",
        action="store_true",
        default=False,
        help="Run destructive tests (e.g., force-remove application)",
    )


APP = "juju-norma-k8s"
CHARM_FILE_GLOB = "*norma-k8s_*.charm"
OCI_IMAGE_DEFAULT = "ghcr.io/sinanawad/juju-norma:latest"
# setup_env._register_microk8s_cloud registers the k8s cloud as "mk8s" (the
# built-in "microk8s" name is reserved), and bootstraps on it. Keep the default
# here in sync so the FRESH_CONTROLLER and JUJU_CLI add-model paths reference the
# SAME cloud the controller was bootstrapped on.
CONTROLLER_DEFAULT = "microk8s-localhost"
CLOUD_DEFAULT = "mk8s"
RESOURCE_NAME = "juju-norma-image"
DEPLOY_RETRIES = 3
DEPLOY_RETRY_DELAY = 5  # seconds


def _deploy_with_retry(j: jubilant.Juju, charm_path: str, oci_image: str) -> None:
    """Deploy the charm, retrying on the OCI resource race (juju/juju#21456).

    The server-side ``deployResources`` races with ``Deploy`` — the resource
    upload hits the API before the application row exists.  A simple retry
    after a short sleep is sufficient because the application is created
    within milliseconds of the first attempt.
    """
    for attempt in range(1, DEPLOY_RETRIES + 1):
        try:
            j.deploy(
                charm_path,
                app=APP,
                resources={RESOURCE_NAME: oci_image},
            )
            return
        except jubilant.CLIError as exc:
            if "not found" in str(exc) and attempt < DEPLOY_RETRIES:
                logger.warning(
                    "deploy attempt %d/%d hit resource race, retrying in %ds",
                    attempt,
                    DEPLOY_RETRIES,
                    DEPLOY_RETRY_DELAY,
                )
                time.sleep(DEPLOY_RETRY_DELAY)
                continue
            raise


def _detect_juju_major_version() -> int:
    """Detect the Juju major version at collection time.

    Checks JUJU_CHANNEL env var first, then runs ``juju version``.
    Used for conditional xfail markers on Juju 4 WIP limitations.
    """
    channel = os.environ.get("JUJU_CHANNEL", "")
    if channel:
        try:
            return int(channel.split(".")[0].split("/")[0])
        except ValueError:
            pass
    cli = os.environ.get("JUJU_CLI", "juju")
    try:
        result = subprocess.run([cli, "version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return int(result.stdout.strip().split(".")[0])
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return 0


JUJU_MAJOR = _detect_juju_major_version()
JUJU_4 = JUJU_MAJOR >= 4
# 4.0/edge ships fixes ahead of 4.0/stable (e.g. the K8s mem-constraint regression
# #22650, fixed on edge ~2026-06-23 but not yet on stable). Channel-aware so
# version-delta xfails can target only the channel that still carries the bug.
JUJU_CHANNEL = os.environ.get("JUJU_CHANNEL", "")
JUJU_EDGE = "edge" in JUJU_CHANNEL


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def kubectl(*args: str, timeout: int = 60):
    """Run ``microk8s kubectl`` (override via ``$KUBECTL``).

    CI sets ``KUBECTL="sudo microk8s kubectl"`` because the runner user is not
    yet in the ``snap_microk8s`` group within the same job. Returns the
    ``CompletedProcess`` or ``None`` when kubectl is unavailable, so pod-spec
    tests can ``skip`` gracefully off microk8s rather than error.
    """
    base = os.environ.get("KUBECTL", "microk8s kubectl").split()
    try:
        return subprocess.run([*base, *args], capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


# ------------------------------------------------------------------
# Session-scoped fixtures
# ------------------------------------------------------------------


@pytest.fixture(scope="session")
def environment_ready():
    """Ensure integration test prerequisites are available.

    When ``SETUP_ENVIRONMENT=1`` is set, install snaps and bootstrap a
    controller automatically.  When ``FRESH_CONTROLLER=1`` is set,
    destroy any existing controller and re-bootstrap so that the
    controller jujud matches the client version.  Otherwise just verify
    that the tools are present and skip the session if they are not.
    """
    juju_cli = _env("JUJU_CLI", "juju")
    controller = _env("JUJU_CONTROLLER", CONTROLLER_DEFAULT)
    cloud = _env("JUJU_CLOUD", CLOUD_DEFAULT)

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

    if _env("FRESH_CONTROLLER") == "1":
        try:
            bootstrap_controller(
                controller=controller,
                cloud=cloud,
                juju_cli=juju_cli,
                force_fresh=True,
            )
        except subprocess.CalledProcessError as exc:
            pytest.fail(f"Fresh controller bootstrap failed: {exc.cmd!r}\nstderr: {exc.stderr}")


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
    controller = _env("JUJU_CONTROLLER", CONTROLLER_DEFAULT)
    cloud = _env("JUJU_CLOUD", CLOUD_DEFAULT)
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
        no_model = jubilant.Juju(cli_binary=cli)
        no_model.cli("add-model", model_name, cloud, "-c", controller)
        j = jubilant.Juju(model=model_name, cli_binary=cli)
        try:
            _deploy_with_retry(j, str(charm_path), oci_image)
            j.wait(jubilant.all_active, timeout=300)
            yield j
        finally:
            if not keep:
                no_model.cli(
                    "destroy-model",
                    model_name,
                    "--no-prompt",
                    "--destroy-storage",
                )
        return

    # Default path — let jubilant manage the model.
    with jubilant.temp_model(controller=controller) as j:
        _deploy_with_retry(j, str(charm_path), oci_image)
        j.wait(jubilant.all_active, timeout=300)
        yield j
