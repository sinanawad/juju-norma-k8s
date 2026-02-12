# Implementation Plan: Juju K8s Calibration Charm

**Branch**: `001-calibration-charm` | **Date**: 2026-02-11 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-calibration-charm/spec.md`

## Summary

Build a comprehensive Juju K8s calibration charm (`norma-k8s`) that exercises
all 21 Juju features relevant to K8s charms. The charm follows the holistic
reconciler architecture with a purpose-built Go binary workload co-located in
`workload/`, managed via Pebble in two containers (same ROCK image, different
ports). Every feature is testable independently via dedicated actions, making
the charm suitable as a CI validation suite for Juju itself.

## Technical Context

**Language/Version**: Python 3.10+ (charm), Go 1.22+ (workload binary)
**Primary Dependencies**: `ops` (charm framework), `ops[testing]` (unit tests),
`jubilant` (integration tests), `ruff` (lint), `coverage[toml]` (coverage)
**Charm Libraries**: `prometheus_scrape`, `grafana_dashboard`, `loki_push_api`
**Storage**: Juju filesystem storage (PersistentVolume), peer relation data
**Testing**: ops.testing/Scenario (unit), jubilant (integration), ruff (lint)
**Target Platform**: Kubernetes (Juju 3.6+, ubuntu@24.04, MicroK8s)
**Project Type**: Single project (charm + co-located Go workload)
**Performance Goals**: Active in <120s, scale 1→3 in <180s, actions <30s
**Constraints**: Non-root execution, chiselled ROCK, no StoredState, no
event.defer() for control flow
**Scale/Scope**: 21 user stories, 17 actions, 2 containers, 7+ relation
endpoints, 5 config options (one per type)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | Holistic Reconciler Architecture | PASS | All lifecycle events route to `_reconcile()`. Action handlers are dedicated (permitted). |
| II | Workload Abstraction | PASS | `src/norma.py` has zero ops dependency. Pebble layers, port definitions, config construction all in workload module. |
| III | Stateless by Default | PASS | No StoredState. Event ledger is ephemeral in-memory (resets on pod restart by design). Peer relation data for persistent state. Secret IDs stored in peer data. |
| IV | Security-First | PASS | `charm-user: non-root`, container uid/gid 10000, Juju secrets for password, chiselled ROCK, no sensitive data in logs. |
| V | Observable by Design | PASS | US18 provides prometheus_scrape, grafana_dashboard, loki_push_api. Workload `/metrics` endpoint in Prometheus format. Alert rules shipped. |
| VI | Three-Tier Testing | PASS | Unit: ops.testing for charm + plain pytest for norma.py. Integration: jubilant. Lint: ruff. No Harness, no pytest-operator, no flake8. |
| VII | Simplicity & Idempotency | PASS with EXCEPTION | All handlers idempotent. `collect_unit_status` for status. Exception: US20 deliberately tests `event.defer()` to validate Juju's deferral mechanism — see Complexity Tracking. |

**Gate result: PASS** (1 justified exception documented below)

## Project Structure

### Documentation (this feature)

```text
specs/001-calibration-charm/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── charmcraft-schema.yaml
│   └── actions-schema.yaml
└── tasks.md
```

### Source Code (repository root)

```text
charmcraft.yaml
pyproject.toml
uv.lock
Makefile
rockcraft.yaml
workload/
  main.go
  go.mod
  go.sum
src/
  charm.py
  norma.py
  grafana_dashboards/
    norma.json
  prometheus_alert_rules/
    norma_alerts.yaml
lib/charms/
tests/
  conftest.py
  unit/
    test_charm.py
    test_norma.py
  integration/
    __init__.py
    conftest.py
    test_lifecycle.py
    test_pebble.py
    test_config.py
    test_status.py
    test_actions.py
    test_relations.py
    test_scaling.py
    test_secrets.py
    test_storage.py
    test_health_checks.py
    test_pebble_ops.py
    test_notices.py
    test_networking.py
    test_upgrade.py
    test_multi_container.py
    test_security.py
    test_observability.py
    test_cmr.py
    test_defer.py
    test_oci_resource.py
```

**Structure Decision**: Single project layout per constitution. The `workload/`
directory is co-located at repo root for the Go binary. The charm follows the
standard `src/charm.py` + `src/norma.py` separation. Integration tests are
organized one file per user story for independent execution.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| US20 uses `event.defer()` | The calibration charm's purpose is to test ALL Juju features including deferral. US20 validates defer behavior, re-emission ordering, and non-deferrable event rejection. | Not testing defer would leave a critical Juju mechanism unvalidated. The deferral is action-triggered and isolated to US20; it is not used as charm control flow. |
| No `tls-certificates` relation (Principle IV) | The calibration charm tests Juju primitives (lifecycle, config, relations, secrets, Pebble, etc.), not infrastructure security patterns. TLS integration requires a TLS provider charm and certificate management that is orthogonal to the Juju features being calibrated. | Adding TLS would increase deployment complexity without testing any new Juju mechanism — the `tls-certificates` interface uses standard relations already covered by US7/US19. |
| No `parca_scrape`/`tracing` relation (Principle V) | Continuous profiling and distributed tracing libraries for Juju charms are not yet stable. The calibration charm validates COS observability via prometheus_scrape, grafana_dashboard, and loki_push_api (US18), covering the three established pillars. | Adding tracing would depend on unstable libraries and a tracing backend not yet part of standard COS deployments, risking test flakiness without testing a novel Juju mechanism. |
