#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Norma K8s calibration charm — exercises all Juju K8s charm features.

This charm follows the holistic reconciler architecture: all lifecycle events
route to a single _reconcile() method. Action handlers are dedicated.
"""

import datetime
import json
import logging
import re

import ops

import norma

logger = logging.getLogger(__name__)


def _event_to_kebab(event: ops.EventBase) -> str:
    """Convert an event class name to kebab-case for the event ledger."""
    name = type(event).__name__
    # Remove 'Event' suffix if present
    if name.endswith("Event"):
        name = name[: -len("Event")]
    # CamelCase to kebab-case
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", name).lower()


class NormaK8sCharm(ops.CharmBase):
    """Main charm class for norma-k8s calibration charm."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        # Event ledger: persisted to charm container filesystem, resets on pod restart
        self._event_ledger: list[dict] = norma.read_event_ledger()

        # Forced status from set-status action (cleared on next successful reconcile)
        self._forced_status: ops.StatusBase | None = None

        # Deferral arming flag for US20
        self._defer_armed: bool = False

        # --- Lifecycle events → _reconcile ---
        self.framework.observe(self.on.install, self._reconcile)
        self.framework.observe(self.on.start, self._reconcile)
        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.leader_elected, self._reconcile)
        self.framework.observe(self.on.leader_settings_changed, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._reconcile)
        self.framework.observe(self.on.update_status, self._reconcile)
        self.framework.observe(self.on.secret_changed, self._reconcile)

        # --- Pebble ready events ---
        self.framework.observe(self.on.norma_pebble_ready, self._reconcile)
        self.framework.observe(self.on.norma_secondary_pebble_ready, self._reconcile)

        # --- Dedicated handlers (permitted by constitution) ---
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on.remove, self._on_remove)

        # --- Status collection ---
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)
        self.framework.observe(self.on.collect_app_status, self._on_collect_app_status)

        # --- Actions ---
        self.framework.observe(self.on.get_event_log_action, self._on_get_event_log_action)
        self.framework.observe(self.on.run_check_action, self._on_run_check_action)
        self.framework.observe(self.on.get_config_action, self._on_get_config_action)

    # ------------------------------------------------------------------ #
    #  Core reconciler                                                    #
    # ------------------------------------------------------------------ #

    def _reconcile(self, event: ops.EventBase) -> None:
        """Holistic reconciler — single entry point for all lifecycle events."""
        event_name = _event_to_kebab(event)
        extra: dict[str, str] = {}

        # Detect re-emitted (deferred) events
        if getattr(event, "deferred", False):
            extra["re-emitted"] = "true"

        self._log_event(event_name, extra)

        # Check primary container connectivity
        container = self.unit.get_container(norma.CONTAINER_NAME)
        if not container.can_connect():
            return

        # Build and apply Pebble layer
        port = int(self.config.get("calibration-int", norma.DEFAULT_PORT))
        version = self._get_charm_version()

        # Validate config
        config_dict = {
            "calibration_string": self.config.get("calibration-string", "default"),
            "calibration_int": port,
            "calibration_float": float(self.config.get("calibration-float", 1.0)),
            "calibration_bool": self.config.get("calibration-bool", True),
        }
        valid, error_msg = norma.validate_config(config_dict)
        if not valid:
            self._forced_status = ops.BlockedStatus(error_msg)
            return

        # Resolve secret config if set
        secret_uri = self.config.get("calibration-secret")
        if secret_uri:
            try:
                secret = self.model.get_secret(id=secret_uri)
                secret.get_content(refresh=True)
            except ops.SecretNotFoundError:
                self._forced_status = ops.BlockedStatus(f"Secret not found: {secret_uri}")
                return
            except ops.ModelError as e:
                self._forced_status = ops.BlockedStatus(f"Secret error: {e}")
                return

        # Apply Pebble layer and replan
        try:
            layer = norma.build_pebble_layer(norma.CONTAINER_NAME, port, version)
            container.add_layer(norma.CONTAINER_NAME, layer, combine=True)
            container.replan()
        except ops.pebble.ConnectionError:
            logger.warning("Pebble connection lost during layer apply")
            return

        # Set workload version
        try:
            process = container.exec([norma.BINARY_PATH, "--check"])
            process.wait()
            self.unit.set_workload_version(version)
        except (ops.pebble.ExecError, ops.pebble.ConnectionError):
            pass

        # Open workload port
        self.unit.set_ports(ops.Port("tcp", port))

        # Successful reconcile — clear any forced status
        self._forced_status = None

    # ------------------------------------------------------------------ #
    #  Dedicated handlers                                                 #
    # ------------------------------------------------------------------ #

    def _on_stop(self, event: ops.StopEvent) -> None:
        self._log_event("stop")

    def _on_remove(self, event: ops.RemoveEvent) -> None:
        self._log_event("remove")

    # ------------------------------------------------------------------ #
    #  Status collection                                                  #
    # ------------------------------------------------------------------ #

    def _on_collect_unit_status(self, event: ops.CollectStatusEvent) -> None:
        if self._forced_status:
            event.add_status(self._forced_status)
            return

        container = self.unit.get_container(norma.CONTAINER_NAME)
        if not container.can_connect():
            event.add_status(ops.WaitingStatus("Waiting for Pebble"))
            return

        event.add_status(ops.ActiveStatus())

    def _on_collect_app_status(self, event: ops.CollectStatusEvent) -> None:
        if not self.unit.is_leader():
            return
        if self._forced_status:
            event.add_status(self._forced_status)
            return
        event.add_status(ops.ActiveStatus())

    # ------------------------------------------------------------------ #
    #  Actions                                                            #
    # ------------------------------------------------------------------ #

    def _on_get_event_log_action(self, event: ops.ActionEvent) -> None:
        """Return the event ledger, optionally filtered."""
        event.log("Retrieving event ledger")
        limit = event.params.get("limit", 0)
        event_filter = event.params.get("event-filter", "")

        entries = self._event_ledger
        if event_filter:
            entries = [e for e in entries if event_filter in e["event_name"]]
        if limit > 0:
            entries = entries[-limit:]

        event.set_results(
            {
                "events": json.dumps(entries),
                "count": str(len(entries)),
                "unit": self.unit.name,
            }
        )

    def _on_get_config_action(self, event: ops.ActionEvent) -> None:
        """Return all current configuration values."""
        event.log("Retrieving configuration")
        event.set_results(
            {
                "calibration-string": str(self.config.get("calibration-string", "default")),
                "calibration-int": str(self.config.get("calibration-int", norma.DEFAULT_PORT)),
                "calibration-float": str(self.config.get("calibration-float", 1.0)),
                "calibration-bool": str(self.config.get("calibration-bool", True)),
                "calibration-secret": (
                    "set" if self.config.get("calibration-secret") else "unset"
                ),
            }
        )

    def _on_run_check_action(self, event: ops.ActionEvent) -> None:
        """Validate a specific charm capability and return pass/fail."""
        event.log("Running capability check")
        check = event.params.get("check", "")

        if check == "pebble":
            container = self.unit.get_container(norma.CONTAINER_NAME)
            if not container.can_connect():
                event.set_results(
                    {"check": "pebble", "result": "fail", "details": "Container not connected"}
                )
                return
            try:
                svc = container.get_service(norma.CONTAINER_NAME)
                if svc.is_running():
                    event.set_results(
                        {"check": "pebble", "result": "pass", "details": "Service running"}
                    )
                else:
                    event.set_results(
                        {"check": "pebble", "result": "fail", "details": "Service not running"}
                    )
            except ops.pebble.ConnectionError:
                event.set_results(
                    {"check": "pebble", "result": "fail", "details": "Connection lost"}
                )
            except (ops.ModelError, ops.pebble.APIError):
                event.set_results(
                    {"check": "pebble", "result": "fail", "details": "Service not found"}
                )
        else:
            event.set_results(
                {"check": check, "result": "fail", "details": f"Unknown check: {check}"}
            )

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _log_event(self, event_name: str, extra: dict[str, str] | None = None) -> None:
        """Append an event to the event ledger and persist to disk."""
        self._event_ledger.append(
            {
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "event_name": event_name,
                "unit_name": self.unit.name,
                "extra": extra or {},
            }
        )
        norma.write_event_ledger(self._event_ledger)
        logger.info("Event: %s on %s", event_name, self.unit.name)

    def _get_charm_version(self) -> str:
        """Read charm version from the version file written by charmcraft."""
        try:
            return (self.charm_dir / "version").read_text().strip()
        except FileNotFoundError:
            return "dev"


if __name__ == "__main__":  # pragma: nocover
    ops.main(NormaK8sCharm)
