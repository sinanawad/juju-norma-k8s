# Charm Anatomy: File-by-File Guide

This document explains every file in the juju-norma-k8s repository, what it does, and how the pieces connect. Use this when building a new Juju K8s charm to understand which files you need and what goes in each.

## Core Charm Files

### `charmcraft.yaml` — The Single Source of Metadata

This is the **only** metadata file. No `metadata.yaml`, no `config.yaml`, no `actions.yaml` — everything lives here since charmcraft 3.x.

```
charmcraft.yaml
├── type: charm                    # Always "charm"
├── name: juju-norma-k8s          # Charm name (always -k8s suffix for K8s charms)
├── base: ubuntu@24.04            # Build base
├── platforms: {amd64, arm64}     # Target architectures
├── parts:                        # Build recipe (uv plugin for Python)
├── assumes: [juju >= 3.6, k8s-api]  # Runtime requirements
├── containers:                   # Workload containers (Pebble-managed)
│   ├── norma:                    # Primary container
│   │   ├── resource: ...         # Links to OCI image resource
│   │   ├── uid/gid: 584792      # Non-root execution
│   │   └── mounts:              # Storage → container path mappings
│   └── norma-secondary:         # Additional container (same image, different port)
├── resources:                    # OCI images (deployed via juju attach-resource)
├── storage:                      # Persistent filesystem volumes
├── config:                       # All 5 Juju config types
│   └── options:
│       ├── string, int, float, boolean  # Standard types
│       └── secret                       # Secret URI (no default allowed)
├── actions:                      # 18 actions (one per feature area)
├── peers:                        # Peer relation for inter-unit data
├── provides:                     # Endpoints this charm offers
├── requires:                     # Endpoints this charm consumes
├── charm-libs:                   # COS libraries to fetch
├── charm-user: non-root          # Security: run charm code as UID 170
└── links:                        # Source and issue tracker URLs
```

**Key rules**:
- `charm-libs` entries use short names (`prometheus-k8s.prometheus_scrape`), never `charms.` prefix
- `secret`-type config cannot have a default value
- Container `uid`/`gid` sets the K8s `securityContext` — use 584792 for `_daemon_` on bare-base ROCKs
- Storage `multiple-range: 0-1` makes a storage optional

### `src/charm.py` — Juju Lifecycle (The Reconciler)

This file imports `ops` and handles all Juju events. Its architecture:

```
NormaK8sCharm(ops.CharmBase)
├── __init__()
│   ├── Observe ALL lifecycle events → _on_defer_gate → _reconcile
│   ├── Observe dedicated handlers (stop, remove, secret-rotate/expired/remove)
│   ├── Observe collect_unit_status / collect_app_status
│   ├── Observe ALL action events → dedicated _on_*_action handlers
│   └── Initialize COS library objects (MetricsEndpointProvider, etc.)
│
├── _reconcile(event)              # SINGLE ENTRY POINT for all lifecycle events
│   ├── Log event to ledger
│   ├── Update relation data (idempotent)
│   ├── If primary container connected:
│   │   ├── Validate config
│   │   ├── Resolve secret config (if set)
│   │   ├── Build & apply Pebble layer
│   │   ├── Set workload version
│   │   ├── Open ports
│   │   └── Write storage markers
│   └── If secondary container connected:
│       └── Build & apply secondary Pebble layer
│
├── Status collection (never sets status in handlers)
│   ├── _on_collect_unit_status()  # Pebble connected? → Active. Not? → Waiting.
│   └── _on_collect_app_status()   # Leader only
│
├── Action handlers (18 dedicated handlers)
│   └── Each returns structured results via event.set_results()
│
└── Helpers
    ├── _log_event()               # Append to event ledger
    ├── _update_relation_data()    # Idempotent relation writes
    └── _get_charm_version()       # Read version file
```

**Critical rules**:
- `_reconcile()` MUST NOT call `event.defer()` — deferral lives in `_on_defer_gate()`
- Never set status in lifecycle handlers — use `collect_unit_status` exclusively
- Never pass `ops` event objects to `norma.py` — extract primitive data first
- All relation data writes check for changes before writing (avoids feedback loops)

### `src/norma.py` — Workload Logic (Zero ops Dependency)

This file has **no import of ops**. It is testable with plain pytest. It provides:

```
norma.py
├── Constants
│   ├── CONTAINER_NAME, SECONDARY_CONTAINER
│   ├── DEFAULT_PORT, SECONDARY_PORT
│   ├── HEALTH_FLAG_FILE, BINARY_PATH
│   ├── STORAGE_CONFIG (dict mapping storage names → paths and markers)
│   └── LEDGER_FILE, DEFER_FLAG_FILE
│
├── Event ledger I/O
│   ├── read_event_ledger() → list[dict]
│   └── write_event_ledger(ledger)
│
├── Deferral flag I/O
│   ├── read_defer_armed() → bool
│   └── write_defer_armed(armed)
│
├── Config validation
│   └── validate_config(config) → (bool, error_message)
│
└── Pebble layer builders
    ├── build_pebble_layer(name, port, version) → dict
    └── build_secondary_layer(version) → dict
```

**Why this separation matters**: If you ever need to change the workload (different binary, different ports, different health check), you only touch `norma.py`. The charm lifecycle code in `charm.py` stays unchanged. This is the two-module separation principle.

## Workload Files

### `workload/main.go` — The Go Binary

A single-file Go HTTP server (~200 lines) that provides 5 endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Pebble HTTP check (returns 200 or 500 based on atomic flag + flag file) |
| `/version` | GET | JSON version response (version injected via ldflags) |
| `/ready` | GET | Simple readiness (always 200 when running) |
| `/metrics` | GET | Prometheus text exposition (`promhttp.Handler()`) |
| `/toggle-health` | POST | Flips health state atomically |

**Key design**: The health state has two mechanisms:
1. Atomic bool (toggled via HTTP POST)
2. Flag file existence (toggled by the charm via `container.push()`/`container.remove_path()`)

This dual approach works because chiselled containers have no shell — the charm can't `curl` but can manipulate files via Pebble.

### `workload/go.mod` — Go Dependencies

Only one external dependency: `github.com/prometheus/client_golang` for the `/metrics` endpoint. Built with `CGO_ENABLED=0` for a fully static binary (~8-12 MB).

### `rockcraft.yaml` — The OCI Image

Builds a chiselled (distroless) ROCK image:

```
rockcraft.yaml
├── base: bare                 # No OS, no shell, no package manager
├── build-base: ubuntu@24.04   # Build tools come from here
├── platforms: {amd64, arm64}  # Multi-architecture
├── run_user: _daemon_         # Default UID in the image
├── services:                  # Default Pebble service (overridden by charm layer)
│   └── norma: /bin/norma
├── parts:
│   ├── tmp-dir:               # /tmp directory (Pebble needs it)
│   └── norma:                 # Go binary build
│       ├── plugin: go
│       ├── build-snaps: [go/1.22/stable]
│       ├── CGO_ENABLED=0      # Static binary
│       └── override-build:    # Custom build for ldflags (go plugin doesn't support them)
```

**Pitfall**: The rockcraft Go plugin only supports `go-buildtags` and `go-generate`. For ldflags (version injection), you must use `override-build` with an explicit `go build` command.

**Pitfall**: `base: bare` has no NSS libraries. Pebble can't resolve usernames like `_daemon_`. Don't set `user: _daemon_` in Pebble layers — let the OCI image's `run_user` handle it, and set matching `uid`/`gid` in `charmcraft.yaml` containers.

## Build & Configuration Files

### `pyproject.toml` — Python Configuration

Single file for all Python tooling:

```toml
[project]
requires-python = ">=3.12"
dependencies = ["ops", "cosl", "pyyaml"]

[project.optional-dependencies]
dev = ["ops[testing]", "pytest", "coverage[toml]", "jubilant", "ruff"]

[tool.ruff]
line-length = 99
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "A", "SIM", "RUF"]

[tool.coverage.run]
source = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "lib"]    # Makes src/charm.py and lib/charms importable
```

**No `tox.ini`**, no `setup.py`, no `setup.cfg`. Everything in one file.

### `uv.lock` — Dependency Lock File

Managed by `uv` (not pip). Always committed. Regenerate with `uv lock`.

### `Makefile` — Build Commands

```makefile
lint:     uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
fmt:      uv run ruff format src/ tests/ && uv run ruff check --fix src/ tests/
unit:     uv run coverage run -m pytest tests/unit -v && uv run coverage report
integration: uv run pytest tests/integration -v --tb=short
clean:    rm -rf *.charm __pycache__ .coverage ...
```

### `CLAUDE.md` — AI Agent Instructions

Project-specific instructions for Claude Code. Contains build commands, architecture rules, constitutional prohibitions, and naming conventions. This file is automatically loaded when Claude Code opens the project.

## Test Files

### `tests/unit/test_charm.py` — Charm Unit Tests (ops.testing / Scenario)

Uses the declarative state-transition pattern:

```python
# 1. Create a Context with the charm class
ctx = ops.testing.Context(NormaK8sCharm)

# 2. Define input State (immutable)
state = ops.testing.State(
    containers=[NORMA_CONTAINER, NORMA_SECONDARY],
    config={"calibration-int": 9090},
)

# 3. Fire one event, get output State
out = ctx.run(ctx.on.config_changed(), state)

# 4. Assert on output State
assert out.unit_status == ops.ActiveStatus()
```

For introspecting charm internals (event ledger, etc.), use the context manager:

```python
with ctx(ctx.on.install(), state) as mgr:
    mgr.run()
    ledger = mgr.charm._event_ledger
    assert ledger[0]["event_name"] == "install"
```

### `tests/unit/test_norma.py` — Workload Module Tests (Plain pytest)

No ops imports. Tests `validate_config()`, `build_pebble_layer()`, event ledger I/O, etc. Proves the workload module is independently testable.

### `tests/unit/conftest.py` — Unit Test Fixtures

Autouse fixture that cleans the event ledger file between tests (prevents cross-test pollution).

### `tests/integration/conftest.py` — Integration Test Fixtures

Session-scoped fixtures providing a deployed charm instance. Supports 4 modes:
1. **Existing model** (`JUJU_MODEL=...`) — fastest for iteration
2. **Custom Juju binary** (`JUJU_CLI=~/go/bin/juju`) — for testing against local builds
3. **Auto-setup** (`SETUP_ENVIRONMENT=1`) — installs everything on a fresh machine
4. **Default** — `jubilant.temp_model()` with automatic cleanup

### `tests/integration/setup_env.py` — Environment Bootstrapper

Idempotent functions for installing microk8s, Juju snaps, and bootstrapping a controller. Called when `SETUP_ENVIRONMENT=1`.

## COS Observability Files

### `src/grafana_dashboards/norma.json`

Grafana dashboard template (auto-loaded by `GrafanaDashboardProvider`).

### `src/prometheus_alert_rules/norma_alerts.yaml`

Prometheus alert rules (auto-loaded by `MetricsEndpointProvider`).

### `lib/charms/` — Fetched Charm Libraries

Downloaded via `charmcraft fetch-libs`. Contains:
- `prometheus_k8s/v0/prometheus_scrape.py`
- `grafana_k8s/v0/grafana_dashboard.py`
- `loki_k8s/v1/loki_push_api.py`

These are vendored (committed to the repo), not installed as packages.

## CI/CD Files

### `.github/workflows/ci.yaml`

PR and dispatch workflow: lint → unit → pack → integration (matrix: Juju 3/stable + 4/stable).

## File Dependency Graph

```
charmcraft.yaml ← defines containers, config, actions, relations
    ↓
src/charm.py ← imports ops, imports norma, reads charmcraft.yaml implicitly
    ↓
src/norma.py ← zero ops dependency, provides constants + layer builders
    ↓
workload/main.go ← the actual binary that runs inside the container
    ↓
rockcraft.yaml ← builds the OCI image containing the Go binary
    ↓
tests/unit/test_charm.py ← uses ops.testing to test charm.py
tests/unit/test_norma.py ← uses plain pytest to test norma.py
tests/integration/ ← uses jubilant to test deployed charm
```

The key insight: `charmcraft.yaml` defines the contract (what containers exist, what config options exist, what actions exist). `charm.py` implements that contract using ops. `norma.py` provides the workload-specific logic without knowing about ops. The Go binary is the actual workload.
