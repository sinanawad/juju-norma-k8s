# Quickstart: Charm Introspection Action

## Prerequisites

- norma-k8s charm deployed on a Juju K8s model
- `juju` CLI available

## Basic Usage

### Full report (all sections)

```bash
juju run norma-k8s/0 introspect
```

Output includes all sections: `identity`, `version`, `leadership`, `config`, `event-ledger`, `relations`, `storage`, `containers`, `secrets`, plus `timestamp` and `unit` metadata.

### Filtered report (specific sections only)

```bash
juju run norma-k8s/0 introspect sections=config,relations
```

### Parse a specific section with jq

```bash
juju run norma-k8s/0 introspect --format=json | jq -r '.results.config' | jq .
```

## CI Usage Example

```bash
# Assert the charm is leader
REPORT=$(juju run norma-k8s/0 introspect sections=leadership --format=json)
IS_LEADER=$(echo "$REPORT" | jq -r '.results.leadership' | jq -r '.is_leader')
[ "$IS_LEADER" = "true" ] || echo "FAIL: expected leader"

# Assert config was changed
REPORT=$(juju run norma-k8s/0 introspect sections=config --format=json)
CHANGED=$(echo "$REPORT" | jq -r '.results.config' | jq -r '.options["calibration-string"].changed')
[ "$CHANGED" = "true" ] || echo "FAIL: expected config changed"

# Assert peer relation exists
REPORT=$(juju run norma-k8s/0 introspect sections=relations --format=json)
PEERS=$(echo "$REPORT" | jq -r '.results.relations' | jq -r '.endpoints["norma-peers"]')
[ "$PEERS" != "null" ] || echo "FAIL: expected peer relation"
```

## Testing the Feature

### Unit tests

```bash
uv run pytest tests/unit/test_charm.py -k introspect -v
```

### Integration test

```bash
# Deploy charm, run introspect, verify sections
juju add-model test-model
juju deploy ./norma-k8s_amd64.charm --resource juju-norma-image=localhost:32000/norma:0.1.0
juju wait-for application norma-k8s --query='status.current=="active"'
juju run norma-k8s/0 introspect
```

## Section Reference

| Section | Description |
|---------|-------------|
| `identity` | Unit name, app name, model name, leadership |
| `version` | Charm version and workload version |
| `leadership` | Whether this unit is the leader |
| `config` | All config options with current values, defaults, and changed flag |
| `event-ledger` | In-memory event history (resets on pod restart) |
| `relations` | All endpoints with connected apps, interfaces, and databag contents |
| `storage` | Storage attachment status and locations |
| `containers` | Pebble connectivity and service status per container |
| `secrets` | Secret metadata only (URI, label, revision, owner) |
