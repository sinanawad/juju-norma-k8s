# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Workload abstraction module for the norma-k8s calibration charm.

This module has ZERO dependency on the ops framework. It handles Pebble layer
construction, configuration validation, and workload-related constants. All
functions are independently testable with plain pytest.
"""

import json

CONTAINER_NAME = "norma"
SECONDARY_CONTAINER = "norma-secondary"
DEFAULT_PORT = 8080
SECONDARY_PORT = 8081
HEALTH_FLAG_FILE = "/tmp/norma-unhealthy"
STORAGE_PATH = "/var/lib/norma"
MARKER_FILE = "calibration-marker.json"
BINARY_PATH = "/bin/norma"
LEDGER_FILE = "/tmp/norma-event-ledger.json"


def read_event_ledger() -> list[dict]:
    """Read the event ledger from the charm container filesystem.

    Returns an empty list if the file doesn't exist (pod restart resets it).
    """
    try:
        with open(LEDGER_FILE) as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def write_event_ledger(ledger: list[dict]) -> None:
    """Write the event ledger to the charm container filesystem."""
    with open(LEDGER_FILE, "w") as f:
        f.write(json.dumps(ledger))


def validate_config(config: dict) -> tuple[bool, str]:
    """Validate charm configuration values.

    Returns (True, "") if valid, or (False, error_message) if invalid.
    """
    cal_string = config.get("calibration_string", "default")
    if not cal_string:
        return False, "calibration-string must not be empty"

    port = config.get("calibration_int", DEFAULT_PORT)
    if not (1 <= port <= 65535):
        return False, f"calibration-int must be between 1 and 65535, got {port}"

    cal_float = config.get("calibration_float", 1.0)
    if cal_float <= 0.0:
        return False, f"calibration-float must be > 0.0, got {cal_float}"

    return True, ""


def build_pebble_layer(container_name: str, port: int, version: str) -> dict:
    """Build the Pebble layer configuration for the primary container.

    Args:
        container_name: Name of the container (used as service name).
        port: Port for the workload HTTP server.
        version: Charm version string passed to the workload.

    Returns:
        A dict suitable for container.add_layer().
    """
    return {
        "summary": f"{container_name} layer",
        "description": f"Pebble layer for {container_name}",
        "services": {
            container_name: {
                "override": "replace",
                "startup": "enabled",
                "command": BINARY_PATH,
                "environment": {
                    "PORT": str(port),
                    "VERSION": version,
                },
            },
        },
        "checks": {
            "health": {
                "override": "replace",
                "level": "ready",
                "http": {"url": f"http://localhost:{port}/health"},
                "period": "10s",
                "threshold": 3,
            },
            "alive": {
                "override": "replace",
                "level": "alive",
                "exec": {"command": f"{BINARY_PATH} --check"},
                "period": "30s",
            },
            "tcp-alive": {
                "override": "replace",
                "level": "alive",
                "tcp": {"port": port},
                "period": "30s",
            },
        },
    }


def build_secondary_layer(version: str) -> dict:
    """Build the Pebble layer for the secondary container.

    Args:
        version: Charm version string passed to the workload.

    Returns:
        A dict suitable for container.add_layer().
    """
    return {
        "summary": "norma-secondary layer",
        "description": "Pebble layer for norma-secondary",
        "services": {
            "norma-secondary": {
                "override": "replace",
                "startup": "enabled",
                "command": BINARY_PATH,
                "environment": {
                    "PORT": str(SECONDARY_PORT),
                    "VERSION": version,
                },
            },
        },
        "checks": {
            "health-secondary": {
                "override": "replace",
                "level": "ready",
                "http": {"url": f"http://localhost:{SECONDARY_PORT}/health"},
                "period": "10s",
                "threshold": 3,
            },
        },
    }
