# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

juju-norma-k8s is a Kubernetes Juju charm for the Norma workload, built with the `ops` framework (Python 3.10+). The project uses a specification-driven development workflow (SpecKit) where features progress through: `/speckit.specify` → `/speckit.plan` → `/speckit.tasks` → `/speckit.implement`.

All development is governed by the **constitution** at `.specify/memory/constitution.md` (v1.0.0). The constitution supersedes all other practices — never contradict it.

## Build & Development Commands

```bash
make lint              # ruff check + format check on src/ and tests/
make format            # ruff auto-fix + format on src/ and tests/
make unit              # pytest tests/unit with coverage (PYTHONPATH=src:lib)
make integration       # pytest tests/integration (requires Juju controller)
charmcraft pack        # build the .charm artifact
charmcraft fetch-libs  # pull declared charm libraries
make clean             # remove build artifacts
```

Dependencies managed with `uv` (not pip/tox). `uv.lock` must be committed. Single config in `pyproject.toml`. Linting uses `ruff` exclusively (line-length 99, py310).

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

### Status Reporting

Use `collect_unit_status` / `collect_app_status` events exclusively. Never set status in individual handlers. Priority: BlockedStatus > MaintenanceStatus > WaitingStatus > ActiveStatus. Use `ActiveStatus()` with **no message**.

### Project Layout

```
charmcraft.yaml          # sole metadata file (no metadata.yaml)
pyproject.toml / uv.lock / Makefile
rockcraft.yaml           # chiselled ROCK (distroless OCI image)
src/charm.py             # charm lifecycle
src/norma.py             # workload logic (ops-free)
src/grafana_dashboards/  # JSON dashboard templates
src/prometheus_alert_rules/
lib/charms/              # fetched charm libraries
tests/unit/              # ops.testing (Scenario) + plain pytest
tests/integration/       # jubilant tests
```

## Constitutional Prohibitions

These are **hard rules** — never introduce them:

- `event.defer()` as control flow (reconciler handles all state)
- `StoredState` (lost on K8s pod recreation; use peer relations instead)
- Blocking operations in handlers (sleep, polling loops)
- `ActiveStatus` with a message
- `ErrorStatus` for recoverable issues (use `BlockedStatus`)
- Passing `ops` event objects to non-charm code
- Hardcoded values (use config or relation data)
- Legacy Harness for testing (use `ops.testing` / Scenario)
- `pytest-operator` for integration tests (use `jubilant`)
- `flake8`/`black`/`isort` (use `ruff`)
- `tox.ini` (use `Makefile`)

## Testing

**Unit tests** (`ops.testing` / Scenario): Declarative state-transition tests. Each test fires one event against an immutable input `State` and asserts on output `State`. Workload module tests (`test_norma.py`) use plain pytest with no ops mocking.

**Integration tests** (`jubilant`): Real deployments using `jubilant.temp_model()`. Synchronous API. Run with `CHARM_PATH=<path> make integration`.

**CLI Acceptance (Constitution VIII)**: Every user story MUST be verified against a live Juju deployment via CLI (`juju run`, `juju config`, `juju status`, etc.) before it is considered done. Unit tests alone are insufficient — they cannot catch bugs that only manifest across event dispatches.

## State Management

No `StoredState`. When state is needed, prefer in order:
1. Re-read from workload/environment
2. Peer relation data (leader writes to `relation.data[self.app]`)
3. Juju storage
4. Database relations

Sensitive values use Juju Secrets — store the secret **ID** in peer data, never the secret value.

## Security Requirements

All mandatory: `charm-user: non-root` in charmcraft.yaml, container uid/gid set, `secrets.token_urlsafe()` for passwords, TLS via `tls-certificates` relation, chiselled ROCKs for images, no sensitive data in logs.

## Observability (COS Stack)

Every charm must integrate: `prometheus_scrape` (metrics), `grafana_dashboard` (dashboards in `src/grafana_dashboards/`), `loki_push_api` (logs), `parca_scrape` or `tracing` (profiling). Alert rules ship in `src/prometheus_alert_rules/`.

## SpecKit Workflow

Feature development follows the specification-driven workflow via slash commands:

1. `/speckit.specify` — Create feature spec from natural language
2. `/speckit.clarify` — Identify and resolve underspecified areas
3. `/speckit.plan` — Generate implementation plan with constitution check
4. `/speckit.tasks` — Generate dependency-ordered task list
5. `/speckit.checklist` — Generate requirements quality checklist
6. `/speckit.analyze` — Cross-artifact consistency analysis
7. `/speckit.implement` — Execute tasks phase-by-phase
8. `/speckit.constitution` — Manage the project constitution

Feature specs, plans, and tasks live under `specs/<NNN>-<feature-name>/`. Reference materials are in `.specify/memory/` (charm-patterns, testing-patterns, cicd-and-tooling, zinc-k8s-reference).

## Naming Conventions

- Charm name: `norma-k8s` (always `-k8s` suffix)
- Event handlers: `_on_<event_name>` (private, underscore prefix)
- Config options: dashes in YAML, underscores in Python
- Charm libraries: `lib/charms/<charm_name>/v<N>/<library>.py`

## CI/CD

GitHub Actions with `canonical/charming-actions`. PR workflow: lint → unit → lib-check → pack → integration. Release publishes to CharmHub edge. OCI workflow builds chiselled ROCKs. Dependabot covers Actions + uv deps.

## Active Technologies
- Python 3.12+ (charm, ubuntu@24.04), Go 1.22+ (workload binary) (001-calibration-charm)
- `ops` (charm framework), `ops[testing]` (unit tests), standard library `json` for serialization (001-calibration-charm)
- Juju filesystem storage (PersistentVolume, two named storages: data + logs), peer relation data (001-calibration-charm)

## Recent Changes
- 001-calibration-charm: Added Python 3.12+ (charm, ubuntu@24.04), Go 1.22+ (workload binary) + `ops` (charm framework), `ops[testing]` (unit tests),
