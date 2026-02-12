# Research: Charm Introspection Action

**Date**: 2026-02-12
**Status**: Complete (no unknowns identified)

## Summary

No NEEDS CLARIFICATION items in the technical context. The feature uses established patterns from the existing charm codebase and standard Juju action APIs.

## Decisions

### 1. Action Result Format

**Decision**: Each report section is a JSON-encoded string value in the Juju action results dict, keyed by section name.

**Rationale**: Juju action results are key-value pairs where values must be strings. JSON encoding per-section allows CI to parse individual sections with standard tooling (`jq .results.config | jq -r . | jq .`). A single top-level JSON blob would require double-parsing.

**Alternatives considered**:
- Single JSON blob as one result key: Simpler but harder to extract individual sections; hits size limits faster.
- YAML encoding: Less universal in CI tooling than JSON; Juju results are strings anyway.

### 2. Section Collector Architecture

**Decision**: Individual private methods on the charm class (`_collect_config()`, `_collect_relations()`, etc.), each returning a plain dict.

**Rationale**: Keeps each collector independently testable. Follows the existing pattern in the charm (e.g., `_log_event()` helper). No need for a separate module since collectors read Juju model state (ops-dependent).

**Alternatives considered**:
- Separate `introspection.py` module: Would require passing the charm model/unit objects, adding coupling without benefit. The collectors need direct access to `self.model`, `self.unit`, `self.config`.
- Single monolithic handler: Harder to test individual sections; harder to maintain.

### 3. Graceful Degradation Pattern

**Decision**: Each collector wraps its logic in try/except, returning `{"status": "unavailable", "reason": "<error>"}` on failure. The action handler never fails due to a subsystem error.

**Rationale**: FR-004 requires the action to succeed regardless of charm state. Container disconnection, missing storage, or absent secrets should not prevent the report from returning partial data.

**Alternatives considered**:
- Fail the action if any section fails: Violates FR-004 and SC-002.
- Skip failed sections entirely: Less informative for CI — knowing *why* a section is unavailable is valuable for debugging.
