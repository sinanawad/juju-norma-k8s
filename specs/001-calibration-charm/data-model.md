# Data Model: Juju K8s Calibration Charm

**Branch**: `001-calibration-charm` | **Date**: 2026-02-11

## Entities

### EventLedger

In-memory ordered log. Resets on pod restart (by design — tests event firing,
not persistence).

| Field | Type | Description |
|-------|------|-------------|
| timestamp | str (ISO 8601) | When the event was observed |
| event_name | str | Juju event name (e.g., `config-changed`, `install`) |
| unit_name | str | Unit that observed the event (e.g., `juju-norma-k8s/0`) |
| extra | dict[str, str] | Optional metadata (e.g., `{"deferred": "true"}`, `{"relation_id": "3"}`) |

**Storage**: Python `list[dict]` in charm instance. Not persisted.
**Access**: Read via `get-event-log` action.

### CalibrationConfig

Declared in `charmcraft.yaml`. One option per supported Juju config type.

| Option (YAML) | Type | Default | Validation | Python accessor |
|---------------|------|---------|------------|-----------------|
| `calibration-string` | string | `"default"` | Non-empty | `self.config["calibration_string"]` |
| `calibration-int` | int | `8080` | 1–65535 | `self.config["calibration_int"]` |
| `calibration-float` | float | `1.0` | > 0.0 | `self.config["calibration_float"]` |
| `calibration-bool` | boolean | `true` | N/A | `self.config["calibration_bool"]` |
| `calibration-secret` | secret | N/A | Valid secret URI | `self.config.get("calibration_secret")` |

**Note**: YAML dashes become Python underscores per constitution naming convention.

### ClusterState

Runtime view of the deployment, assembled by `_reconcile()` and reported by actions.

| Field | Type | Source |
|-------|------|--------|
| unit_count | int | `len(peer_relation.units) + 1` |
| planned_units | int | `self.app.planned_units()` |
| leader_unit | str | `self.unit.name` if `self.unit.is_leader()` |
| is_leader | bool | `self.unit.is_leader()` |
| peer_app_data | dict[str, str] | `peer_relation.data[self.app]` |
| peer_unit_data | dict[str, dict] | `{u.name: dict(peer_relation.data[u]) for u in peer_relation.units}` |
| secret_id | str | From peer app data key `"secret-id"` |
| storage_attached | bool | Storage mount point exists |
| storage_marker | str | Content of marker file in storage |

### PebbleLayer (Primary Container: `norma`)

| Field | Value |
|-------|-------|
| service name | `norma` |
| override | `replace` |
| startup | `enabled` |
| command | `/bin/norma` |
| environment.PORT | From `calibration-int` config (default `8080`) |
| environment.VERSION | Charm version string |
| checks.health | HTTP `http://localhost:8080/health`, level `ready`, period 10s, threshold 3 |
| checks.alive | exec `["/bin/norma", "--check"]`, level `alive`, period 30s |
| checks.tcp-alive | TCP port 8080, level `alive`, period 30s |

### PebbleLayer (Secondary Container: `norma-secondary`)

| Field | Value |
|-------|-------|
| service name | `norma-secondary` |
| override | `replace` |
| startup | `enabled` |
| command | `/bin/norma` |
| environment.PORT | `8081` (fixed) |
| environment.VERSION | Charm version string |
| user | `_daemon_` |
| checks.health-secondary | HTTP `http://localhost:8081/health`, level `ready`, period 10s, threshold 3 |

### JujuSecret (App-Owned)

| Field | Value |
|-------|-------|
| label | `calibration-password` |
| owner | application (leader creates) |
| content | `{"password": secrets.token_urlsafe(24)}` |
| rotation | `SecretRotate.MONTHLY` |
| storage | Secret ID stored in peer data key `"secret-id"` |

### Storage

| Name | Type | Min Size | Mount Point | Required |
|------|------|----------|-------------|----------|
| `data` | filesystem | 1G | `/var/lib/norma` | Yes |
| `logs` | filesystem | 512M | `/var/log/norma` | No (0-1) |

**Data marker file**: `/var/lib/norma/calibration-marker.json`
Content: `{"created_by": "<unit_name>", "created_at": "<ISO timestamp>", "revision": <int>}`

**Logs marker file**: `/var/log/norma/logs-marker.json`
Content: `{"created_by": "<unit_name>", "created_at": "<ISO timestamp>", "revision": <int>}`

## Relation Endpoints

### Peer

| Endpoint | Interface | Purpose |
|----------|-----------|---------|
| `norma-peers` | `norma_peers` | Leader coordination, secret ID sharing, unit data exchange |

### Provides

| Endpoint | Interface | Optional | Limit | Purpose |
|----------|-----------|----------|-------|---------|
| `calibration-provider` | `calibration` | true | — | Testing provides/requires and self-relation (US7) |
| `metrics-endpoint` | `prometheus_scrape` | true | — | COS metrics (US18) |
| `grafana-dashboard` | `grafana_dashboard` | true | — | COS dashboards (US18) |
| `juju-info` | `juju-info` | true | — | Subordinate attachment point (US25) |

### Requires

| Endpoint | Interface | Optional | Limit | Purpose |
|----------|-----------|----------|-------|---------|
| `calibration-requirer` | `calibration` | true | 1 | Testing provides/requires and self-relation (US7) |
| `log-proxy` | `loki_push_api` | true | 1 | COS log forwarding (US18) |

**Self-relation**: `juju integrate juju-norma-k8s:calibration-provider juju-norma-k8s:calibration-requirer`
uses matching `calibration` interface on both sides.

## Containers

| Name | Resource | UID/GID | Mounts |
|------|----------|---------|--------|
| `norma` | `juju-norma-image` | 584792:584792 | `data` -> `/var/lib/norma`, `logs` -> `/var/log/norma` |
| `norma-secondary` | `juju-norma-image` | 584792:584792 | — |

Both containers use the same ROCK image resource (`juju-norma-image`).

## State Transitions

### Charm Status (via collect_unit_status)

```text
                ┌──────────────────────┐
                │     WaitingStatus    │
                │ "Waiting for Pebble" │
                └──────────┬───────────┘
                           │ container.can_connect()
                           ▼
                ┌──────────────────────┐
                │    BlockedStatus     │◄── invalid config
                │ "<validation error>" │◄── forced via set-status action
                └──────────┬───────────┘
                           │ all preconditions met
                           ▼
                ┌──────────────────────┐
                │    ActiveStatus()    │
                │    (no message)      │
                └──────────────────────┘
```

Priority: BlockedStatus > MaintenanceStatus > WaitingStatus > ActiveStatus

### Workload Health Toggle

```text
    healthy (default)  ──toggle-health──►  unhealthy
         200                                  500
          ▲                                    │
          └──────────toggle-health─────────────┘
```

### Secret Lifecycle

```text
    leader-elected ──► create secret ──► store ID in peer data
                                              │
    secret-rotate  ──► new revision ──────────┘
    secret-expired ──► cleanup
    secret-remove  ──► remove old revision
```

## Introspection Report (US22)

The `introspect` action returns a flat key-value map where each key is a section name and each value is a JSON-encoded string. Two metadata keys (`timestamp` and `unit`) are plain strings.

### Top-Level Keys

| Key | Type | Always Present | Description |
|-----|------|---------------|-------------|
| `timestamp` | string (ISO 8601) | Yes | When the report was generated |
| `unit` | string | Yes | Unit name (e.g., "juju-norma-k8s/0") |
| `identity` | JSON string | Yes | Unit, app, and model identity |
| `version` | JSON string | Yes | Charm and workload versions |
| `leadership` | JSON string | Yes | Leadership status |
| `config` | JSON string | Yes | All config options with values |
| `event-ledger` | JSON string | Yes | Recent event history |
| `relations` | JSON string | Yes | All relation endpoints and data |
| `storage` | JSON string | Yes | Storage attachment status |
| `containers` | JSON string | Yes | Container connectivity and services |
| `secrets` | JSON string | Yes | Secret metadata (no values) |
| `goal-state` | JSON string | Yes | Planned model state from `goal-state` hook tool (units and relations with status) |

### Section Schemas

**identity**: `{"unit": "juju-norma-k8s/0", "app": "norma-k8s", "model": "test-model", "is_leader": true}`

**version**: `{"charm_version": "1610bbe", "workload_version": "0.1.0", "workload_available": true}`

**leadership**: `{"is_leader": true}`

**config**: `{"options": {"calibration-string": {"value": "hello", "default": "default", "changed": true}, ...}}`

**event-ledger**: `{"count": 5, "events": [...], "truncated": false}`

**relations**: `{"endpoints": {"norma-peers": {"interface": "norma_peers", "relations": [{"relation_id": 1, "remote_app": "norma-k8s", ...}]}}}`

**storage**: `{"storages": {"data": {"attached": true, "location": "/var/lib/norma", "count": 1}}}`

**containers**: `{"norma": {"connected": true, "services": {"norma": {"current": "active", "startup": "enabled"}}}, ...}`

**secrets**: `{"secrets": [{"label": "calibration-secret", "uri": "secret:abc123", "revision": 1, "owner": "application"}]}`

### Unavailable Section

When a collector fails: `{"status": "unavailable", "reason": "Description of what went wrong"}`

---

## Subordinate Overlay (US25)

The subordinate variant is built from the same source tree using a charmcraft overlay file.

### `charmcraft-subordinate.yaml` delta from `charmcraft.yaml`

| Field | Principal | Subordinate |
|-------|-----------|-------------|
| `subordinate` | absent | `true` |
| `juju-info` | `provides: { interface: juju-info }` | `requires: { interface: juju-info, scope: container }` |
| `containers` | two containers defined | removed (subordinates share principal's pod) |
| `resources` | `juju-norma-image` OCI | removed |
| `storage` | `data` + `logs` | removed |

The subordinate overlay keeps all other fields (config, peers, calibration endpoints, actions, charm-libs) identical. This means the subordinate charm code is the same — it just runs inside the principal's pod.

## Edge Case Assignments (from spec)

Deferred to planning per spec clarification. Assignments to user stories:

| Edge Case | Assigned To | Resolution |
|-----------|-------------|------------|
| Pebble connectivity loss during layer apply | US2 | `_reconcile()` catches `ConnectionError`, sets WaitingStatus, next event retries |
| Leader removed mid-write to peer data | US6/US8 | Juju guarantees atomic databag writes; new leader re-reconciles |
| Rapid successive config-changed | US3 | Idempotent `_reconcile()` handles last-writer-wins; event ledger records all |
| Secret rotation without leader | US9 | `secret-rotate` fires on owner unit only (always the leader for app secrets) |
| Storage detach during write | US10 | `storage-detaching` fires before removal; marker write is atomic (write-then-rename) |
| relation-broken without relation-changed | US7 | `_reconcile()` reads current relation state; no dependency on prior events |
| upgrade-charm with unhealthy workload | US15 | `_reconcile()` re-applies layer and replans; health check recovers |
| Scale-down exceeding tolerance | US8 | Juju handles; remaining units re-elect leader; charm reports via `get-cluster-info` |
| Force remove while hooks running | US1 | Juju forcefully terminates; model returns to clean state (AC4) |
| send_signal to exited service | US12 | Pebble returns error; action catches exception and reports failure (AC12) |
| import-filesystem on bound PV | US10 | Juju rejects the import; PV must be unbound first (AC6, xfail) |
