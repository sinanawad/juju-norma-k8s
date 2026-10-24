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
import sys
import time
import uuid

import jubilant
import pytest

from .conftest import (
    CLOUD_DEFAULT,
    CONTROLLER_DEFAULT,
    JUJU_4,
    MODEL_LOGGING_CONFIG,
    _deploy_with_retry,
    _env,
    dump_debug_logs,
)

APP = "juju-norma-k8s"
OFFERER = "norma-cmr-offerer"
_ENDPOINT = "calibration-provider"
logger = logging.getLogger(__name__)


class OfferNotFoundError(Exception):
    """``juju offers`` has no offer for the requested application."""


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


def _offer_name(raw: str) -> str:
    """Offer name from a ``juju offers`` key or offer URL.

    ``admin/model.offer`` and ``model.offer`` both yield ``offer``.
    """
    tail = str(raw).rsplit("/", 1)[-1]
    if "." in tail:
        return tail.rsplit(".", 1)[-1]
    return tail


def _offer_for_app(offers: dict, app: str) -> tuple[str, dict] | None:
    """Return the offers entry for ``app``, preferring the calibration endpoint."""
    matches: list[tuple[str, dict]] = []
    for name, info in offers.items():
        if not isinstance(info, dict):
            continue
        if info.get("application") == app or _offer_name(name) == app:
            matches.append((str(name), info))
    if not matches:
        return None
    for name, info in matches:
        endpoints = info.get("endpoints")
        if isinstance(endpoints, dict) and _ENDPOINT in endpoints:
            return name, info
    return matches[0]


def _offer_target(name: str, info: dict, model_name: str) -> str:
    """Offer URL or ``<model>.<offer-name>`` for show-offer, consume, and remove-offer.

    ``juju offer`` takes ``<model>.<app>:<endpoint>``. ``remove-offer`` does not:
    it takes the offer URL (``admin/<model>.<offer>`` or ``<model>.<offer>``).
    """
    url = str(info.get("offer-url") or "").strip()
    if url:
        return url
    if "/" in name:
        return name
    if "." in name:
        return name
    return f"{model_name}.{_offer_name(name)}"


def _offer_exists(offers: dict, app: str) -> bool:
    return _offer_for_app(offers, app) is not None


def _read_offer_target(juju: jubilant.Juju, app: str, model_name: str) -> str:
    """Read the offer URL back from ``juju offers``."""
    found = _offer_for_app(_load_offers(juju), app)
    if found is None:
        raise OfferNotFoundError(app)
    name, info = found
    return _offer_target(name, info, model_name)


def _remove_offer_url(juju: jubilant.Juju, offer_url: str, *, force: bool) -> None:
    """Remove an offer. ``--yes`` skips the 3.6 and 4.0 confirmation prompt.

    The rename of that flag to ``--no-prompt`` is a Juju 4.1 change.
    ``offer_url`` is the offer URL or ``<model>.<offer-name>``, not
    ``<model>.<app>:<endpoint>``.
    """
    args = ["remove-offer", offer_url, "--yes"]
    if force:
        args.append("--force")
    juju.cli(*args, include_model=False)


def _remove_offer(juju: jubilant.Juju, model_name: str, app: str, *, force: bool) -> None:
    """Remove whatever offer ``juju offers`` currently has for ``app``."""
    _remove_offer_url(juju, _read_offer_target(juju, app, model_name), force=force)


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


def _error_summary(juju: jubilant.Juju, app: str) -> str | None:
    """Workload text when ``app`` is in error, otherwise None.

    A status failure is not treated as error: the caller keeps polling.
    """
    try:
        status = juju.status()
    except Exception:
        logger.warning("status failed while polling %s", app, exc_info=True)
        return None
    if not jubilant.any_error(status, app) or app not in status.apps:
        return None
    app_status = status.apps[app]
    parts = [f"app={app_status.app_status.current}: {app_status.app_status.message}"]
    for unit_name, unit in app_status.units.items():
        parts.append(f"{unit_name}={unit.workload_status.current}: {unit.workload_status.message}")
    return "; ".join(parts)


def _raise_if_in_error(juju: jubilant.Juju, app: str, reason: str) -> None:
    summary = _error_summary(juju, app)
    if summary is not None:
        raise AssertionError(f"{app} is in error {reason}: {summary}")


def _await_remote_lifecycle_events(
    juju: jubilant.Juju, app: str, timeout: float = 120
) -> list[dict]:
    """Poll until a remote departure hook is in the ledger.

    ``all_active`` can succeed before relation-departed or relation-broken
    has run. A failed ``get-event-log`` while that hook is in progress is
    retried until the timeout. An offerer already in error fails immediately.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            events = _remote_lifecycle_events(juju, app)
        except Exception as exc:
            summary = _error_summary(juju, app)
            if summary is not None:
                raise AssertionError(
                    f"{app} is in error while reading the event log: {summary}"
                ) from exc
            logger.warning("event log not readable yet on %s", app, exc_info=True)
            events = []
        if events:
            return events
        _raise_if_in_error(juju, app, "while waiting for a departure hook")
        if time.monotonic() > deadline:
            raise AssertionError(
                f"expected relation-departed or relation-broken for the remote app on {app}"
            )
        time.sleep(5)


def _wait_until_provider_relation_gone(
    juju: jubilant.Juju, app: str, timeout: float = 300
) -> None:
    """Poll until ``calibration-provider`` is gone. An error unit fails immediately."""
    deadline = time.monotonic() + timeout
    relations: dict = {}
    while True:
        try:
            status = juju.status()
        except Exception:
            logger.warning("status failed while waiting for %s relation", app, exc_info=True)
            status = None
        if status is not None and app in status.apps:
            _raise_if_in_error(juju, app, "before the offer relation departed")
            relations = status.apps[app].relations
            if not (relations.get(_ENDPOINT) or []):
                return
        if time.monotonic() > deadline:
            raise AssertionError(f"{_ENDPOINT} relation still present on {app}: {relations!r}")
        time.sleep(5)


def _provider_has_remote_unit(relations: str) -> bool:
    """True when introspect shows calibration-provider with a remote unit."""
    try:
        payload = json.loads(relations) if relations else {}
    except json.JSONDecodeError:
        return False
    providers = payload.get("calibration-provider") if isinstance(payload, dict) else None
    if not isinstance(providers, list):
        return False
    return any(isinstance(rel, dict) and rel.get("remote-units") for rel in providers)


def _wait_for_offerer_relation(juju: jubilant.Juju, app: str) -> None:
    """Poll introspect until the provider relation has a remote unit."""
    relations = ""
    for _ in range(18):  # ~90s
        task = juju.run(f"{app}/leader", "introspect", params={"sections": "relations"})
        relations = task.results.get("relations", "") if task.success else ""
        if _provider_has_remote_unit(relations):
            return
        time.sleep(5)
    raise AssertionError(
        f"calibration-provider relation with a remote unit did not propagate to {app}: {relations}"
    )


def _wait_until_app_gone(juju: jubilant.Juju, app: str, timeout: float = 300) -> None:
    """Poll until ``app`` has left the model.

    ``remove-application --no-wait`` returns while the app is still dying.
    Status failures and an error status are ignored; only absence counts.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            if app not in juju.status().apps:
                return
        except Exception:
            logger.warning("status failed while waiting for %s to leave", app, exc_info=True)
        if time.monotonic() > deadline:
            raise AssertionError(f"{app} still present {timeout:.0f}s after removal")
        time.sleep(5)


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
        with contextlib.suppress(jubilant.CLIError, OfferNotFoundError):
            _remove_offer(juju, model_a_name, APP, force=True)
    no_model.cli(
        "destroy-model",
        model_b_name,
        "--no-prompt",
        "--destroy-storage",
        include_model=False,
    )
    # The forced-removal test removes its offerer with --no-wait. Re-check
    # here so a unit still dying cannot fail the next test. A failure to
    # observe that departure must not skip the shared-app check below.
    gone_error: Exception | None = None
    try:
        _wait_until_app_gone(juju, OFFERER)
    except Exception as exc:
        logger.warning("offerer still present during CMR teardown", exc_info=True)
        gone_error = exc
    # If a CMR test left the shared unit in error, fail that test here
    # rather than letting the next test inherit the broken unit.
    juju.wait(
        lambda status: jubilant.all_active(status, APP),
        error=lambda status: jubilant.any_error(status, APP),
        timeout=300,
    )
    if gone_error is not None:
        raise gone_error


class TestCMR:
    """US19: Cross-model relation offer/consume cycle."""

    def _create_offer(self, env: CmrEnv, app: str) -> str:
        """Offer ``app``'s calibration-provider and return the offer URL.

        The offer command takes ``<model>.<app>:<endpoint>``. The URL comes
        back from ``juju offers``, which is what consume and remove-offer take.
        """
        env.model_a.cli(
            "offer",
            f"{env.model_a_name}.{app}:{_ENDPOINT}",
            include_model=False,
        )
        return _read_offer_target(env.model_a, app, env.model_a_name)

    def _consume_and_integrate(self, env: CmrEnv, offer_url: str, alias: str) -> None:
        """Consume ``offer_url`` in model B under ``alias`` and integrate."""
        # Use an alias — model B already has a local app with the same name.
        env.juju_b.cli(
            "consume",
            offer_url,
            alias,
            include_model=False,
        )
        env.juju_b.cli(
            "integrate",
            f"{alias}:{_ENDPOINT}",
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
        offer_url = self._create_offer(env, APP)
        result = env.model_a.cli("show-offer", offer_url, include_model=False)
        assert "calibration-provider" in result

        # Consume + integrate from model B; verify the relation exists.
        self._consume_and_integrate(env, offer_url, "remote-norma")
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
            provider_gone = not (relations.get(_ENDPOINT) or [])
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
        _remove_offer_url(env.model_a, offer_url, force=False)

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
        On 4.0 the calibration-provider relation must disappear. On 3.6 the
        hook sequence can differ, so either relation-departed or
        relation-broken for the remote app is enough.
        """
        env = cmr_setup
        offer_url: str | None = None
        try:
            _deploy_with_retry(env.model_a, str(charm_path), oci_image, app=OFFERER)
            env.model_a.wait(
                lambda status: jubilant.all_active(status, OFFERER),
                error=lambda status: jubilant.any_error(status, OFFERER),
                timeout=300,
            )
            offer_url = self._create_offer(env, OFFERER)
            self._consume_and_integrate(env, offer_url, "remote-offerer")
            _wait_for_offerer_relation(env.model_a, OFFERER)

            _remove_offer_url(env.model_a, offer_url, force=True)
            # Hooks can still be queued after the offer is gone. On 4.0 the
            # relation itself must leave; 3.6 may only record one of the two
            # departure hooks. Then require the unit to stay active.
            if JUJU_4:
                _wait_until_provider_relation_gone(env.model_a, OFFERER)
            else:
                _await_remote_lifecycle_events(env.model_a, OFFERER, timeout=120)
            env.model_a.wait(
                lambda status: jubilant.all_active(status, OFFERER),
                error=lambda status: jubilant.any_error(status, OFFERER),
                successes=3,
                timeout=300,
            )

            env.juju_b.wait(
                lambda status: jubilant.all_active(status, APP),
                error=lambda status: jubilant.any_error(status, APP),
                timeout=300,
            )
        finally:
            # Drop the offer first when the test failed before remove-offer,
            # or remove-application can stall on a still-consumed offer.
            # remove-saas runs before the gone-wait so a slow removal cannot
            # skip it or replace the test's own exception.
            with contextlib.suppress(jubilant.CLIError, OfferNotFoundError):
                if offer_url is not None:
                    _remove_offer_url(env.model_a, offer_url, force=True)
                else:
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
            pending = sys.exc_info()[1]
            try:
                _wait_until_app_gone(env.model_a, OFFERER)
            except Exception:
                if pending is None:
                    raise
                logger.warning(
                    "offerer still present after the test failed",
                    exc_info=True,
                )
