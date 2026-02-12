<!--
  Sync Impact Report
  ===================
  Version change: 1.0.0 -> 1.1.0
  Modified principles: None
  Added sections:
    - Principle VIII: CLI Acceptance Verification
  Removed sections: None
  Templates requiring updates:
    - .specify/templates/plan-template.md ✅ reviewed (Constitution Check
      section dynamically filled; new principle auto-included)
    - .specify/templates/spec-template.md ✅ reviewed (no changes needed)
    - .specify/templates/tasks-template.md ✅ reviewed (no changes needed;
      CLI verification is a workflow gate, not a task template change)
    - .specify/templates/agent-file-template.md ✅ reviewed (no changes needed)
  Follow-up TODOs: None
-->

# juju-norma-k8s Constitution

## Core Principles

### I. Holistic Reconciler Architecture

All charm event handling MUST follow the holistic/reconciler pattern.
Multiple events (config-changed, relation-changed, pebble-ready, etc.)
MUST route to a single `_reconcile()` method that:

- Reads all inputs (config, relations, workload state)
- Computes the complete desired state
- Writes outputs (updates workload, sets status)
- Returns early with appropriate status when preconditions are unmet

This pattern eliminates excessive `event.defer()` usage. The event
payload SHOULD be ignored; the charm reads all necessary state directly.

Dedicated handlers are permitted ONLY for: `stop`, `remove`, action
events, and secret rotation/expiration events.

**Rationale**: The delta pattern (one handler per event) leads to
status overwriting, deferred event accumulation, and ordering bugs.
The holistic pattern treats every event as a trigger to reconcile
the full desired state.

### II. Workload Abstraction

Workload-specific logic MUST live in a dedicated module (`src/norma.py`)
that has ZERO dependency on `ops` or any Juju framework code.

- `src/charm.py` handles Juju lifecycle, relations, and status
- `src/norma.py` handles Pebble layer construction, port definitions,
  version detection, and workload configuration
- The workload module MUST be independently testable with plain pytest
- Event objects MUST NOT be passed to workload code; extract data first

**Rationale**: Decoupling workload logic from the charm framework
enables pure-Python unit testing without mocking the Juju model,
and makes the workload module reusable across charm versions.

### III. Stateless by Default

Charms MUST NOT use `StoredState` for persistent data. StoredState is
lost on K8s container recreation, making it fundamentally unreliable.

When state is required, use this priority order:

1. Re-read from the workload or environment (preferred)
2. Peer relation data (persists for application lifetime)
3. Juju storage (for filesystem-backed persistence)
4. Database relations (for structured persistent data)

Peer relation data rules:

- Only the leader writes to `relation.data[self.app]`
- Values MUST be strings (serialize complex data to JSON)
- Store Juju secret IDs (not secret values) in peer data

**Rationale**: K8s pods are ephemeral. Any state mechanism tied to
the charm container is unreliable. Peer relations survive pod churn
and leader failover.

### IV. Security-First

All security measures are mandatory, not optional hardening:

- `charm-user: non-root` MUST be set in `charmcraft.yaml`
- Container `uid`/`gid` MUST be set for non-root Pebble execution
- Sensitive data MUST use Juju secrets (3.0+); NEVER hardcode
  passwords, API keys, or certificates
- Password generation MUST use `secrets.token_urlsafe()`
- TLS MUST be supported via the `tls-certificates` relation interface
- OCI images MUST be chiselled ROCKs (distroless, minimal attack
  surface) built from `rockcraft.yaml`
- Sensitive data MUST NOT appear in logs, traces, or exceptions

**Rationale**: Kubernetes workloads operate in shared environments.
Non-root execution, secret management, and minimal images reduce
the blast radius of any compromise.

### V. Observable by Design

Every charm MUST integrate with the Canonical Observability Stack (COS):

- `prometheus_scrape` relation (metrics endpoint)
- `grafana_dashboard` relation (ship dashboards as JSON templates
  in `src/grafana_dashboards/`)
- `loki_push_api` relation (log forwarding)
- `parca_scrape` or `tracing` relation (profiling/tracing)

Additional requirements:

- Prometheus alert rules MUST ship in `src/prometheus_alert_rules/`
- Use Python standard `logging` module at appropriate levels
- Juju topology labels are auto-enriched by COS; do not duplicate

**Rationale**: Observability is not an afterthought. Charms that lack
metrics, logs, and dashboards are undeployable in production
environments using the COS stack.

### VI. Three-Tier Testing

Testing MUST follow three tiers with specific tooling:

1. **Unit tests** (`ops.testing` / Scenario): Declarative
   state-transition tests. Each test fires exactly one event against
   an immutable input State and asserts on the output State. Install
   via `ops[testing]`. NEVER use legacy Harness.
2. **Integration tests** (`jubilant`): Real deployments against a Juju
   controller using `jubilant.temp_model()`. Synchronous API. NEVER
   use `pytest-operator`.
3. **Lint** (`ruff`): Single tool for linting and formatting. No
   flake8, black, or isort. Coverage via `coverage[toml]`.

Test organization:

- `tests/unit/test_charm.py` for charm lifecycle tests
- `tests/unit/test_norma.py` for workload module tests (plain pytest)
- `tests/integration/` for deployment tests

**Rationale**: State-transition testing catches event-handling bugs
without mocking Juju internals. Jubilant avoids the async/websocket
failures of pytest-operator. Ruff consolidates multiple linting tools.

### VII. Simplicity & Idempotency

Every event handler MUST be idempotent: safe to re-run with identical
results. Handlers MUST base decisions on current model state, not on
the specific event that triggered them.

The following anti-patterns are PROHIBITED:

- `event.defer()` as a primary control flow mechanism
- `StoredState` for any persistent data
- Blocking operations in handlers (sleep, polling loops)
- Setting status in individual handlers (use `collect_unit_status`)
- `ActiveStatus` with a message (the message adds no information)
- `ErrorStatus` for recoverable issues (use `BlockedStatus`)
- Hardcoded values (use config or relation data)
- Passing `ops` event objects to non-charm code

**Rationale**: Juju charms execute in a reactive, event-driven model
where events may arrive in any order and may repeat. Idempotency and
simplicity are the only reliable strategies.

### VIII. CLI Acceptance Verification

Every user story MUST be verified against a live Juju deployment using
the Juju CLI before it is considered complete. Unit tests alone are
insufficient — they execute within a single charm instance lifetime
and cannot catch bugs that manifest across event dispatches (e.g.,
state not persisting between events, actions returning stale data).

Acceptance workflow for each user story:

1. Unit tests pass (`make unit`)
2. Charm is deployed to a test model (`juju deploy`)
3. The user story is exercised via CLI commands (`juju run`,
   `juju config`, `juju status`, `juju relate`, etc.)
4. CLI output is verified against the acceptance criteria in the spec

A user story that passes unit tests but fails CLI verification is
**not done** — the implementation MUST be fixed before proceeding.

**Rationale**: This charm exists as a calibration standard for Juju CI.
If a feature cannot be verified through the same CLI that CI uses, it
provides no value. The event ledger bug (in-memory list that resets on
every dispatch) proved that unit tests can pass while the feature is
completely non-functional in production.

## Technology Stack & Tooling

**Language**: Python 3.10+ with the `ops` framework (CharmBase)

**Build & Dependencies**:

- `uv` for all dependency management (build plugin, lock file, venvs)
- `uv.lock` MUST be committed to version control for reproducibility
- `pyproject.toml` as the single dependency declaration file
- `Makefile` for all build/test targets (no tox.ini)
- Charm libraries declared in `charmcraft.yaml` under `charm-libs`
- `charmcraft fetch-libs` for library management

**Charm Metadata**:

- `charmcraft.yaml` is the ONLY metadata file authors edit
- Charm name MUST use the `-k8s` suffix (e.g., `norma-k8s`)
- `assumes` MUST declare minimum Juju version and `k8s-api`
- All relation endpoints MUST declare `optional` and `limit`
- `base: ubuntu@24.04` as the target base

**Workload**:

- Pebble for process supervision in sidecar containers
- `add_layer(combine=True)` + `replan()` for all workload changes
- Health checks (HTTP/TCP) mapped to K8s liveness/readiness probes
- `override: replace` and `startup: enabled` for service definitions
- Wrap all Pebble operations in try/except for ConnectionError

**Project Layout**:

```text
charmcraft.yaml
pyproject.toml
uv.lock
Makefile
rockcraft.yaml
src/
  charm.py
  norma.py
  grafana_dashboards/
  prometheus_alert_rules/
  loki_alert_rules/
lib/charms/
tests/
  unit/
  integration/
```

**Status Reporting**:

- Use `collect_unit_status` / `collect_app_status` events exclusively
- Priority: BlockedStatus > MaintenanceStatus > WaitingStatus > ActiveStatus
- `ActiveStatus()` with NO message
- `BlockedStatus` for operator-fixable issues

## Development Workflow & CI/CD

**Local Development**:

1. `charmcraft init --profile kubernetes` for scaffolding
2. `charmcraft fetch-libs` to pull declared charm libraries
3. `make lint` for ruff checks
4. `make unit` for ops.testing state-transition tests
5. `charmcraft pack` to build the .charm file
6. `make integration` for jubilant deployment tests

**Naming Conventions**:

- Event handlers: `_on_<event_name>` (private, underscore prefix)
- Handler order in `__init__` MUST match declaration order
- Config options: dashes in YAML, underscores in Python
- Charm libraries: `lib/charms/<charm_name>/v<N>/<library>.py`

**CI/CD (GitHub Actions)**:

- PR workflow: lint, unit test, lib-check, pack, integration tests
- Release workflow: test + upload to CharmHub (edge channel)
- OCI workflow: build chiselled ROCK, push to container registry
- Weekly automation: charm library updates + upstream dep checks
- Use `canonical/charming-actions` for CharmHub operations
- Dependabot for GitHub Actions and uv dependencies

**Relations & Integrations**:

- Search `charm-relation-interfaces` repository before creating
  new interfaces
- Use charm libraries for all relation handling
- Only the leader writes to application-level databag
- Use Juju Secrets for credential sharing (store secret ID in
  peer relation data, not the secret value)

## Governance

This constitution supersedes all other development practices for
the juju-norma-k8s project. All code contributions MUST comply
with these principles.

**Amendment Process**:

1. Propose changes via pull request modifying this file
2. Document rationale for each change
3. Update version following semantic versioning:
   - MAJOR: Principle removal or backward-incompatible redefinition
   - MINOR: New principle added or existing principle materially expanded
   - PATCH: Clarifications, wording fixes, non-semantic refinements
4. Update LAST_AMENDED_DATE to the date of merge

**Compliance**:

- All PRs MUST be reviewed against these principles
- Constitution Check in plan.md MUST pass before implementation
- Violations MUST be documented and justified in the Complexity
  Tracking section of the implementation plan
- Use CLAUDE.md for runtime development guidance that supplements
  (but never contradicts) this constitution

**Version**: 1.1.0 | **Ratified**: 2026-02-10 | **Last Amended**: 2026-02-12
