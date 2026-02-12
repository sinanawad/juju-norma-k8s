# Data Model: Charm Introspection Action

**Date**: 2026-02-12

## Introspection Report

The action result is a flat key-value map where each key is a section name and each value is a JSON-encoded string. Two metadata keys (`timestamp` and `unit`) are plain strings.

### Top-Level Keys

| Key | Type | Always Present | Description |
|-----|------|---------------|-------------|
| `timestamp` | string (ISO 8601) | Yes | When the report was generated |
| `unit` | string | Yes | Unit name (e.g., "norma-k8s/0") |
| `identity` | JSON string | Yes | Unit, app, and model identity |
| `version` | JSON string | Yes | Charm and workload versions |
| `leadership` | JSON string | Yes | Leadership status |
| `config` | JSON string | Yes | All config options with values |
| `event-ledger` | JSON string | Yes | Recent event history |
| `relations` | JSON string | Yes | All relation endpoints and data |
| `storage` | JSON string | Yes | Storage attachment status |
| `containers` | JSON string | Yes | Container connectivity and services |
| `secrets` | JSON string | Yes | Secret metadata (no values) |

### Section Schemas

#### identity

```json
{
  "unit": "norma-k8s/0",
  "app": "norma-k8s",
  "model": "test-model",
  "is_leader": true
}
```

#### version

```json
{
  "charm_version": "1610bbe",
  "workload_version": "0.1.0",
  "workload_available": true
}
```

#### leadership

```json
{
  "is_leader": true
}
```

#### config

```json
{
  "options": {
    "calibration-string": {"value": "hello", "default": "default", "changed": true},
    "calibration-int": {"value": 8080, "default": 8080, "changed": false},
    "calibration-float": {"value": 1.0, "default": 1.0, "changed": false},
    "calibration-bool": {"value": true, "default": true, "changed": false},
    "calibration-secret": {"value": "secret:abc123", "default": null, "changed": true}
  }
}
```

#### event-ledger

```json
{
  "count": 5,
  "events": [
    {"timestamp": "2026-02-12T10:00:00+00:00", "event_name": "install", "unit_name": "norma-k8s/0"},
    {"timestamp": "2026-02-12T10:00:01+00:00", "event_name": "config-changed", "unit_name": "norma-k8s/0"}
  ],
  "truncated": false
}
```

#### relations

```json
{
  "endpoints": {
    "norma-peers": {
      "interface": "norma_peers",
      "relations": [
        {
          "relation_id": 1,
          "remote_app": "norma-k8s",
          "remote_units": ["norma-k8s/0"],
          "local_app_data": {},
          "local_unit_data": {},
          "remote_app_data": {},
          "remote_units_data": {}
        }
      ]
    }
  }
}
```

#### storage

```json
{
  "storages": {
    "data": {
      "attached": true,
      "location": "/var/lib/norma",
      "count": 1
    }
  }
}
```

#### containers

```json
{
  "norma": {
    "connected": true,
    "services": {
      "norma": {"current": "active", "startup": "enabled"}
    }
  },
  "norma-secondary": {
    "connected": false,
    "services": {},
    "status": "unavailable",
    "reason": "Pebble not connected"
  }
}
```

#### secrets

```json
{
  "secrets": [],
  "note": "No secrets configured"
}
```

When secrets exist:

```json
{
  "secrets": [
    {"label": "calibration-secret", "uri": "secret:abc123", "revision": 1, "owner": "application"}
  ]
}
```

### Unavailable Section

When a collector fails, the section value is:

```json
{
  "status": "unavailable",
  "reason": "Description of what went wrong"
}
```
