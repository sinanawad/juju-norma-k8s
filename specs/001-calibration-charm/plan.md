# Implementation Plan: Juju K8s Calibration Charm

**Branch**: `001-calibration-charm` | **Date**: 2026-02-18 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-calibration-charm/spec.md`

## Summary

Build a comprehensive Juju K8s calibration charm (`juju-norma-k8s`) that exercises
all 25 Juju features relevant to K8s charms. The charm follows the holistic
reconciler architecture with a purpose-built Go binary workload co-located in
`workload/`, managed via Pebble in two containers (same ROCK image, different
ports). Every feature is testable independently via dedicated actions, making
the charm suitable as a self-sufficient CI validation suite for Juju itself —
replacing ALL existing Juju K8s sidecar test charms (NFR-005).

The charm also serves as the principal for subordinate charm testing (US25),
using a charmcraft overlay (`charmcraft-subordinate.yaml`) to repack the same
source as a subordinate variant.

## Technical Context

**Language/Version**: Python 3.12+ (charm, ubuntu@24.04), Go 1.22+ (workload binary)
**Primary Dependencies**: `ops` (charm framework), `ops[testing]` (unit tests),
`jubilant` (integration tests), `ruff` (lint), `coverage[toml]` (coverage)
**Charm Libraries**: `prometheus_scrape`, `grafana_dashboard`, `loki_push_api`
**Storage**: Juju filesystem storage (PersistentVolume, two named storages: data + logs), peer relation data
**Testing**: ops.testing/Scenario (unit), jubilant (integration), ruff (lint)
**Target Platform**: Kubernetes (Juju 3.6+, ubuntu@24.04, MicroK8s)
**Project Type**: Single project (charm + co-located Go workload + subordinate overlay)
**Performance Goals**: Active in <120s, scale 1->3 in <180s, actions <30s
**Constraints**: Non-root execution, chiselled ROCK, no StoredState, no
event.defer() for control flow
**Scale/Scope**: 25 user stories, 18 actions (+1 introspect in US22), 2 containers,
8+ relation endpoints (including juju-info), 5 config options (one per type),
2 named storages (data + logs), 40 functional requirements, 5 non-functional requirements

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | Holistic Reconciler Architecture | PASS | All lifecycle events route to `_reconcile()`. Action handlers are dedicated (permitted). |
| II | Workload Abstraction | PASS | `src/norma.py` has zero ops dependency. Pebble layers, port definitions, config construction all in workload module. |
| III | Stateless by Default | PASS | No StoredState. Event ledger is ephemeral in-memory (resets on pod restart by design). Peer relation data for persistent state. Secret IDs stored in peer data. |
| IV | Security-First | PASS with EXCEPTION | `charm-user: non-root`, container uid/gid 584792 (`_daemon_`), Juju secrets for password, chiselled ROCK, no sensitive data in logs. Exception: FR-031 requires a `charm-user: sudoer` build variant — see Complexity Tracking. |
| V | Observable by Design | PASS with EXCEPTION | US18 provides prometheus_scrape, grafana_dashboard, loki_push_api. Workload `/metrics` endpoint in Prometheus format. Alert rules shipped. Exception: No parca_scrape/tracing — see Complexity Tracking. |
| VI | Three-Tier Testing | PASS | Unit: ops.testing for charm + plain pytest for norma.py. Integration: jubilant. Lint: ruff. No Harness, no pytest-operator, no flake8. |
| VII | Simplicity & Idempotency | PASS with EXCEPTION | All handlers idempotent. `collect_unit_status` for status. Exception: US20 deliberately tests `event.defer()` to validate Juju's deferral mechanism — see Complexity Tracking. |
| VIII | CLI Acceptance Verification | PASS | Every user story is CLI-verified against a live Juju deployment before being marked complete. Acceptance workflow: unit tests -> deploy -> CLI exercise -> verify against spec ACs. |

**Gate result: PASS** (3 justified exceptions documented below)

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
charmcraft.yaml                    # principal charm metadata (charm-user: non-root)
charmcraft-subordinate.yaml        # overlay: subordinate=true, juju-info requires scope:container
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
    setup_env.py
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
    test_introspect.py
    test_multi_storage.py
    test_subordinate.py
```

**Structure Decision**: Single project layout per constitution. The `workload/`
directory is co-located at repo root for the Go binary. The charm follows the
standard `src/charm.py` + `src/norma.py` separation. Integration tests are
organized one file per user story for independent execution. The subordinate
overlay (`charmcraft-subordinate.yaml`) lives at repo root alongside the
principal `charmcraft.yaml`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| US20 uses `event.defer()` | The calibration charm's purpose is to test ALL Juju features including deferral. US20 validates defer behavior, re-emission ordering, and non-deferrable event rejection. | Not testing defer would leave a critical Juju mechanism unvalidated. The deferral is action-triggered and isolated to US20; it is not used as charm control flow. |
| No `tls-certificates` relation (Principle IV) | The calibration charm tests Juju primitives (lifecycle, config, relations, secrets, Pebble, etc.), not infrastructure security patterns. TLS integration requires a TLS provider charm and certificate management that is orthogonal to the Juju features being calibrated. | Adding TLS would increase deployment complexity without testing any new Juju mechanism — the `tls-certificates` interface uses standard relations already covered by US7/US19. |
| No `parca_scrape`/`tracing` relation (Principle V) | Continuous profiling and distributed tracing libraries for Juju charms are not yet stable. The calibration charm validates COS observability via prometheus_scrape, grafana_dashboard, and loki_push_api (US18), covering the three established pillars. | Adding tracing would depend on unstable libraries and a tracing backend not yet part of standard COS deployments, risking test flakiness without testing a novel Juju mechanism. |
| FR-031 `charm-user: sudoer` variant (Principle IV) | Constitution IV mandates `charm-user: non-root`. FR-031 requires a build variant with `charm-user: sudoer` to validate all Juju privilege levels for K8s charms. The sudoer variant is a CI-only build artifact — the primary/default charm always uses non-root. | Not testing sudoer would leave a Juju privilege mode unvalidated. The variant is built from a separate `charmcraft-sudoer.yaml` overlay and tested in a CI matrix job, never published as the production artifact. |

## Architecture

### Two-Module Separation

- **`src/charm.py`** — Juju lifecycle, relations, status. Imports `ops`. All event handlers route to a single `_reconcile()` method (holistic reconciler pattern).
- **`src/norma.py`** — Workload logic (Pebble layers, ports, config). **Zero `ops` dependency**. Must be testable with plain pytest.

Event objects must never be passed to `src/norma.py`. Extract data in the charm, pass primitives to the workload module.

### Holistic Reconciler Pattern

Every event (config-changed, relation-changed, pebble-ready, etc.) triggers `_reconcile()` which:
1. Reads all inputs (config, relations, workload state)
2. Computes complete desired state
3. Writes outputs (workload update, status)

Dedicated handlers are allowed **only** for: `stop`, `remove`, action events, and secret rotation/expiration.

### Subordinate Overlay Strategy (US25)

The test subordinate reuses the same charm source with a charmcraft overlay:

- **`charmcraft-subordinate.yaml`**: Sets `subordinate: true`, flips `juju-info` from provides to requires with `scope: container`, removes containers/resources/storage sections (subordinates share the principal's pod).
- **Build**: `charmcraft pack --project-dir . --charm-config charmcraft-subordinate.yaml` (or copy overlay as charmcraft.yaml in a temp dir and pack).
- **Principal changes**: Add `juju-info` provides endpoint to `charmcraft.yaml` (FR-027). No code changes needed — the charm already handles arbitrary relations via `_reconcile()`.

### Build Variants (CI Matrix)

| Variant | charmcraft.yaml | charm-user | Purpose |
|---------|----------------|------------|---------|
| Primary (default) | `charmcraft.yaml` | `non-root` (UID 170) | Production artifact, all standard tests |
| Subordinate | `charmcraft-subordinate.yaml` | `non-root` | US25: subordinate relation lifecycle |
| Sudoer | `charmcraft-sudoer.yaml` | `sudoer` (UID 171) | FR-031: validate Juju sudoer privilege mode |

### xfail Strategy for K8s Storage CLI Limitations

US10 AC4 (`attach-storage`), AC6 (`import-filesystem`), and AC7 (`deploy --attach-storage`) exercise Juju storage CLI operations that are not yet supported on K8s container models. Per clarification session 2026-02-18:

- Integration tests are written with `@pytest.mark.xfail(strict=False, reason="K8s container model storage CLI not yet supported")`
- Tests exist and run on every CI execution
- When Juju adds support, tests auto-pass and the `xfail` marker can be removed
- No charm code changes needed — the charm already handles `storage-attached` events

### Relation Endpoints (Updated)

| Endpoint | Type | Interface | Scope | Purpose |
|----------|------|-----------|-------|---------|
| `norma-peers` | peer | `norma_peers` | — | Leader coordination, secret ID sharing |
| `calibration-provider` | provides | `calibration` | — | US7: provides/requires relations |
| `metrics-endpoint` | provides | `prometheus_scrape` | — | US18: COS metrics |
| `grafana-dashboard` | provides | `grafana_dashboard` | — | US18: COS dashboards |
| `juju-info` | provides | `juju-info` | — | US25: subordinate attachment point |
| `calibration-requirer` | requires | `calibration` | — | US7: provides/requires relations |
| `log-proxy` | requires | `loki_push_api` | — | US18: COS log forwarding |

Note: The `juju-info` provides endpoint does NOT specify `scope: container` — scope is a requires-side attribute set in the subordinate's metadata.

### Storage Definitions

| Name | Type | Min Size | Mount Point | Required | Purpose |
|------|------|----------|-------------|----------|---------|
| `data` | filesystem | 1G | `/var/lib/norma` | Yes | US10: primary storage persistence |
| `logs` | filesystem | 512M | `/var/log/norma` | No (0-1) | US24: independent attach/detach testing |

### OCI Resources

| Resource | Current Name | Type | Registry |
|----------|-------------|------|----------|
| Workload image | `juju-norma-image` | oci-image | `localhost:32000/norma:0.1.0` (dev), `ghcr.io/canonical/norma:latest` (prod) |

### Actions (18 + introspect)

| Action | Story | Parameters | Purpose |
|--------|-------|------------|---------|
| `get-event-log` | US1 | limit, event-filter | Query event ledger |
| `get-config` | US3 | — | Return current config values |
| `set-status` | US4 | status, message | Force status for testing |
| `get-peer-data` | US6 | — | Query peer relation data |
| `get-relation-data` | US7 | endpoint, relation-id | Query relation data |
| `get-cluster-info` | US8 | — | Report cluster membership |
| `get-secret-info` | US9 | — | Report secret metadata |
| `check-storage` | US10/US24 | name | Check named storage status |
| `test-pebble-ops` | US12 | container | Full Pebble operation suite |
| `trigger-notice` | US13 | key, data | Send Pebble custom notice |
| `toggle-health` | US11 | container | Toggle health endpoint |
| `test-networking` | US14 | — | Report ports and bindings |
| `check-security` | US17 | — | Report UID/GID and trust |
| `get-version` | US15 | — | Report charm/workload version |
| `fail-action` | US5 | message | Intentionally fail |
| `test-defer` | US20 | arm | Arm/disarm event deferral |
| `run-check` | US2 | check | Validate a specific capability |
| `introspect` | US22 | sections | Comprehensive state report |

### Phase Organization

| Phase | Stories | Dependencies | Status |
|-------|---------|-------------|--------|
| 1: Setup | — | None | Complete |
| 2: Foundational | — | Phase 1 | Complete |
| 3-5: US1-US3 | P1-P3 | Phase 2 | US1-US2 complete, US3 partial |
| 6-7: US4-US5 | P4-P5 | US3 | Pending |
| 8-10: US6-US8 | P6-P8 | Phase 2 | Pending |
| 11: US9 | P9 | US6 | Pending |
| 12: US10 | P10 | Phase 2 | Pending |
| 13-15: US11-US13 | P11-P13 | US2 | US11 partial |
| 16-19: US14-US17 | P14-P17 | Phase 2 | US14 partial, US16 partial |
| 20-23: US18-US21 | P18-P21 | US7 (for CMR) | Pending |
| 25: US22 (Introspect) | P22 | US1-US9 | Pending |
| 26: US23 (Multi-Arch) | P23 | Phase 2 | Pending |
| 27: US24 (Multi-Storage) | P24 | US10 | Pending |
| 28: US25 (Subordinate) | P25 | FR-027 (juju-info endpoint) | **New** |
| O1: CI Pipeline | — | Phase 1 | Partial (ci.yaml exists) |
| O2: Integration Tests | — | Corresponding stories | Partial (files exist) |
| 24: Polish | — | All stories | Pending |

### Cross-Story Dependencies

| Story | Depends On | Reason |
|-------|-----------|--------|
| US4 (Status) | US3 (Config) | Status validation uses config validation |
| US8 (Scaling) | US6 (Peer) | Cluster info reads from peer relation |
| US9 (Secrets) | US6 (Peer) | Secret ID stored in peer app data |
| US11 (Health) | US2 (Pebble) | Health checks extend Pebble layer |
| US12 (Pebble Ops) | US2 (Pebble) | File/exec ops require connected container |
| US13 (Notices) | US2 (Pebble) | Notices sent via Pebble |
| US16 (Multi-Container) | US2 (Pebble) | Secondary container extends Pebble management |
| US19 (CMR) | US7 (Relations) | CMR uses calibration relation endpoints |
| US21 (Resource) | US2 (Pebble) | Resource refresh triggers pebble-ready |
| US22 (Introspect) | US1-US9 | Collectors read data populated by prior stories |
| US24 (Multi-Storage) | US10 (Storage) | Extends existing storage handling |
| US25 (Subordinate) | FR-027 | Requires juju-info provides endpoint |
| All stories | US1 (Lifecycle) | Event ledger used for verification |

### New Requirements Mapping (Post-Analysis)

These requirements were added after the original planning and need task coverage:

| Requirement | Story | Description |
|-------------|-------|-------------|
| FR-027 | US25 | Add `juju-info` provides endpoint for subordinate attachment |
| FR-028 | US12 | Add `container.send_signal()` to test-pebble-ops action |
| FR-029 | US1 | Integration test for `juju remove-application --force` |
| FR-030 | US10 | Integration tests for `import-filesystem` and `deploy --attach-storage` (xfail) |
| FR-031 | US17 | CI matrix for `charm-user: sudoer` build variant |
| FR-032 | US9 | Integration test for parallel secret operations |
| FR-033 | US14 | `juju expose`/`juju unexpose` support and integration tests |
| FR-034 | All | Model migration (`juju migrate`) integration test |
| FR-035 | US22 | `goal-state` section in introspect action |
| FR-036 | US1 | `update-status-hook-interval` model-config integration test |
| FR-037 | All | `juju ssh` connectivity and `--constraints` deployment integration tests |
| FR-038 | US23 | ROCK includes busybox shell (`/bin/sh`) for `juju exec`/`juju ssh` shell support |
| FR-039 | US17 | `credential-get` hook tool exercise in check-security action |
| FR-040 | US17 | Sudoer charmcraft overlay (`charmcraft-sudoer.yaml`) packed as third build variant |
| NFR-005 | All | Self-sufficiency meta-requirement (audit task in Polish phase) |
