"""Idempotent environment setup for integration tests.

Installs microk8s + juju snaps and bootstraps a controller when
``SETUP_ENVIRONMENT=1`` is set.  Pure subprocess orchestration — no
pytest or jubilant dependency so it can also be used as a standalone
script.
"""

import getpass
import logging
import subprocess

logger = logging.getLogger(__name__)

SNAP_TIMEOUT = 300  # seconds
BOOTSTRAP_TIMEOUT = 1200  # CI runners are slow; bootstrap pulls controller images


class SetupError(Exception):
    """Unrecoverable environment setup failure."""


def _run(cmd: list[str], *, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess:
    logger.info("$ %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check)


# ------------------------------------------------------------------
# Snap helpers
# ------------------------------------------------------------------


def is_snap_installed(name: str) -> bool:
    """Return True if the snap *name* is installed."""
    result = _run(["snap", "list", name], check=False)
    return result.returncode == 0


def install_snap(name: str, channel: str, *, classic: bool = True) -> None:
    """Install a snap if it is not already present."""
    if is_snap_installed(name):
        logger.info("snap %s already installed", name)
        return
    cmd = ["sudo", "snap", "install", name, "--channel", channel]
    if classic:
        cmd.append("--classic")
    _run(cmd, timeout=SNAP_TIMEOUT)
    logger.info("snap %s installed from %s", name, channel)


# ------------------------------------------------------------------
# MicroK8s
# ------------------------------------------------------------------


def _ensure_microk8s_group() -> None:
    """Add the current user to snap_microk8s group (strictly confined)."""
    user = getpass.getuser()
    _run(["sudo", "usermod", "-a", "-G", "snap_microk8s", user])
    logger.info("added %s to snap_microk8s group", user)


def ensure_microk8s(channel: str = "1.34-strict/stable") -> None:
    """Install microk8s and enable required addons."""
    install_snap("microk8s", channel, classic=False)
    _ensure_microk8s_group()
    _run(["sudo", "microk8s", "status", "--wait-ready"], timeout=SNAP_TIMEOUT)
    for addon in ("dns", "hostpath-storage", "registry"):
        _run(["sudo", "microk8s", "enable", addon], timeout=SNAP_TIMEOUT)
    logger.info("microk8s ready with addons")


# ------------------------------------------------------------------
# Juju controller
# ------------------------------------------------------------------


def is_controller_bootstrapped(controller: str, juju_cli: str = "juju") -> bool:
    """Return True if *controller* already exists."""
    result = _run([juju_cli, "show-controller", controller], check=False)
    return result.returncode == 0


def _register_microk8s_cloud(juju_cli: str = "juju") -> None:
    """Register microk8s as a k8s cloud in juju via kubeconfig.

    Uses ``sudo microk8s config`` piped into ``juju add-k8s`` so juju
    only needs the kubeconfig, not direct microk8s snap access.
    """
    # "microk8s" is a built-in cloud name; use a distinct name.
    cloud_name = "mk8s"
    result = _run([juju_cli, "clouds", "--format", "json"], check=False)
    if result.returncode == 0 and cloud_name in result.stdout:
        logger.info("%s cloud already registered", cloud_name)
        return cloud_name
    # Pipe kubeconfig from sudo microk8s config into juju add-k8s.
    config = _run(["sudo", "microk8s", "config"], timeout=SNAP_TIMEOUT)
    proc = subprocess.run(
        [juju_cli, "add-k8s", cloud_name, "--client"],
        input=config.stdout,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    logger.info("%s cloud registered: %s", cloud_name, proc.stdout.strip())
    return cloud_name


def destroy_controller(controller: str, juju_cli: str = "juju") -> None:
    """Destroy a Juju controller and all its models."""
    if not is_controller_bootstrapped(controller, juju_cli):
        logger.info("controller %s does not exist, nothing to destroy", controller)
        return
    logger.info("destroying controller %s", controller)
    subprocess.run(
        [
            juju_cli,
            "destroy-controller",
            controller,
            "--destroy-all-models",
            "--no-prompt",
            "--destroy-storage",
        ],
        timeout=BOOTSTRAP_TIMEOUT,
        check=True,
    )
    logger.info("controller %s destroyed", controller)


def bootstrap_controller(
    controller: str = "microk8s-localhost",
    cloud: str | None = None,
    juju_cli: str = "juju",
    *,
    force_fresh: bool = False,
) -> None:
    """Bootstrap a Juju controller on microk8s.

    Args:
        controller: Controller name.
        cloud: Cloud name. If None, registers microk8s via add-k8s.
        juju_cli: Path to juju binary.
        force_fresh: If True, destroy existing controller first.
    """
    if force_fresh:
        destroy_controller(controller, juju_cli)
    elif is_controller_bootstrapped(controller, juju_cli):
        logger.info("controller %s already bootstrapped", controller)
        return
    cloud_name = cloud or _register_microk8s_cloud(juju_cli)
    # Stream output instead of capturing — bootstrap is long-running and
    # we want to see progress in CI logs.
    logger.info("$ %s bootstrap %s %s", juju_cli, cloud_name, controller)
    subprocess.run(
        [juju_cli, "bootstrap", cloud_name, controller],
        timeout=BOOTSTRAP_TIMEOUT,
        check=True,
    )
    logger.info("controller %s bootstrapped", controller)


# ------------------------------------------------------------------
# Top-level orchestrator
# ------------------------------------------------------------------


def check_prerequisites(juju_cli: str = "juju") -> list[str]:
    """Return a list of missing prerequisites (empty = all OK)."""
    missing = []
    if not is_snap_installed("microk8s"):
        missing.append("microk8s snap")
    result = _run([juju_cli, "version"], check=False)
    if result.returncode != 0:
        missing.append(f"juju CLI ({juju_cli})")
    return missing


def ensure_environment(
    *,
    juju_channel: str = "3.6/stable",
    microk8s_channel: str = "1.34-strict/stable",
    controller: str = "microk8s-localhost",
    juju_cli: str = "juju",
) -> str:
    """Set up the full integration test environment.

    Returns the effective juju CLI path.
    """
    try:
        ensure_microk8s(microk8s_channel)
        install_snap("juju", juju_channel, classic=True)
        bootstrap_controller(controller, juju_cli)
    except subprocess.CalledProcessError as exc:
        raise SetupError(
            f"Command failed: {exc.cmd!r}\nstdout: {exc.stdout}\nstderr: {exc.stderr}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SetupError(f"Command timed out: {exc.cmd!r}") from exc
    return juju_cli
