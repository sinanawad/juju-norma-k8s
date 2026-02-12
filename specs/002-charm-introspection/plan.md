# Implementation Plan: Charm Introspection Action

**Branch**: `002-charm-introspection` | **Date**: 2026-02-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-charm-introspection/spec.md`

## Summary

Add a single `introspect` action to the norma-k8s charm that returns a comprehensive, structured report of all internal charm state — event ledger, configuration, relations, storage, containers, leadership, secrets (metadata only), version, and unit identity. The action supports optional section filtering and degrades gracefully when subsystems are unavailable. This provides CI pipelines with a programmatic way to assert on charm internals beyond what `juju status` exposes.

## Technical Context

**Language/Version**: Python 3.12 (ubuntu@24.04 base, `requires-python = ">=3.12"`)
**Primary Dependencies**: ops 3.5.2, standard library `json` for serialization
**Storage**: N/A (read-only action, no new storage)
**Testing**: ops.testing/Scenario for unit tests, jubilant for integration tests, ruff for lint
**Target Platform**: K8s charm on ubuntu@24.04 via charmcraft
**Project Type**: Single project (existing charm)
**Performance Goals**: Action completes in under 5 seconds regardless of charm state
**Constraints**: Juju action result values are strings; complex data must be JSON-encoded. Action result total size limited by Juju controller (typically ~300KB).
**Scale/Scope**: Single action handler, ~150-200 lines of new code

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Holistic Reconciler | PASS | Action handlers are explicitly permitted as dedicated handlers. `introspect` does not participate in reconciliation. |
| II. Workload Abstraction | PASS | Report-building reads Juju model state (ops-dependent) so it lives in `charm.py`. Workload constants (container names, ports) are read from `norma.py`. No ops leakage into workload module. |
| III. Stateless by Default | PASS | Read-only action. No StoredState. Reads current model state directly. |
| IV. Security-First | PASS | FR-008: secrets section returns metadata only (URI, label, revision, owner). No secret content in output. |
| V. Observable by Design | PASS | N/A — no new workload services or metrics endpoints. Action results are logged by Juju automatically. |
| VI. Three-Tier Testing | PASS | Unit tests via ops.testing (fire action event, assert on action_results). Integration test via jubilant (deploy, run action, parse output). |
| VII. Simplicity & Idempotency | PASS | Pure read-only action. Inherently idempotent. No side effects. |
| VIII. CLI Acceptance Verification | PASS | Each user story has a dedicated CLI verification task. US1: deploy and run `juju run norma-k8s/0 introspect`, verify all 9 sections. US2: run with `sections=config,leadership`, verify filtering. |

**Gate result**: ALL PASS (8/8 principles). No violations. No Complexity Tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/002-charm-introspection/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output (minimal — no unknowns)
├── data-model.md        # Phase 1 output (report section schema)
├── quickstart.md        # Phase 1 output (how to test the action)
├── contracts/           # Phase 1 output (action schema)
│   └── introspect-action.yaml
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (from /speckit.tasks)
```

### Source Code (repository root)

```text
src/
  charm.py          # Add introspect action handler + section collectors
  norma.py          # No changes (constants already available)
tests/
  unit/
    test_charm.py   # Add introspect action unit tests
  integration/
    test_introspect.py  # Integration test (deploy + run action + parse)
charmcraft.yaml     # Add introspect action definition
```

**Structure Decision**: All new code fits within existing files. The action handler and section collector functions go in `charm.py` following the established pattern. No new modules needed — this avoids unnecessary file proliferation for what is essentially one action handler with helper functions.

## Implementation Approach

### Action Design

The `introspect` action handler collects data from each subsystem into a dict of sections, then serializes each section as a JSON string in the action results. This matches the existing pattern used by `get-event-log`.

Section collectors are individual private methods on the charm class, each returning a dict for its domain. This makes them independently testable and easy to extend.

### Section Collectors

Each collector follows the pattern: try to read state, return data dict on success, return `{"status": "unavailable", "reason": "..."}` on failure.

| Section | Data Source | Failure Mode |
|---------|------------|--------------|
| `identity` | `self.unit.name`, `self.app.name`, `self.model.name` | Always available |
| `version` | charm version file + workload binary | Workload may be unavailable |
| `leadership` | `self.unit.is_leader()` | Always available |
| `config` | `self.config` + charmcraft defaults | Always available |
| `event-ledger` | `self._event_ledger` (in-memory) | Always available (may be empty) |
| `relations` | `self.model.relations` iteration | Always available (may be empty) |
| `storage` | `self.model.storages` | May be unattached |
| `containers` | `self.unit.get_container()` + Pebble API | Container may not be connected |
| `secrets` | `self.model.get_secret()` for known secrets | May not exist yet |

### Filtering

The action accepts an optional `sections` parameter (comma-separated string). When provided, only matching section collectors run. When absent, all sections are included.

## Complexity Tracking

No violations to justify.
