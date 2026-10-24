"""Integration tests for US19: Cross-Model Relations.

Tests deploy a second norma instance in a separate model, create a
cross-model offer on the ``calibration-provider`` endpoint, consume it
from the second model, integrate, and verify relation data flows.

``test_cmr_forced_offer_removal_recovers`` force-removes an offer from a
dedicated offering app so a regression cannot wedge the shared app.
"""

import contextlib
import dataclasses
import json
import logging
import os
import time
import uuid

import jubilant
import pytest

from .conftest import (
    CLOUD_DEFAULT,
    CONTROLLER_DEFAULT,
    MODEL_LOGGING_CONFIG,
    _deploy_with_retry,
    _env,
    dump_debug_logs,
)

APP = "juju-norma-k8s"
OFFERER = "norma-cmr-offerer"
logger = logging.getLogger(__name__)


@dataclasses.dataclass
class CmrEnv:
    """The two models used by the CMR tests."""

    model_a: jubilant.Juju
    model_a_name: str
    model_b_name: str
    juju_b: jubilant.Juju
    controller: str
    cli: str


def _load_offers(juju: jubilant.Juju) -> dict:
    raw = juju.cli("offers", "--format", "json")
    if not raw.strip():
        return {}
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def _offer_connections(offers: dict) -> int:
    total = 0
    for info in offers.values():
        if not isinstance(info, dict):
            continue
        connections = info.get("connections")
        if isinstance(connections, list):
            total += len(connections)
        elif isinstance(connections, int):
            total += connections
    return total


def _offer_exists(offers: dict, app: str) -> bool:
    for name, info in offers.items():
        if name == app:
            return True
        if not isinstance(info, dict):
            continue
        if info.get("application") == app or app in str(info.get("offer-url", "")):
            return True
    return False


def _remove_offer(juju: jubilant.Juju, model_name: str, app: str, *, force: bool) -> None:
    """Remove an offer. ``--yes`` skips the 3.6 and 4.0 confirmation prompt.

    The rename of that flag to ``--no-prompt`` is a Juju 4.1 change.
    """
    args = ["remove-offer", f"{model_name}.{app}:calibration-provider", "--yes"]
    if force:
        args.append("--force")
    juju.cli(*args, include_model=False)


def _remote_lifecycle_events(juju: jubilant.Juju, app: str) -> list[dict]:
    """relation-departed / relation-broken ledger rows for a ``remote-*`` app."""
    task = juju.run(f"{app}/leader", "get-event-log", params={"event-filter": "relation"})
    assert task.success, task.results
    events = json.loads(task.results["events"])
    return [
        event
        for event in events
        if event.get("event_name") in {"relation-departed", "relation-broken"}
        and str((event.get("extra") or {}).get("remote-app", "")).startswith("remote-")
    ]


def _wait_for_offerer_relation(juju: jubilant.Juju, app: str) -> None:
    """Poll introspect until the provider relation has propagated."""
    relations = ""
    for _ in range(18):  # ~90s
        task = juju.run(f"{app}/leader", "introspect", params={"sections": "relations"})
        relations = task.results.get("relations", "") if task.success else ""
        if "calibration-provider" in relations:
            return
        time.sleep(5)
    raise AssertionError(f"calibration-provider relation did not propagate to {app}: {relations}")


@pytest.fixture(scope="class")
def cmr_setup(juju: jubilant.Juju, charm_path, oci_image):
    """Deploy norma in a second model once for every test in TestCMR.

    Two function-scoped setups would build and destroy model B twice.
    """
    model_a_name = juju.model.split(":")[-1]
    cli = juju.cli_binary if hasattr(juju, "cli_binary") else "juju"
    model_b_name = f"cmr-{uuid.uuid4().hex[:8]}"
    no_model = jubilant.Juju(cli_binary=cli)
    controller = _env("JUJU_CONTROLLER", CONTROLLER_DEFAULT)
    cloud = _env("JUJU_CLOUD", CLOUD_DEFAULT)
    no_model.cli(
        "add-model",
        model_b_name,
        cloud,
        "-c",
        controller,
        "--config",
        f"logging-config={MODEL_LOGGING_CONFIG}",
        include_model=False,
    )
    juju_b = jubilant.Juju(model=model_b_name, cli_binary=cli)
    _deploy_with_retry(juju_b, str(charm_path), oci_image)
    juju_b.wait(jubilant.all_active, timeout=300)

    env = CmrEnv(
        model_a=juju,
        model_a_name=model_a_name,
        model_b_name=model_b_name,
        juju_b=juju_b,
        controller=controller,
        cli=cli,
    )
    yield env

    # Model B is about to be destroyed. Dump first, whenever the directory
    # is set: a later test can fail after this fixture has already exited.
    dump_debug_logs(cli, controller, os.environ.get("JUJU_DEBUG_LOG_DIR"))
    try:
        offers = _load_offers(juju)
        exists = _offer_exists(offers, APP)
    except jubilant.CLIError:
        logger.warning("could not list offers during CMR teardown", exc_info=True)
        exists = True
    if exists:
        with contextlib.suppress(jubilant.CLIError):
            _remove_offer(juju, model_a_name, APP, force=True)
    no_model.cli(
        "destroy-model",
        model_b_name,
        "--no-prompt",
        "--destroy-storage",
        include_model=False,
    )
    # If a CMR test left the shared unit in error, fail that test here
    # rather than letting the next test inherit the broken unit.
    juju.wait(
        lambda status: jubilant.all_active(status, APP),
        error=lambda status: jubilant.any_error(status, APP),
        timeout=300,
    )


class TestCMR:
    """US19: Cross-model relation offer/consume cycle."""

    def _offer(self, env: CmrEnv) -> None:
        """Create a CMR offer from model A's calibration-provider."""
        env.model_a.cli(
            "offer",
            f"{env.model_a_name}.{APP}:calibration-provider",
            include_model=False,
        )

    def _consume_and_integrate(self, env: CmrEnv) -> None:
        """Consume the offer in model B and integrate."""
        # Use an alias — model B already has a local app with the same name.
        env.juju_b.cli(
            "consume",
            f"{env.model_a_name}.{APP}",
            "remote-norma",
            include_model=False,
        )
        env.juju_b.cli(
            "integrate",
            "remote-norma:calibration-provider",
            f"{APP}:calibration-requirer",
        )

    def test_cmr_offer_consume_integrate(self, cmr_setup: CmrEnv):
        """Full CMR cycle in ONE test: offer -> show-offer -> consume -> integrate
        -> verify relation + cross-model data flow -> remove the relation and the offer.

        The model-B setup is class-scoped so this teardown does not pay for a
        second deploy. ``destroy-model`` of a CAAS model is slow on K8s.
        """
        env = cmr_setup
        # US19 offer: create + verify via show-offer.
        self._offer(env)
        result = env.model_a.cli(
            "show-offer",
            f"{env.model_a_name}.{APP}",
            include_model=False,
        )
        assert "calibration-provider" in result

        # Consume + integrate from model B; verify the relation exists.
        self._consume_and_integrate(env)
        env.juju_b.wait(jubilant.all_active, timeout=120)
        status = env.juju_b.status()
        app_relations = status.apps[APP].relations
        assert any(
            "calibration" in iface
            for rels in app_relations.values()
            for rel in (rels if isinstance(rels, list) else [rels])
            for iface in ([rel.interface] if hasattr(rel, "interface") else [str(rel)])
        ), f"Expected calibration relation, got: {app_relations}"

        _wait_for_offerer_relation(env.model_a, APP)

        # Tear the relation down in the test body. all_active can pass before
        # any removal hook has fired, so wait until the relation is actually gone.
        env.juju_b.remove_relation(
            "remote-norma:calibration-provider",
            f"{APP}:calibration-requirer",
        )
        deadline = time.monotonic() + 300
        relations: dict = {}
        offers: dict = {}
        while True:
            status = env.model_a.status()
            relations = status.apps[APP].relations
            provider_gone = not (relations.get("calibration-provider") or [])
            offers = _load_offers(env.model_a)
            if provider_gone and _offer_connections(offers) == 0:
                break
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"CMR relation still up: relations={relations!r} offers={offers!r}"
                )
            time.sleep(5)
        env.model_a.wait(
            lambda status: jubilant.all_active(status, APP),
            error=lambda status: jubilant.any_error(status, APP),
            timeout=300,
        )

        env.juju_b.cli("remove-saas", "remote-norma")
        _remove_offer(env.model_a, env.model_a_name, APP, force=False)

        status = env.model_a.status()
        unit = status.apps[APP].units[f"{APP}/0"]
        assert unit.workload_status.current == "active"

        events = _remote_lifecycle_events(env.model_a, APP)
        names = {event["event_name"] for event in events}
        assert "relation-departed" in names, events
        assert "relation-broken" in names, events

    def test_cmr_forced_offer_removal_recovers(self, cmr_setup: CmrEnv, charm_path, oci_image):
        """``remove-offer --force`` must leave the offering unit active.

        The offerer is a separate application. A regression here must not wedge
        the shared ``juju-norma-k8s`` app that the rest of the suite uses.
        On 3.6 the hook sequence can differ, so either relation-departed or
        relation-broken for the remote app is enough.
        """
        env = cmr_setup
        try:
            _deploy_with_retry(env.model_a, str(charm_path), oci_image, app=OFFERER)
            env.model_a.wait(
                lambda status: jubilant.all_active(status, OFFERER),
                error=lambda status: jubilant.any_error(status, OFFERER),
                timeout=300,
            )
            env.model_a.cli(
                "offer",
                f"{env.model_a_name}.{OFFERER}:calibration-provider",
                include_model=False,
            )
            env.juju_b.cli(
                "consume",
                f"{env.model_a_name}.{OFFERER}",
                "remote-offerer",
                include_model=False,
            )
            env.juju_b.cli(
                "integrate",
                "remote-offerer:calibration-provider",
                f"{APP}:calibration-requirer",
            )
            _wait_for_offerer_relation(env.model_a, OFFERER)

            _remove_offer(env.model_a, env.model_a_name, OFFERER, force=True)
            env.model_a.wait(
                lambda status: jubilant.all_active(status, OFFERER),
                error=lambda status: jubilant.any_error(status, OFFERER),
                timeout=300,
            )
            status = env.model_a.status()
            unit = status.apps[OFFERER].units[f"{OFFERER}/0"]
            assert unit.workload_status.current == "active"
            events = _remote_lifecycle_events(env.model_a, OFFERER)
            assert events, "expected relation-departed or relation-broken for the remote app"

            env.juju_b.wait(
                lambda status: jubilant.all_active(status, APP),
                error=lambda status: jubilant.any_error(status, APP),
                timeout=300,
            )
        finally:
            # Drop the offer first when the test failed before remove-offer,
            # or remove-application can stall on a still-consumed offer.
            with contextlib.suppress(jubilant.CLIError):
                _remove_offer(env.model_a, env.model_a_name, OFFERER, force=True)
            with contextlib.suppress(jubilant.CLIError):
                env.model_a.cli(
                    "remove-application",
                    OFFERER,
                    "--force",
                    "--no-wait",
                    "--no-prompt",
                )
            with contextlib.suppress(jubilant.CLIError):
                env.juju_b.cli("remove-saas", "remote-offerer")
