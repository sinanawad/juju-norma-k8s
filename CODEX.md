# CODEX.md

Instructions for OpenAI Codex when reviewing or working with this repository.

## Project Purpose

This is a **calibration charm** — its explicit goal is to exercise **every** Juju K8s charm feature for CI validation. Features that would be anti-patterns in a production charm are intentionally present here as test instrumentation. Review findings must account for this context.

## Constitution

All development is governed by the constitution at `.specify/memory/constitution.md` (v1.1.0, 8 principles). The constitution supersedes all other practices.

Key principles:

1. **Holistic Reconciler** — All lifecycle events route to `_reconcile()`. Dedicated handlers only for: `stop`, `remove`, actions, secret rotation/expiration, and the deferral gate (`_on_defer_gate`).
2. **Workload Abstraction** — `src/norma.py` has zero `ops` dependency. Event objects never cross into it.
3. **Stateless by Default** — No `StoredState`. Peer relation data for persistence. Secret IDs (not values) in peer data.
4. **Security-First** — `charm-user: non-root`, container uid/gid 584792 (`_daemon_`), chiselled ROCK, `secrets.token_urlsafe()`.
5. **Observable by Design** — prometheus_scrape, grafana_dashboard, loki_push_api integrations.
6. **Three-Tier Testing** — `ops.testing`/Scenario for unit, `jubilant` for integration, `ruff` for lint. No Harness, no pytest-operator, no flake8/black.
7. **Simplicity & Idempotency** — No `event.defer()` as control flow, no `StoredState`, no blocking ops, no `ActiveStatus` with message.
8. **CLI Acceptance** — Every user story verified via live Juju CLI before done.

## Documented Exceptions (Do NOT Flag These)

These are justified violations tracked in `specs/001-calibration-charm/plan.md` Complexity Tracking. They have been reviewed and approved. Do not report them as findings.

### 1. `event.defer()` in `_on_defer_gate()` (Principle VII exception)

**What**: `src/charm.py` calls `event.defer()` inside `_on_defer_gate()`, a dedicated pre-reconcile handler.

**Why**: User Story 20 (Event Deferral) exists specifically to test Juju's deferral mechanism — defer, re-emit ordering, and non-deferrable event rejection. This is the calibration charm's purpose: to exercise ALL Juju features including deferral.

**Constraints**: The call is action-triggered only (requires explicit `juju run norma-k8s/0 test-defer arm=true`), isolated to US20, never used as charm control flow, and lives outside `_reconcile()` in a dedicated handler.

### 2. No `tls-certificates` relation (Principle IV exception)

**What**: The charm does not implement TLS via the `tls-certificates` interface.

**Why**: The charm tests Juju primitives (lifecycle, config, relations, secrets, Pebble), not infrastructure security patterns. TLS uses standard relations already covered by US7/US19. Adding TLS would increase deployment complexity without validating any new Juju mechanism.

### 3. No `parca_scrape`/`tracing` relation (Principle V exception)

**What**: The charm does not integrate with Parca or tracing backends.

**Why**: Profiling and tracing charm libraries are not yet stable. The charm validates COS observability via the three established pillars (Prometheus, Grafana, Loki) in US18.

## Architecture

```
Event → _on_defer_gate()  → [if defer armed: log + defer + return]
                           → [else: _reconcile()]

_reconcile()  — MUST NOT call event.defer(). Pure reconciliation only.
```

- `src/charm.py` — Juju lifecycle, relations, status, actions (~940 lines)
- `src/norma.py` — Workload logic, zero ops dependency (~160 lines)
- `tests/unit/test_charm.py` — ops.testing/Scenario tests (~1930 lines)
- `tests/unit/test_norma.py` — Plain pytest for workload module

## Prohibitions (Flag These)

These are hard rules with NO exceptions:

- `StoredState` anywhere
- Blocking operations in handlers (`sleep`, polling loops)
- `ActiveStatus` with a message (use `ActiveStatus()` with no args)
- `ErrorStatus` for recoverable issues (use `BlockedStatus`)
- Passing `ops` event objects to `src/norma.py`
- Hardcoded config values (use `self.config` or relation data)
- `event.defer()` inside `_reconcile()` (deferral gate is the only permitted location)
- Legacy Harness in tests (use `ops.testing` / Scenario)
- `pytest-operator` (use `jubilant`)
- `flake8`/`black`/`isort` (use `ruff`)
- `tox.ini` (use `Makefile`)
- Sensitive data in logs, traces, or action results

## Code Review Patterns

Recurring feedback to check for:

- **Pebble race conditions**: `can_connect()` returning True does not guarantee subsequent calls succeed. All Pebble operations must be wrapped in try/except for `ConnectionError`.
- **Relation data feedback loops**: Never write volatile values (timestamps, counters) to relation databags inside the reconciler. Only write stable, derived values with diff-check guards.
- **Relation data before Pebble check**: Relation databag writes must happen before the `container.can_connect()` gate, not after.
- **Revoke-then-grant in same hook**: When revoking a secret on `relation-broken`, the broken relation is still visible in `self.model.relations`. Pass it as a parameter and skip it in grant loops.

## Spec Artifacts

- `specs/001-calibration-charm/spec.md` — 22 user stories, 24 FRs, 8 success criteria
- `specs/001-calibration-charm/plan.md` — Implementation plan with constitution check
- `specs/001-calibration-charm/tasks.md` — 93 tasks across 25 phases
- `.specify/memory/constitution.md` — Project constitution v1.1.0

## Build & Test

```bash
make lint       # ruff check + format
make unit       # pytest tests/unit with coverage
make format     # ruff auto-fix
```
