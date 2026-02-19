#!/usr/bin/env python3
"""Norma K8s calibration charm — exercises all Juju K8s charm features.

This charm follows the holistic reconciler architecture: all lifecycle events
route to a single _reconcile() method. Action handlers are dedicated.
"""

import contextlib
import datetime
import json
import logging
import os
import re
import secrets

import ops
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider

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


REPORT_SECTIONS = (
    "identity",
    "version",
    "leadership",
    "config",
    "event-ledger",
    "relations",
    "storage",
    "containers",
    "secrets",
)


class NormaK8sCharm(ops.CharmBase):
    """Main charm class for norma-k8s calibration charm."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        # Event ledger: persisted to charm container filesystem, resets on pod restart
        self._event_ledger: list[dict] = norma.read_event_ledger()

        # Forced status from set-status action (cleared on next successful reconcile)
        self._forced_status: ops.StatusBase | None = None

        # Deferral arming flag for US20 (persisted to disk across dispatches)
        self._defer_armed: bool = norma.read_defer_armed()

        # --- Lifecycle events → _on_defer_gate → _reconcile ---
        self.framework.observe(self.on.install, self._on_defer_gate)
        self.framework.observe(self.on.start, self._on_defer_gate)
        self.framework.observe(self.on.config_changed, self._on_defer_gate)
        self.framework.observe(self.on.leader_elected, self._on_defer_gate)
        self.framework.observe(self.on.leader_settings_changed, self._on_defer_gate)
        self.framework.observe(self.on.upgrade_charm, self._on_defer_gate)
        self.framework.observe(self.on.update_status, self._on_defer_gate)
        self.framework.observe(self.on.secret_changed, self._on_defer_gate)

        # --- Peer relation events → _on_defer_gate → _reconcile ---
        self.framework.observe(self.on.norma_peers_relation_joined, self._on_defer_gate)
        self.framework.observe(self.on.norma_peers_relation_changed, self._on_defer_gate)
        self.framework.observe(self.on.norma_peers_relation_departed, self._on_defer_gate)

        # --- Calibration relation events → _on_defer_gate → _reconcile ---
        for evt in (
            self.on.calibration_provider_relation_created,
            self.on.calibration_provider_relation_joined,
            self.on.calibration_provider_relation_changed,
            self.on.calibration_provider_relation_departed,
            self.on.calibration_provider_relation_broken,
            self.on.calibration_requirer_relation_created,
            self.on.calibration_requirer_relation_joined,
            self.on.calibration_requirer_relation_changed,
            self.on.calibration_requirer_relation_departed,
            self.on.calibration_requirer_relation_broken,
        ):
            self.framework.observe(evt, self._on_defer_gate)

        # --- Pebble / storage events (only when containers are declared) ---
        # Subordinate variants share the principal's pod and have no containers
        # or storage in their metadata — skip container/storage event observers.
        if norma.CONTAINER_NAME in self.meta.containers:
            self.framework.observe(self.on.norma_pebble_ready, self._on_defer_gate)
            self.framework.observe(self.on.norma_pebble_check_failed, self._on_defer_gate)
            self.framework.observe(self.on.norma_pebble_check_recovered, self._on_defer_gate)
        if norma.SECONDARY_CONTAINER in self.meta.containers:
            self.framework.observe(self.on.norma_secondary_pebble_ready, self._on_defer_gate)
        if "data" in self.meta.storages:
            self.framework.observe(self.on.data_storage_attached, self._on_defer_gate)
            self.framework.observe(self.on.data_storage_detaching, self._on_defer_gate)
        if "logs" in self.meta.storages:
            self.framework.observe(self.on.logs_storage_attached, self._on_defer_gate)
            self.framework.observe(self.on.logs_storage_detaching, self._on_defer_gate)

        # --- Dedicated handlers (permitted by constitution) ---
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.secret_rotate, self._on_secret_rotate)
        self.framework.observe(self.on.secret_expired, self._on_secret_expired)
        self.framework.observe(self.on.secret_remove, self._on_secret_remove)

        # --- Status collection ---
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)
        self.framework.observe(self.on.collect_app_status, self._on_collect_app_status)

        # --- Actions ---
        self.framework.observe(self.on.get_event_log_action, self._on_get_event_log_action)
        self.framework.observe(self.on.run_check_action, self._on_run_check_action)
        self.framework.observe(self.on.get_config_action, self._on_get_config_action)
        self.framework.observe(self.on.set_status_action, self._on_set_status_action)
        self.framework.observe(self.on.fail_action_action, self._on_fail_action)
        self.framework.observe(self.on.get_peer_data_action, self._on_get_peer_data_action)
        self.framework.observe(self.on.get_relation_data_action, self._on_get_relation_data_action)
        self.framework.observe(self.on.get_cluster_info_action, self._on_get_cluster_info_action)
        self.framework.observe(self.on.get_secret_info_action, self._on_get_secret_info_action)
        self.framework.observe(self.on.check_storage_action, self._on_check_storage_action)
        self.framework.observe(self.on.toggle_health_action, self._on_toggle_health_action)
        self.framework.observe(self.on.test_pebble_ops_action, self._on_test_pebble_ops_action)
        self.framework.observe(self.on.trigger_notice_action, self._on_trigger_notice_action)
        self.framework.observe(self.on.test_networking_action, self._on_test_networking_action)
        self.framework.observe(self.on.get_version_action, self._on_get_version_action)
        self.framework.observe(self.on.check_security_action, self._on_check_security_action)
        self.framework.observe(self.on.test_defer_action, self._on_test_defer_action)
        self.framework.observe(self.on.introspect_action, self._on_introspect_action)

        # --- Pebble custom notice event → _on_defer_gate → _reconcile ---
        if norma.CONTAINER_NAME in self.meta.containers:
            self.framework.observe(self.on.norma_pebble_custom_notice, self._on_defer_gate)

        # --- COS Observability (US18) ---
        self._metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[
                {
                    "static_configs": [{"targets": [f"*:{norma.DEFAULT_PORT}"]}],
                }
            ],
        )
        self._grafana_dashboard = GrafanaDashboardProvider(self)
        self._log_forwarder = LogForwarder(self, relation_name="log-proxy")

    # ------------------------------------------------------------------ #
    #  US20: Deferral gate (dedicated handler — never inside reconciler)  #
    # ------------------------------------------------------------------ #

    def _on_defer_gate(self, event: ops.EventBase) -> None:
        """Pre-reconcile deferral gate for US20 testing.

        This is a dedicated handler that intercepts events before the reconciler.
        If deferral is armed (via the test-defer action), the event is deferred
        here and never reaches _reconcile(). This keeps event.defer() out of
        the reconciler, satisfying constitutional Principle VII.
        """
        event_name = _event_to_kebab(event)
        # Never defer update-status (high frequency) or relation-broken
        # (re-emission fails because the relation no longer exists).
        skip_defer = event_name in ("update-status", "relation-broken")
        if self._defer_armed and not skip_defer:
            extra: dict[str, str] = {"deferred": "true"}
            self._log_event(event_name, extra)
            event.defer()
            self._defer_armed = False
            norma.write_defer_armed(False)
            return
        self._reconcile(event)

    # ------------------------------------------------------------------ #
    #  Core reconciler                                                    #
    # ------------------------------------------------------------------ #

    def _reconcile(self, event: ops.EventBase) -> None:
        """Holistic reconciler — single entry point for all lifecycle events.

        This method MUST NOT call event.defer(). All deferral logic lives in
        _on_defer_gate() which runs before the reconciler.
        """
        event_name = _event_to_kebab(event)
        extra: dict[str, str] = {}

        # Detect re-emitted (deferred) events
        if getattr(event, "deferred", False):
            extra["re-emitted"] = "true"

        # Capture departing unit identity for relation-departed events
        if isinstance(event, ops.RelationDepartedEvent) and event.departing_unit:
            extra["departing-unit"] = event.departing_unit.name

        # Capture check name for pebble-check-failed/recovered events
        if isinstance(event, (ops.PebbleCheckFailedEvent, ops.PebbleCheckRecoveredEvent)):
            extra["check"] = event.info.name

        # Capture notice key for pebble-custom-notice events
        # Only log the key, not the payload — notice data may contain secrets.
        if isinstance(event, ops.PebbleCustomNoticeEvent):
            extra["notice-key"] = event.notice.key

        # US19: Capture remote app name for relation events (CMR compatibility)
        if isinstance(event, ops.RelationEvent) and event.app:
            extra["remote-app"] = event.app.name

        # US21: Detect resource refresh / pod restart for pebble-ready events
        if isinstance(event, ops.PebbleReadyEvent):
            container_name = event.workload.name
            extra["container"] = container_name
            prior = [
                e
                for e in self._event_ledger
                if e["event_name"] == "pebble-ready"
                and e["extra"].get("container") == container_name
            ]
            if prior:
                extra["trigger"] = "resource-refresh-or-restart"

        self._log_event(event_name, extra)

        # Identify the broken relation (if any) so grant logic skips it
        broken_relation: ops.Relation | None = None
        if (
            isinstance(event, ops.RelationBrokenEvent)
            and event.relation.name == "calibration-provider"
        ):
            broken_relation = event.relation
            # Revoke secret access for the broken relation
            if self.unit.is_leader():
                peer = self.model.get_relation("norma-peers")
                if peer:
                    secret_id = peer.data[self.app].get("secret-id")
                    if secret_id:
                        try:
                            secret = self.model.get_secret(id=secret_id)
                            secret.revoke(event.relation)
                        except ops.SecretNotFoundError:
                            pass

        # Update relation data first — independent of workload readiness
        self._update_relation_data(broken_relation=broken_relation)

        version = self._get_charm_version()

        # Subordinate variants have no containers — skip workload operations
        if norma.CONTAINER_NAME not in self.meta.containers:
            return

        # --- Primary container ---
        container = self.unit.get_container(norma.CONTAINER_NAME)
        if container.can_connect():
            port = int(self.config.get("calibration-int", norma.DEFAULT_PORT))

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
            else:
                # Resolve secret config if set
                secret_ok = True
                secret_uri = self.config.get("calibration-secret")
                if secret_uri:
                    try:
                        secret = self.model.get_secret(id=secret_uri)
                        secret.get_content(refresh=True)
                    except ops.SecretNotFoundError:
                        self._forced_status = ops.BlockedStatus(f"Secret not found: {secret_uri}")
                        secret_ok = False
                    except ops.ModelError as e:
                        self._forced_status = ops.BlockedStatus(f"Secret error: {e}")
                        secret_ok = False

                if secret_ok:
                    # Apply Pebble layer and replan
                    layer_ok = True
                    try:
                        layer = norma.build_pebble_layer(norma.CONTAINER_NAME, port, version)
                        container.add_layer(norma.CONTAINER_NAME, layer, combine=True)
                        container.replan()
                    except ops.pebble.ConnectionError:
                        logger.warning("Pebble connection lost during layer apply")
                        layer_ok = False

                    # Set workload version
                    try:
                        process = container.exec([norma.BINARY_PATH, "--check"])
                        process.wait()
                        self.unit.set_workload_version(version)
                    except (
                        ops.pebble.ExecError,
                        ops.pebble.ConnectionError,
                    ):
                        pass

                    # Open workload port
                    self.unit.set_ports(ops.Port("tcp", port))

                    # Write storage markers
                    for s_name, s_cfg in norma.STORAGE_CONFIG.items():
                        if self.model.storages.get(s_name):
                            s_marker = f"{s_cfg['path']}/{s_cfg['marker']}"
                            try:
                                if not container.exists(s_marker):
                                    marker = json.dumps(
                                        {
                                            "created_by": self.unit.name,
                                            "created_at": datetime.datetime.now(
                                                datetime.UTC
                                            ).isoformat(),
                                            "storage": s_name,
                                            "revision": 1,
                                        }
                                    )
                                    container.push(s_marker, marker, make_dirs=True)
                            except (
                                ops.pebble.ConnectionError,
                                ops.pebble.PathError,
                            ):
                                logger.debug(
                                    "Storage marker write skipped for %s",
                                    s_name,
                                )

                    # Only clear forced status when layer apply succeeded
                    if layer_ok:
                        self._forced_status = None

        # --- Secondary container (US16) ---
        if norma.SECONDARY_CONTAINER not in self.meta.containers:
            return
        secondary = self.unit.get_container(norma.SECONDARY_CONTAINER)
        if secondary.can_connect():
            try:
                secondary_layer = norma.build_secondary_layer(version)
                secondary.add_layer(norma.SECONDARY_CONTAINER, secondary_layer, combine=True)
                secondary.replan()
            except ops.pebble.ConnectionError:
                logger.warning("Pebble connection lost during secondary layer apply")

    # ------------------------------------------------------------------ #
    #  Dedicated handlers                                                 #
    # ------------------------------------------------------------------ #

    def _on_stop(self, event: ops.StopEvent) -> None:
        self._log_event("stop")

    def _on_remove(self, event: ops.RemoveEvent) -> None:
        self._log_event("remove")

    def _on_secret_rotate(self, event: ops.SecretRotateEvent) -> None:
        """Rotate the secret by creating a new revision with fresh content."""
        self._log_event("secret-rotate", {"secret-label": event.secret.label or ""})
        event.secret.set_content({"password": secrets.token_urlsafe(24)})

    def _on_secret_expired(self, event: ops.SecretExpiredEvent) -> None:
        """Handle expired secret revision."""
        self._log_event("secret-expired", {"secret-label": event.secret.label or ""})
        event.secret.remove_revision(event.revision)

    def _on_secret_remove(self, event: ops.SecretRemoveEvent) -> None:
        """Remove obsolete secret revision."""
        self._log_event("secret-remove", {"secret-label": event.secret.label or ""})
        event.secret.remove_revision(event.revision)

    # ------------------------------------------------------------------ #
    #  Status collection                                                  #
    # ------------------------------------------------------------------ #

    def _on_collect_unit_status(self, event: ops.CollectStatusEvent) -> None:
        if self._forced_status:
            event.add_status(self._forced_status)
            return

        # Subordinate variants have no containers — active if not forced
        if norma.CONTAINER_NAME not in self.meta.containers:
            event.add_status(ops.ActiveStatus())
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

    def _on_set_status_action(self, event: ops.ActionEvent) -> None:
        """Force a specific status condition for testing."""
        event.log("Setting forced status")
        status_map: dict[str, type[ops.StatusBase]] = {
            "active": ops.ActiveStatus,
            "blocked": ops.BlockedStatus,
            "waiting": ops.WaitingStatus,
            "maintenance": ops.MaintenanceStatus,
        }
        status_name = event.params.get("status", "")
        message = event.params.get("message", "")
        status_cls = status_map.get(status_name)
        if status_cls is None:
            event.fail(f"Unknown status type: {status_name}")
            return

        previous = type(self._forced_status).__name__ if self._forced_status else "none"
        if status_cls is ops.ActiveStatus:
            self._forced_status = None
        else:
            self._forced_status = status_cls(message)

        event.set_results({"previous-status": previous, "new-status": status_name})

    def _on_fail_action(self, event: ops.ActionEvent) -> None:
        """Intentionally fail to test error reporting."""
        message = event.params.get("message", "Intentional failure for testing")
        event.log(f"Failing action with message: {message}")
        self._log_event("fail-action", {"message": message})
        event.fail(message)

    def _on_get_relation_data_action(self, event: ops.ActionEvent) -> None:
        """Return relation data for a specific endpoint."""
        event.log("Retrieving relation data")
        endpoint = event.params.get("endpoint", "")
        rel_id_filter = event.params.get("relation-id")

        relations = self.model.relations.get(endpoint, [])
        if rel_id_filter is not None:
            relations = [r for r in relations if r.id == rel_id_filter]

        result = []
        for rel in relations:
            app_data = dict(rel.data[self.app]) if self.unit.is_leader() else {}
            units = {}
            units[self.unit.name] = dict(rel.data[self.unit])
            for unit in rel.units:
                units[unit.name] = dict(rel.data[unit])
            result.append({"id": rel.id, "app-data": app_data, "units": units})

        event.set_results({"relations": json.dumps(result)})

    def _on_get_peer_data_action(self, event: ops.ActionEvent) -> None:
        """Return peer relation data from all units."""
        event.log("Retrieving peer relation data")
        peer = self.model.get_relation("norma-peers")
        if not peer:
            event.set_results({"app-data": "{}", "unit-data": "{}"})
            return

        app_data = dict(peer.data[self.app])
        unit_data = {}
        # Include own unit data
        unit_data[self.unit.name] = dict(peer.data[self.unit])
        # Include remote peer units
        for unit in peer.units:
            unit_data[unit.name] = dict(peer.data[unit])

        event.set_results(
            {
                "app-data": json.dumps(app_data),
                "unit-data": json.dumps(unit_data),
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

    def _on_get_secret_info_action(self, event: ops.ActionEvent) -> None:
        """Return info about the app-owned secret."""
        event.log("Retrieving secret info")
        peer = self.model.get_relation("norma-peers")
        if not peer:
            event.set_results({"secret-id": "", "has-content": "false", "rotation": ""})
            return

        secret_id = peer.data[self.app].get("secret-id", "")
        if not secret_id:
            event.set_results({"secret-id": "", "has-content": "false", "rotation": ""})
            return

        try:
            secret = self.model.get_secret(id=secret_id)
            content = secret.get_content(refresh=True)
            has_content = bool(content.get("password"))
        except (ops.SecretNotFoundError, ops.ModelError):
            has_content = False

        event.set_results(
            {
                "secret-id": secret_id,
                "has-content": str(has_content).lower(),
                "rotation": "monthly",
            }
        )

    def _on_check_storage_action(self, event: ops.ActionEvent) -> None:
        """Check storage status and data integrity."""
        storage_name = event.params.get("name", "data")
        storage_cfg = norma.STORAGE_CONFIG.get(storage_name)
        if not storage_cfg:
            event.fail(f"Unknown storage name: {storage_name}")
            return
        if norma.CONTAINER_NAME not in self.meta.containers:
            event.fail("Storage not available (subordinate mode)")
            return

        event.log(f"Checking storage '{storage_name}'")
        container = self.unit.get_container(norma.CONTAINER_NAME)
        storage_path = storage_cfg["path"]
        marker_path = f"{storage_path}/{storage_cfg['marker']}"

        attached = bool(self.model.storages.get(storage_name))
        can_connect = container.can_connect()

        # Check marker file
        marker_exists = False
        marker_content = ""
        if attached and can_connect:
            try:
                marker_exists = container.exists(marker_path)
                if marker_exists:
                    marker_content = container.pull(marker_path).read()
            except (ops.pebble.ConnectionError, ops.pebble.PathError):
                pass

        # Test writability
        writable = False
        if attached and can_connect:
            test_path = f"{storage_path}/.write-test"
            try:
                container.push(test_path, "test", make_dirs=True)
                container.remove_path(test_path)
                writable = True
            except (ops.pebble.ConnectionError, ops.pebble.PathError):
                pass

        event.set_results(
            {
                "attached": str(attached).lower(),
                "mount-point": storage_path,
                "marker-exists": str(marker_exists).lower(),
                "marker-content": marker_content,
                "writable": str(writable).lower(),
            }
        )

    def _on_get_cluster_info_action(self, event: ops.ActionEvent) -> None:
        """Return cluster membership information."""
        event.log("Retrieving cluster info")
        peer = self.model.get_relation("norma-peers")
        all_units = [self.unit.name]
        if peer:
            all_units.extend(sorted(u.name for u in peer.units))

        leader_unit = self.unit.name if self.unit.is_leader() else ""
        if peer and not self.unit.is_leader():
            leader_unit = peer.data[self.app].get("leader-unit", "")

        event.set_results(
            {
                "unit-count": str(len(all_units)),
                "planned-units": str(self.app.planned_units()),
                "leader": leader_unit,
                "is-leader": str(self.unit.is_leader()),
                "units": json.dumps(all_units),
            }
        )

    def _on_toggle_health_action(self, event: ops.ActionEvent) -> None:
        """Toggle the workload health between healthy and unhealthy."""
        event.log("Toggling workload health")
        container_name = event.params.get("container", norma.CONTAINER_NAME)
        if container_name not in self.meta.containers:
            event.fail(f"Container {container_name} not available (subordinate mode)")
            return
        container = self.unit.get_container(container_name)

        if not container.can_connect():
            event.fail(f"Cannot connect to container {container_name}")
            return

        try:
            if container.exists(norma.HEALTH_FLAG_FILE):
                container.remove_path(norma.HEALTH_FLAG_FILE)
                event.set_results({"previous-state": "unhealthy", "new-state": "healthy"})
            else:
                container.push(norma.HEALTH_FLAG_FILE, "unhealthy", make_dirs=True)
                event.set_results({"previous-state": "healthy", "new-state": "unhealthy"})
        except ops.pebble.ConnectionError:
            event.fail(f"Lost connection to container {container_name}")

    def _on_test_pebble_ops_action(self, event: ops.ActionEvent) -> None:
        """Run the full Pebble file/exec/service operations suite."""
        event.log("Running Pebble operations suite")
        container_name = event.params.get("container", norma.CONTAINER_NAME)
        if container_name not in self.meta.containers:
            event.fail(f"Container {container_name} not available (subordinate mode)")
            return
        container = self.unit.get_container(container_name)

        if not container.can_connect():
            event.fail(f"Cannot connect to container {container_name}")
            return

        results: dict[str, str] = {}
        passed = 0
        total = 0

        def _run_op(name: str, fn) -> None:
            nonlocal passed, total
            total += 1
            try:
                fn()
                results[name] = "pass"
                passed += 1
            except (
                ops.pebble.ConnectionError,
                ops.pebble.PathError,
                ops.pebble.APIError,
                ops.pebble.ChangeError,
                ops.pebble.ExecError,
                AssertionError,
            ) as e:
                results[name] = f"fail: {e}"

        # Primary container has /var/lib/norma via storage mount;
        # secondary container only has /tmp writable (bare ROCK).
        base_dir = "/var/lib/norma" if container_name == norma.CONTAINER_NAME else "/tmp"
        test_path = f"{base_dir}/pebble-test.txt"
        test_dir = f"{base_dir}/pebble-test-dir/nested"
        test_content = "pebble-ops-test-data"

        # --- File operations ---
        def op_push():
            container.push(test_path, test_content, make_dirs=True)

        def op_pull():
            content = container.pull(test_path).read()
            assert content == test_content, f"Expected {test_content!r}, got {content!r}"

        def op_make_dir():
            container.make_dir(test_dir, make_parents=True)

        def op_list_files():
            files = container.list_files(base_dir)
            names = [f.name for f in files]
            assert "pebble-test.txt" in names

        def op_exec():
            proc = container.exec([norma.BINARY_PATH, "--check"])
            proc.wait()

        def op_exec_fail():
            try:
                proc = container.exec(["/nonexistent-binary"])
                proc.wait()
                raise AssertionError("Expected error from failing command")
            except (ops.pebble.ExecError, ops.pebble.APIError, ops.pebble.ChangeError):
                pass  # Expected — binary not found or non-zero exit

        def op_remove_path():
            container.remove_path(test_path)
            assert not container.exists(test_path)

        def op_exists():
            # Push a temp file, verify exists, then clean up
            exists_path = f"{base_dir}/exists-test"
            container.push(exists_path, "x", make_dirs=True)
            assert container.exists(exists_path)
            container.remove_path(exists_path)

        # --- Service operations ---
        service_name = container_name

        def op_stop():
            container.stop(service_name)

        def op_get_services():
            svcs = container.get_services()
            assert service_name in svcs

        def op_start():
            container.start(service_name)

        def op_restart():
            container.restart(service_name)

        def op_get_plan():
            plan = container.get_plan()
            assert service_name in plan.services

        _run_op("push", op_push)
        _run_op("pull", op_pull)
        _run_op("make-dir", op_make_dir)
        _run_op("list-files", op_list_files)
        _run_op("exec", op_exec)
        _run_op("exec-fail", op_exec_fail)
        _run_op("remove-path", op_remove_path)
        _run_op("exists", op_exists)
        _run_op("stop", op_stop)
        _run_op("get-services", op_get_services)
        _run_op("start", op_start)
        _run_op("restart", op_restart)
        _run_op("get-plan", op_get_plan)

        # --- Signal operation (FR-028) ---
        def op_send_signal():
            container.send_signal("SIGHUP", service_name)
            svc = container.get_service(service_name)
            assert svc.is_running(), "Service should survive SIGHUP"

        _run_op("send-signal", op_send_signal)

        # Cleanup test dir
        with contextlib.suppress(ops.pebble.PathError):
            container.remove_path(f"{base_dir}/pebble-test-dir", recursive=True)

        results["summary"] = f"{passed}/{total} passed"
        event.set_results(results)

    def _on_trigger_notice_action(self, event: ops.ActionEvent) -> None:
        """Send a Pebble custom notice from inside the workload container."""
        event.log("Triggering custom notice")
        if norma.CONTAINER_NAME not in self.meta.containers:
            event.fail("Container not available (subordinate mode)")
            return
        container = self.unit.get_container(norma.CONTAINER_NAME)

        if not container.can_connect():
            event.fail("Cannot connect to container")
            return

        key = event.params.get("key", "norma.dev/calibration-test")
        data = event.params.get("data", "{}")

        try:
            data_dict = json.loads(data)
        except json.JSONDecodeError as e:
            event.fail(f"Invalid JSON in data parameter: {e}")
            return
        if not isinstance(data_dict, dict):
            event.fail(f"data must be a JSON object, got {type(data_dict).__name__}")
            return

        try:
            cmd = ["/charm/bin/pebble", "notify", key]
            for k, v in data_dict.items():
                cmd.append(f"{k}={v}")
            process = container.exec(cmd)
            process.wait()
            event.set_results({"notice-sent": "true", "key": key})
        except (ops.pebble.ExecError, ops.pebble.ConnectionError) as e:
            event.fail(f"Failed to send notice: {e}")

    def _on_get_version_action(self, event: ops.ActionEvent) -> None:
        """Return charm and workload version information."""
        event.log("Retrieving version info")
        charm_version = self._get_charm_version()

        workload_version = "unavailable"
        if norma.CONTAINER_NAME not in self.meta.containers:
            event.set_results(
                {"charm-version": charm_version, "workload-version": "n/a (subordinate)"}
            )
            return
        container = self.unit.get_container(norma.CONTAINER_NAME)
        if container.can_connect():
            try:
                process = container.exec(
                    [norma.BINARY_PATH, "--check"],
                )
                process.wait()
                # Binary is reachable — read version from env
                plan = container.get_plan()
                svc = plan.services.get(norma.CONTAINER_NAME)
                if svc:
                    workload_version = svc.environment.get("VERSION", "unknown")
            except (ops.pebble.ExecError, ops.pebble.ConnectionError):
                pass

        event.set_results(
            {
                "charm-version": charm_version,
                "workload-version": workload_version,
            }
        )

    def _on_test_networking_action(self, event: ops.ActionEvent) -> None:
        """Report open ports and network binding information."""
        event.log("Retrieving networking info")

        # Opened ports
        ports = self.unit.opened_ports()
        port_list = [f"{p.port}/{p.protocol}" for p in ports]

        # Network bindings for key endpoints
        bindings: dict[str, dict[str, str]] = {}
        for endpoint in (
            "norma-peers",
            "calibration-provider",
            "calibration-requirer",
        ):
            try:
                binding = self.model.get_binding(endpoint)
                if binding and binding.network:
                    net = binding.network
                    bindings[endpoint] = {
                        "bind-address": str(net.bind_address),
                        "ingress-address": str(net.ingress_address),
                    }
            except ops.ModelError:
                bindings[endpoint] = {"error": "binding unavailable"}

        event.set_results(
            {
                "opened-ports": json.dumps(port_list),
                "bindings": json.dumps(bindings),
            }
        )

    def _on_check_security_action(self, event: ops.ActionEvent) -> None:
        """Report security posture: UID/GID, trust, credentials."""
        event.log("Checking security posture")
        results: dict[str, str] = {
            "charm-uid": str(os.getuid()),
            "charm-gid": str(os.getgid()),
        }

        container = self.unit.get_container(norma.CONTAINER_NAME)
        if container.can_connect():
            for field, cmd in (
                ("workload-uid", ["id", "-u"]),
                ("workload-gid", ["id", "-g"]),
            ):
                try:
                    proc = container.exec(cmd)
                    stdout, _ = proc.wait_output()
                    results[field] = stdout.strip()
                except (
                    ops.pebble.ExecError,
                    ops.pebble.APIError,
                    ops.pebble.ChangeError,
                    ops.pebble.ConnectionError,
                ):
                    results[field] = "unavailable"
        else:
            results["workload-uid"] = "unavailable"
            results["workload-gid"] = "unavailable"

        results["trust-available"] = "false"
        results["cloud-type"] = ""
        results["credential-endpoint"] = ""
        results["credential-auth-type"] = ""
        results["k8s-api-reachable"] = "false"
        cloud_spec = None
        try:
            cloud_spec = self.model.get_cloud_spec()
            results["trust-available"] = "true"
            results["cloud-type"] = cloud_spec.type if cloud_spec else ""
        except ops.ModelError:
            pass

        # FR-039: Exercise credential-get hook tool — hit K8s API
        if cloud_spec and cloud_spec.credential:
            results["credential-endpoint"] = cloud_spec.endpoint or ""
            results["credential-auth-type"] = cloud_spec.credential.auth_type or ""
            token = cloud_spec.credential.attributes.get(
                "Token", cloud_spec.credential.attributes.get("token", "")
            )
            if token and cloud_spec.endpoint:
                try:
                    import ssl
                    import urllib.error
                    import urllib.request

                    ssl_ctx = ssl.create_default_context()
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE
                    req = urllib.request.Request(
                        f"{cloud_spec.endpoint}/api/v1/namespaces",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    with urllib.request.urlopen(req, context=ssl_ctx, timeout=5) as resp:
                        results["k8s-api-reachable"] = str(resp.status == 200).lower()
                except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError):
                    results["k8s-api-reachable"] = "false"

        event.set_results(results)

    def _on_test_defer_action(self, event: ops.ActionEvent) -> None:
        """Arm or disarm event deferral for testing."""
        event.log("Configuring event deferral")
        previous = self._defer_armed
        self._defer_armed = event.params.get("arm", True)
        norma.write_defer_armed(self._defer_armed)
        event.set_results(
            {
                "deferral-armed": str(self._defer_armed).lower(),
                "previous-state": str(previous).lower(),
            }
        )

    # ------------------------------------------------------------------ #
    #  US22: Introspect action + section collectors                       #
    # ------------------------------------------------------------------ #

    def _on_introspect_action(self, event: ops.ActionEvent) -> None:
        """Return comprehensive structured report of all internal charm state."""
        event.log("Collecting introspection report")

        # Determine which sections to include
        filter_str = event.params.get("sections", "")
        if filter_str:
            requested = {s.strip() for s in filter_str.split(",") if s.strip()}
            sections = [s for s in REPORT_SECTIONS if s in requested]
        else:
            sections = list(REPORT_SECTIONS)

        collectors = {
            "identity": self._collect_identity,
            "version": self._collect_version,
            "leadership": self._collect_leadership,
            "config": self._collect_config,
            "event-ledger": self._collect_event_ledger,
            "relations": self._collect_relations,
            "storage": self._collect_storage,
            "containers": self._collect_containers,
            "secrets": self._collect_secrets,
        }

        report: dict[str, str] = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "unit": self.unit.name,
        }
        for section in sections:
            try:
                report[section] = json.dumps(collectors[section]())
            except Exception as e:
                report[section] = json.dumps({"status": "unavailable", "reason": str(e)})

        # Truncation: if total payload > 250KB, trim largest section
        max_bytes = 250_000
        total = sum(len(v) for v in report.values())
        while total > max_bytes and sections:
            largest = max(sections, key=lambda s: len(report.get(s, "")))
            truncated = {"status": "truncated", "reason": "payload exceeded 250KB"}
            report[largest] = json.dumps(truncated)
            sections.remove(largest)
            total = sum(len(v) for v in report.values())

        event.set_results(report)

    def _collect_identity(self) -> dict:
        """Collect unit identity information."""
        return {
            "unit-name": self.unit.name,
            "app-name": self.app.name,
            "model-name": self.model.name,
            "model-uuid": self.model.uuid,
            "charm-uid": os.getuid(),
            "charm-gid": os.getgid(),
        }

    def _collect_version(self) -> dict:
        """Collect charm and workload version."""
        return {
            "charm-version": self._get_charm_version(),
        }

    def _collect_leadership(self) -> dict:
        """Collect leadership status."""
        return {
            "is-leader": self.unit.is_leader(),
        }

    def _collect_config(self) -> dict:
        """Collect current effective configuration."""
        return {
            "calibration-string": self.config.get("calibration-string", "default"),
            "calibration-int": int(self.config.get("calibration-int", norma.DEFAULT_PORT)),
            "calibration-float": float(self.config.get("calibration-float", 1.0)),
            "calibration-bool": self.config.get("calibration-bool", True),
            "calibration-secret": "set" if self.config.get("calibration-secret") else "unset",
        }

    def _collect_event_ledger(self) -> dict:
        """Collect event ledger summary."""
        return {
            "count": len(self._event_ledger),
            "events": self._event_ledger[-50:],  # last 50 for size control
        }

    def _collect_relations(self) -> dict:
        """Collect relation metadata — only our own data, never remote databags.

        Remote app/unit data may contain sensitive values (tokens, certs).
        We only expose: relation id, remote unit names, and our own databags.
        """
        result: dict[str, list] = {}
        for endpoint, relations in self.model.relations.items():
            rel_list = []
            for rel in relations:
                rel_info: dict = {
                    "id": rel.id,
                    "our-app-data": dict(rel.data.get(self.app, {})),
                    "our-unit-data": dict(rel.data.get(self.unit, {})),
                    "remote-units": sorted(u.name for u in rel.units),
                }
                rel_list.append(rel_info)
            if rel_list:
                result[endpoint] = rel_list
        return result

    def _collect_storage(self) -> dict:
        """Collect storage status for all declared storages."""
        if norma.CONTAINER_NAME not in self.meta.containers:
            return {"status": "n/a", "reason": "subordinate mode"}
        container = self.unit.get_container(norma.CONTAINER_NAME)
        can_connect = container.can_connect()
        result: dict = {}
        for s_name, s_cfg in norma.STORAGE_CONFIG.items():
            attached = bool(self.model.storages.get(s_name))
            info: dict = {
                "attached": attached,
                "mount-point": s_cfg["path"],
            }
            if attached and can_connect:
                marker_path = f"{s_cfg['path']}/{s_cfg['marker']}"
                try:
                    info["marker-exists"] = container.exists(marker_path)
                except ops.pebble.ConnectionError:
                    info["marker-exists"] = "unknown"
            elif attached:
                info["marker-exists"] = "unknown"
            result[s_name] = info
        return result

    def _collect_containers(self) -> dict:
        """Collect container connectivity status."""
        result: dict[str, dict] = {}
        for name in (norma.CONTAINER_NAME, norma.SECONDARY_CONTAINER):
            if name not in self.meta.containers:
                continue
            container = self.unit.get_container(name)
            connected = container.can_connect()
            info: dict = {"connected": connected}
            if connected:
                try:
                    plan = container.get_plan()
                    info["services"] = list(plan.services.keys())
                except ops.pebble.ConnectionError:
                    info["services"] = []
                    info["status"] = "connection-lost"
            else:
                info["status"] = "not-ready"
            result[name] = info
        return result

    def _collect_secrets(self) -> dict:
        """Collect secrets metadata (never exposes values)."""
        peer = self.model.get_relation("norma-peers")
        if not peer:
            return {"status": "no-peer-relation"}
        secret_id = peer.data[self.app].get("secret-id") if self.unit.is_leader() else None
        return {
            "secret-id": secret_id or "unavailable",
            "has-secret": bool(secret_id),
        }

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

    def _update_relation_data(self, *, broken_relation: ops.Relation | None = None) -> None:
        """Update peer and calibration relation data (idempotent).

        Only writes when values change to avoid relation-changed feedback loops.

        Args:
            broken_relation: The relation being broken (if any). Grant logic
                skips this relation to avoid re-granting after a revoke.
        """
        peer = self.model.get_relation("norma-peers")
        if peer:
            unit_data = {
                "unit-name": self.unit.name,
                "leader": str(self.unit.is_leader()),
            }
            existing = peer.data[self.unit]
            if any(existing.get(k) != v for k, v in unit_data.items()):
                existing.update(unit_data)
            if self.unit.is_leader():
                app_data = {
                    "cluster-size": str(len(peer.units) + 1),
                    "leader-unit": self.unit.name,
                }
                # Create app secret if not yet created
                if "secret-id" not in peer.data[self.app]:
                    secret = self.app.add_secret(
                        {"password": secrets.token_urlsafe(24)},
                        label="calibration-password",
                        rotate=ops.SecretRotate.MONTHLY,
                    )
                    app_data["secret-id"] = secret.id
                existing_app = peer.data[self.app]
                if any(existing_app.get(k) != v for k, v in app_data.items()):
                    existing_app.update(app_data)

        # Grant secret access to calibration-provider relations (skip broken)
        if peer and self.unit.is_leader():
            secret_id = peer.data[self.app].get("secret-id")
            if secret_id:
                try:
                    secret = self.model.get_secret(id=secret_id)
                    for rel in self.model.relations.get("calibration-provider", []):
                        if rel is not broken_relation:
                            secret.grant(rel)
                except ops.SecretNotFoundError:
                    pass

        for endpoint in ("calibration-provider", "calibration-requirer"):
            for rel in self.model.relations.get(endpoint, []):
                cal_data = {
                    "unit-name": self.unit.name,
                    "role": endpoint.split("-")[-1],
                }
                existing_cal = rel.data[self.unit]
                if any(existing_cal.get(k) != v for k, v in cal_data.items()):
                    existing_cal.update(cal_data)

    def _get_charm_version(self) -> str:
        """Read charm version from the version file written by charmcraft."""
        try:
            return (self.charm_dir / "version").read_text().strip()
        except FileNotFoundError:
            return "dev"


if __name__ == "__main__":  # pragma: nocover
    ops.main(NormaK8sCharm)
