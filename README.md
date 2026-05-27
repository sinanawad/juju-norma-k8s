# juju-norma-k8s

[![CharmHub](https://charmhub.io/juju-norma-k8s/badge.svg)](https://charmhub.io/juju-norma-k8s)
[![CI](https://github.com/sinanawad/juju-norma-k8s/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/sinanawad/juju-norma-k8s/actions/workflows/ci.yaml)
[![Publish to latest/edge](https://github.com/sinanawad/juju-norma-k8s/actions/workflows/publish-edge.yaml/badge.svg?branch=main)](https://github.com/sinanawad/juju-norma-k8s/actions/workflows/publish-edge.yaml)
[![Juju 3.6 / 4.0](https://img.shields.io/badge/juju-3.6%20%7C%204.0-blue)](https://juju.is)
[![License](https://img.shields.io/github/license/sinanawad/juju-norma-k8s)](LICENSE)

A comprehensive **Juju K8s calibration charm** that exercises every feature and capability relevant to Kubernetes charms. Designed as a self-sufficient CI validation suite for Juju itself, this single charm can replace all existing K8s sidecar test charms.

This repository also serves as a **reference implementation** for building Juju K8s charms. See [Reference Documentation](#reference-documentation) below.
## What is this?

`juju-norma-k8s` is not a production workload charm. It is a **test harness** — a purpose-built charm that systematically exercises all 25 Juju K8s features so that Juju's own CI can verify nothing is broken. Every feature is independently testable via dedicated actions, making it trivial to isolate regressions.

The charm bundles a minimal Go HTTP server (the "Norma" binary) as its workload, managed via Pebble inside a chiselled (distroless) ROCK image.

It is also a **canonical example** of how to build a production-quality Juju K8s charm — demonstrating the holistic reconciler pattern, two-module separation, non-root security, COS observability, and three-tier testing (unit/integration/CLI acceptance).

## Capabilities

### Lifecycle & Events
- Full charm lifecycle tracking (install, config-changed, start, leader-elected, update-status, stop, remove)
- In-memory event ledger queryable via the `get-event-log` action with filtering
- Event deferral testing (`test-defer` action) to validate Juju's defer/re-emit mechanism
- `update-status-hook-interval` model-config integration

### Pebble Workload Management
- Two containers (`norma`, `norma-secondary`) running the same ROCK image on different ports
- Pebble layer management, service start/stop/restart
- File push/pull, directory listing, exec commands, signal sending (`test-pebble-ops`)
- Custom Pebble notices (`trigger-notice`)
- HTTP health checks with togglable health state (`toggle-health`)
- Pebble check-failed and check-recovered event handling

### Configuration
- All five Juju config types: `string`, `int`, `float`, `boolean`, `secret`
- Secret-type config with `model.get_secret(id=...)` resolution
- Configuration change tracking via event ledger

### Status Reporting
- All four status types: Active, Blocked, Waiting, Maintenance
- `collect_unit_status` pattern (never sets status in individual handlers)
- Force any status via `set-status` action for testing

### Actions
- 18 dedicated actions covering every feature area
- Comprehensive `introspect` action returning structured JSON report of all internal state
- Intentional failure testing (`fail-action`)

### Relations
- **Peer relations** with leader-elected data sharing (`norma-peers`)
- **Provides/requires** with matching `calibration` interface for cross-app relations
- Relation data inspection via `get-relation-data` and `get-peer-data` actions
- Cross-model relations (CMR) via `juju offer` / `juju consume`

### Scaling
- Scale from 1 to N units with peer discovery
- Cluster membership reporting via `get-cluster-info`
- Leader election and data propagation

### Secrets
- App-owned Juju secrets (create, read, rotate, expire, revoke)
- Secret ID stored in peer relation data (never the secret value)
- `secret-changed`, `secret-rotate`, `secret-expired`, `secret-remove` event handling
- Secret-type config option (`calibration-secret`)

### Storage
- Two named filesystem storages: `data` (1G, required) and `logs` (512M, optional)
- Storage lifecycle events (attached, detaching)
- Data persistence verification via `check-storage` action
- Independent attach/detach testing for optional storage

### Networking & Expose
- Port opening/closing via Juju model
- Network binding information reporting (`test-networking`)
- `juju expose` / `juju unexpose` with LoadBalancer/NodePort service creation
- Exposed status reporting in action output

### Security
- Non-root charm execution (`charm-user: non-root`)
- Container UID/GID 584792 (`_daemon_`)
- Chiselled (distroless) ROCK image — no shell, no package manager
- Security posture reporting via `check-security` action
- Sudoer build variant for CI privilege mode testing

### Observability (COS)
- Prometheus metrics endpoint (`/metrics` on workload, `prometheus_scrape` relation)
- Grafana dashboard (shipped in `src/grafana_dashboards/`)
- Loki log forwarding (`loki_push_api` relation)
- Prometheus alert rules (shipped in `src/prometheus_alert_rules/`)
- Custom workload metrics: `norma_http_requests_total`, `norma_health_toggles_total`, `norma_healthy`

### OCI Resource Lifecycle
- `juju attach-resource` for image updates
- Version tracking across charm refresh cycles
- Multi-architecture image support (amd64 + arm64)

### Juju Operations on K8s Charms
- `juju expose` / `juju unexpose`
- `juju ssh` (exec-via-API into K8s pods)
- `juju deploy --constraints` (K8s resource requests/limits)
- `juju model-config update-status-hook-interval`
- `juju migrate` (model migration between controllers)
- `goal-state` hook tool (introspect action section)

### Introspection
- Comprehensive `introspect` action with selectable sections:
  `config`, `leadership`, `relations`, `storage`, `containers`, `secrets`, `event-ledger`, `network`, `goal-state`
- Each section reports independently with graceful degradation
- Truncation support for large payloads (>250KB)

## Architecture

```
src/charm.py       Juju lifecycle (holistic reconciler pattern)
src/norma.py       Workload logic (zero ops dependency)
workload/main.go   Static Go HTTP server (health, version, metrics, toggle)
rockcraft.yaml     Chiselled ROCK (bare base, ~15MB)
charmcraft.yaml    Charm metadata, actions, config, relations, storage
```

**Key design principle**: All events route to a single `_reconcile()` method. No `StoredState`, no `event.defer()` for control flow. Status set exclusively via `collect_unit_status`.

## Prerequisites

- Juju 3.6+ with a Kubernetes cloud (MicroK8s recommended)
- Go 1.22+ (workload binary)
- `charmcraft` and `rockcraft` (snaps)
- `uv` (Python dependency management)
- `podman` or `skopeo` (OCI image management)

## Quick Start

### Build the ROCK image

```bash
rockcraft pack
# Upload to local registry
rockcraft.skopeo --insecure-policy copy \
    oci-archive:juju-norma_0.1.0_amd64.rock \
    docker://localhost:32000/juju-norma:0.1.0 \
    --dest-tls-verify=false
```

### Build and deploy the charm

```bash
uv sync
charmcraft fetch-libs
charmcraft pack

juju deploy ./juju-norma-k8s_ubuntu-24.04-amd64.charm \
    --resource juju-norma-image=localhost:32000/juju-norma:0.1.0 \
    --trust

juju status --watch 2s
```

### Verify

```bash
# Lifecycle events
juju run juju-norma-k8s/0 get-event-log

# Configuration
juju config juju-norma-k8s calibration-string="hello"
juju run juju-norma-k8s/0 get-config

# Health toggle
juju run juju-norma-k8s/0 toggle-health
juju run juju-norma-k8s/0 toggle-health  # restore

# Full introspection
juju run juju-norma-k8s/0 introspect

# Security posture
juju run juju-norma-k8s/0 check-security
```

## Development

```bash
make lint       # ruff check + format
make fmt        # auto-fix formatting
make unit       # pytest with coverage
make integration  # jubilant integration tests (requires Juju)
make clean      # remove build artifacts
```

### Self-contained integration tests

```bash
# Auto-installs microk8s, juju, bootstraps controller
SETUP_ENVIRONMENT=1 make integration

# Use a specific Juju version
JUJU_CHANNEL=3/stable SETUP_ENVIRONMENT=1 make integration

# Reuse existing deployment for fast iteration
JUJU_MODEL=my-model make integration
```

## Actions Reference

| Action | Description |
|--------|-------------|
| `get-event-log` | Query the in-memory event ledger (supports `limit` and `event-filter`) |
| `get-config` | Return current effective configuration |
| `set-status` | Force a specific status condition (`active`, `blocked`, `waiting`, `maintenance`) |
| `get-peer-data` | Return peer relation data from all units |
| `get-relation-data` | Return relation data for a specific endpoint |
| `get-cluster-info` | Report cluster membership information |
| `get-secret-info` | Report app-owned secret metadata |
| `check-storage` | Check storage status and data integrity (`data` or `logs`) |
| `test-pebble-ops` | Run full Pebble file/exec/service operation suite |
| `trigger-notice` | Send a Pebble custom notice from the workload container |
| `toggle-health` | Toggle workload health endpoint between healthy/unhealthy |
| `test-networking` | Report open ports, bindings, and expose status |
| `check-security` | Report UID/GID, trust status, and credential info |
| `get-version` | Return charm and workload version |
| `fail-action` | Intentionally fail with a given message |
| `test-defer` | Arm/disarm event deferral for the next eligible event |
| `run-check` | Validate a specific charm capability |
| `introspect` | Comprehensive structured report of all internal state |

## Relations

| Endpoint | Type | Interface | Purpose |
|----------|------|-----------|---------|
| `norma-peers` | peer | `norma_peers` | Leader coordination, secret ID sharing |
| `calibration-provider` | provides | `calibration` | Provides/requires relation testing |
| `calibration-requirer` | requires | `calibration` | Provides/requires relation testing |
| `metrics-endpoint` | provides | `prometheus_scrape` | COS Prometheus metrics |
| `grafana-dashboard` | provides | `grafana_dashboard` | COS Grafana dashboards |
| `log-proxy` | requires | `loki_push_api` | COS Loki log forwarding |
| `juju-info` | provides | `juju-info` | Standard Juju info endpoint |

## Build Variants

| Variant | Config | Purpose |
|---------|--------|---------|
| **Principal** (default) | `charmcraft.yaml` | Primary charm with `charm-user: non-root` |
| **Sudoer** | `charmcraft-sudoer.yaml` | CI-only variant with `charm-user: sudoer` privilege mode |

## Reference Documentation

This repo doubles as a reference implementation for building Juju K8s charms. The `docs/reference/` directory contains four guides designed for both humans and AI agents building new charms:

| Document | What it answers |
|----------|----------------|
| [**Charm Anatomy**](docs/reference/charm-anatomy.md) | What files do I need and what goes in each? File-by-file walkthrough of the entire repo. |
| [**Patterns**](docs/reference/patterns.md) | Show me the code for implementing feature X. 18 patterns with annotated code extracted from this repo: reconciler, Pebble, config, relations, storage, actions, secrets, status, observability, security, testing. |
| [**Scaffold**](docs/reference/scaffold.md) | How do I start from zero? Minimal viable charm, then a decision matrix and step-by-step guides for adding each feature. |
| [**Pitfalls**](docs/reference/pitfalls.md) | What will I get wrong? Every real mistake made during this build, with explanations and fixes. |

**To build a new charm using this reference**: Read `scaffold.md` to understand the project skeleton. Check the decision matrix for which features you need. Read the corresponding sections in `patterns.md` for annotated code. Check `pitfalls.md` before shipping.

## License

Apache-2.0
