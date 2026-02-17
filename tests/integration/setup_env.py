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
BOOTSTRAP_TIMEOUT = 600


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


def ensure_microk8s(channel: str = "1.28-strict/stable") -> None:
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


def bootstrap_controller(
    controller: str = "microk8s-localhost",
    juju_cli: str = "juju",
) -> None:
    """Bootstrap a Juju controller on microk8s if it does not exist.

    Uses ``sg snap_microk8s`` so the juju process can read the strictly
    confined microk8s credentials without requiring a re-login.
    """
    if is_controller_bootstrapped(controller, juju_cli):
        logger.info("controller %s already bootstrapped", controller)
        return
    _run(
        ["sg", "snap_microk8s", "-c", f"{juju_cli} bootstrap microk8s {controller}"],
        timeout=BOOTSTRAP_TIMEOUT,
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
    microk8s_channel: str = "1.28-strict/stable",
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
