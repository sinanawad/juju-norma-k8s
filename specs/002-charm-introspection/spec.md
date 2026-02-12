# Feature Specification: Charm Introspection Action

**Feature Branch**: `002-charm-introspection`
**Created**: 2026-02-12
**Status**: Draft
**Input**: User description: "Add a capability where we have an action of the charm, when we execute it it reports back everything the charm has, relations connections all internal information. This will be helpful as part of the CI to get some internal status report of what the charm did and what its state is (in addition to what juju knows about it)"

## Clarifications

### Session 2026-02-12

- Q: Should the introspection report include actual secret values or only metadata? → A: Metadata only (URI, label, revision, owner). No secret content in the report.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Full Charm State Report (Priority: P1)

As a CI pipeline or developer, I want to run a single action on the charm unit that returns a comprehensive report of all internal charm state — event history, configuration, relations, storage, containers, leadership, secrets, and any other internal data the charm tracks — so that I can verify the charm's actual state independently of what Juju reports.

**Why this priority**: This is the core and only feature. Without the comprehensive report, there is no value. Individual per-topic actions already exist in the charm; this feature's value is the single-call aggregation that CI can parse programmatically.

**Independent Test**: Can be fully tested by deploying the charm, performing a few operations (config change, relate, store data), then running the introspection action and verifying the returned report contains all expected sections with accurate data.

**Acceptance Scenarios**:

1. **Given** a deployed norma-k8s unit in active state, **When** the operator runs the introspection action, **Then** the action returns a structured report containing sections for: event ledger, configuration, relations, storage, containers, leadership, secrets, version, and identity.
2. **Given** a deployed unit with active peer relations and custom configuration, **When** the operator runs the introspection action, **Then** the relations section lists all active relations with their interface, endpoint, and relation data, and the configuration section shows all current config values including any changed from defaults.
3. **Given** a deployed unit where the workload container is not yet ready, **When** the operator runs the introspection action, **Then** the report still returns successfully with available sections populated and container/workload sections indicating the unavailable state rather than failing.

---

### User Story 2 - Section Filtering (Priority: P2)

As a CI script, I want to request only specific sections of the introspection report (e.g., only relations, or only event log) so that I can reduce output noise and parse just the data I need for a specific test assertion.

**Why this priority**: Enhances usability for CI but the full report (US1) already delivers all the value. Filtering is a convenience optimisation.

**Independent Test**: Can be tested by running the action with a section filter parameter and verifying only the requested sections appear in the output.

**Acceptance Scenarios**:

1. **Given** a deployed unit, **When** the operator runs the introspection action with a section filter specifying "relations,config", **Then** the report contains only the relations and config sections.
2. **Given** a deployed unit, **When** the operator runs the introspection action with no filter, **Then** all sections are included (default behaviour, same as US1).
3. **Given** a deployed unit, **When** the operator runs the introspection action with an unrecognised section name, **Then** that section name is silently ignored and the report contains only valid matching sections.

---

### Edge Cases

- What happens when the charm has no relations at all? The relations section returns an empty list, not an error.
- What happens when storage is not yet attached? The storage section reports the unattached state with available metadata.
- What happens when the action is run on a non-leader unit? The report still returns all unit-scoped data; app-scoped data (like app relation data or leader-only secrets) is included if accessible, otherwise marked as "not available (non-leader)".
- What happens when the report payload exceeds the action result size limit? The report truncates the largest section (typically event ledger) and includes a "truncated" flag with the original count.
- What happens when secret config is set? The secrets section reports metadata only (URI, label, revision, owner) — never the actual secret content, to prevent leaking sensitive data in CI logs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The charm MUST provide a single action that returns a comprehensive structured report of all internal charm state.
- **FR-002**: The report MUST include the following sections: event ledger summary, current configuration (all options with values and whether they differ from defaults), relations (all endpoints with connected applications, interface names, and relation data), storage (attachment status and metadata), containers (connectivity and service status per container), leadership (whether this unit is leader), secrets (metadata only: URI, label, revision, owner), charm and workload version, and unit identity.
- **FR-003**: The report MUST be returned as structured data that can be parsed programmatically by CI scripts.
- **FR-004**: The action MUST succeed even when some charm subsystems are unavailable (e.g., workload container not connected, storage not attached). Unavailable sections MUST report their status rather than causing the action to fail.
- **FR-005**: The action MUST accept an optional section filter parameter to return only specified sections of the report.
- **FR-006**: The action MUST complete and return results within 5 seconds regardless of charm state, and MUST NOT trigger reconciliation or any side effects beyond reading state.
- **FR-007**: The report MUST include a timestamp indicating when the report was generated and the unit name that generated it.
- **FR-008**: The secrets section MUST include only metadata (URI, label, revision, owner) and MUST NOT include actual secret content.

### Key Entities

- **Introspection Report**: The top-level structured response containing all sections. Keyed by section name, each section containing the relevant data for that domain.
- **Report Section**: A named portion of the report (e.g., "config", "relations", "event-ledger", "storage", "containers", "leadership", "secrets", "version", "identity"). Each section is self-contained and can be independently included or excluded.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A single action invocation returns data spanning all major charm subsystems (minimum 7 distinct sections) in one response.
- **SC-002**: The report completes successfully in 100% of cases regardless of charm health state (waiting, active, blocked, or error).
- **SC-003**: CI scripts can parse the report output and extract individual section data without custom text processing (structured data format).
- **SC-004**: Section filtering reduces the response payload to contain only the requested sections.

## Assumptions

- The introspection action is read-only and does not modify charm state or trigger any events beyond the action event itself.
- The event ledger section reports whatever is available in the in-memory ledger. Currently, the ledger resets on every event dispatch (charm re-instantiation), not just on pod restart — so the section will be empty until ledger persistence is implemented (001 scope). The collector is correct; the data source is the limitation.
- The action result size limit is sufficient for the full report in typical deployments. If not, truncation is applied gracefully.
- The report includes data visible to the unit running the action. Cross-unit data (other units' relation data) is included only if accessible through standard relation APIs.

## Scope Boundaries

**In scope**:
- Single action returning comprehensive charm state
- Section filtering
- Graceful degradation when subsystems are unavailable
- Structured, parseable output format

**Out of scope**:
- Historical reporting or diffing between states over time
- Continuous monitoring or streaming of state changes
- Modifying charm state through the introspection action
- Cross-unit aggregation (reporting state of other units in the application)
- Exposing actual secret content (metadata only)
