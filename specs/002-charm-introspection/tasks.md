# Tasks: Charm Introspection Action

**Input**: Design documents from `/specs/002-charm-introspection/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Unit tests included (constitution mandates Three-Tier Testing). Integration tests deferred to a separate phase.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Add the action definition to the charm metadata

- [ ] T001 Add `introspect` action definition with `sections` parameter to charmcraft.yaml per contracts/introspect-action.yaml

---

## Phase 2: Foundational

**Purpose**: Wire up the action handler skeleton and observer in the charm

- [ ] T002 Register `introspect_action` observer in `__init__` and add empty `_on_introspect_action` handler method in src/charm.py
- [ ] T003 Add `REPORT_SECTIONS` constant (list of valid section names: identity, version, leadership, config, event-ledger, relations, storage, containers, secrets) in src/charm.py

**Checkpoint**: Action can be invoked but returns empty results

---

## Phase 3: User Story 1 - Full Charm State Report (Priority: P1) MVP

**Goal**: Single action returns comprehensive structured report with all 9 sections

**Independent Test**: Deploy charm, run `juju run norma-k8s/0 introspect`, verify all sections present with accurate data

### Unit Tests for User Story 1

- [ ] T004 [P] [US1] Add unit test `TestIntrospectAction::test_returns_all_sections` that fires introspect action and asserts all 9 section keys plus timestamp and unit are present in action_results, in tests/unit/test_charm.py
- [ ] T005 [P] [US1] Add unit test `TestIntrospectAction::test_identity_section` that verifies identity section contains unit, app, model, and is_leader fields, in tests/unit/test_charm.py
- [ ] T006 [P] [US1] Add unit test `TestIntrospectAction::test_config_section` that verifies config section contains all 5 config options with value, default, and changed fields, in tests/unit/test_charm.py
- [ ] T007 [P] [US1] Add unit test `TestIntrospectAction::test_containers_section_disconnected` that fires introspect with Pebble not connected and verifies containers section reports unavailable status rather than failing, in tests/unit/test_charm.py
- [ ] T008 [P] [US1] Add unit test `TestIntrospectAction::test_relations_section` that fires introspect with peer relation present and verifies relations section lists the norma-peers endpoint, in tests/unit/test_charm.py

### Implementation for User Story 1

- [ ] T009 [P] [US1] Implement `_collect_identity` method returning dict with unit, app, model, is_leader in src/charm.py
- [ ] T010 [P] [US1] Implement `_collect_version` method returning dict with charm_version, workload_version, workload_available in src/charm.py
- [ ] T011 [P] [US1] Implement `_collect_leadership` method returning dict with is_leader in src/charm.py
- [ ] T012 [P] [US1] Implement `_collect_config` method returning dict with options map (value, default, changed per option) in src/charm.py
- [ ] T013 [P] [US1] Implement `_collect_event_ledger` method returning dict with count, events list, truncated flag from self._event_ledger in src/charm.py (note: section will be empty until ledger persistence is implemented in 001 scope — the collector is correct, the data source resets every dispatch)
- [ ] T014 [P] [US1] Implement `_collect_relations` method iterating self.model.relations for all endpoints, returning dict with endpoints map containing interface, relation_id, remote_app, databag data in src/charm.py
- [ ] T015 [P] [US1] Implement `_collect_storage` method iterating self.model.storages, returning dict with attachment status and location per storage in src/charm.py
- [ ] T016 [P] [US1] Implement `_collect_containers` method checking each container's can_connect() and Pebble services, returning dict per container in src/charm.py
- [ ] T017 [P] [US1] Implement `_collect_secrets` method returning metadata-only dict (URI, label, revision, owner) for known secrets, never exposing secret content, in src/charm.py
- [ ] T018 [US1] Wire all collectors into `_on_introspect_action` handler: call each collector with try/except, JSON-encode each section, set action results with timestamp and unit metadata in src/charm.py
- [ ] T018a [US1] Add truncation logic to `_on_introspect_action`: if total serialized payload exceeds 250KB, truncate the largest section (typically event-ledger) and set its `truncated` flag to true with original count, in src/charm.py
- [ ] T018b [P] [US1] Add unit test `TestIntrospectAction::test_truncation_on_large_payload` that verifies truncation activates when event ledger is artificially large, in tests/unit/test_charm.py
- [ ] T018c [P] [US1] Add unit test `TestIntrospectAction::test_non_leader_unit` that fires introspect on a non-leader unit and verifies app-scoped data is handled gracefully (accessible data included, inaccessible data marked appropriately), in tests/unit/test_charm.py

### CLI Acceptance for User Story 1 (Constitution VIII)

- [ ] T018d [US1] Deploy charm to test model, run `juju run norma-k8s/0 introspect`, verify: (1) all 9 section keys present, (2) identity section matches unit/app/model, (3) config section reflects current values, (4) relations section lists peer endpoint, (5) containers section shows connected status, (6) action completes within 5 seconds. Report pass/fail per check.

**Checkpoint**: `juju run norma-k8s/0 introspect` returns full report with all 9 sections, verified on live deployment

---

## Phase 4: User Story 2 - Section Filtering (Priority: P2)

**Goal**: Optional `sections` parameter limits report to requested sections only

**Independent Test**: Run `juju run norma-k8s/0 introspect sections=config,leadership`, verify only those sections returned

### Unit Tests for User Story 2

- [ ] T019 [P] [US2] Add unit test `TestIntrospectAction::test_section_filter` that fires introspect with sections="config,leadership" and asserts only those sections plus metadata are in action_results, in tests/unit/test_charm.py
- [ ] T020 [P] [US2] Add unit test `TestIntrospectAction::test_empty_filter_returns_all` that fires introspect with sections="" and asserts all sections returned, in tests/unit/test_charm.py
- [ ] T021 [P] [US2] Add unit test `TestIntrospectAction::test_invalid_section_ignored` that fires introspect with sections="config,nonexistent" and asserts only config section returned (nonexistent silently ignored), in tests/unit/test_charm.py

### Implementation for User Story 2

- [ ] T022 [US2] Add section filtering logic to `_on_introspect_action`: parse `sections` param as comma-separated list, intersect with REPORT_SECTIONS, run only matching collectors, in src/charm.py

### CLI Acceptance for User Story 2 (Constitution VIII)

- [ ] T022a [US2] On live deployment, run `juju run norma-k8s/0 introspect sections=config,leadership`, verify: (1) only config and leadership sections returned plus metadata, (2) run with no filter and verify all sections returned, (3) run with `sections=config,nonexistent` and verify only config returned. Action completes within 5 seconds.

**Checkpoint**: Filtering works on live deployment. Full report still works when no filter provided.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Lint, validate, and verify end-to-end

- [ ] T023 Run `uv run ruff check src/ tests/` and fix any lint issues
- [ ] T024 Run `uv run pytest tests/unit/ -v` and verify all tests pass (existing + new)
- [ ] T025 Repack charm with `charmcraft pack` and verify it builds successfully
- [ ] T026 Run final quickstart.md validation: confirm CLI acceptance (T018d, T022a) passed, verify structured output matches data-model.md schema end-to-end

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 (action must be defined before handler)
- **US1 (Phase 3)**: Depends on Phase 2 (handler skeleton must exist)
- **US2 (Phase 4)**: Depends on Phase 3 (filtering operates on the full report mechanism)
- **Polish (Phase 5)**: Depends on Phase 4

### User Story Dependencies

- **User Story 1 (P1)**: Depends on Foundational (Phase 2). No other story dependencies.
- **User Story 2 (P2)**: Depends on User Story 1 (filtering requires the collector framework from US1).

### Within Each User Story

- Tests written first (T004-T008 before T009-T018)
- All collectors (T009-T017) are parallelizable — different methods, no dependencies
- Wiring task (T018) depends on all collectors being complete
- CLI acceptance (T018d) depends on T018 + live deployment — runs after unit tests pass
- US2 filter logic (T022) depends on US1 wiring (T018)
- CLI acceptance (T022a) depends on T022 + live deployment

### Parallel Opportunities

Within US1 implementation:
- T009, T010, T011, T012, T013, T014, T015, T016, T017 can all run in parallel (independent collector methods)
- T004, T005, T006, T007, T008 can all run in parallel (independent test methods)

---

## Parallel Example: User Story 1

```bash
# Launch all US1 unit tests together:
Task: "T004 - test_returns_all_sections"
Task: "T005 - test_identity_section"
Task: "T006 - test_config_section"
Task: "T007 - test_containers_section_disconnected"
Task: "T008 - test_relations_section"

# Launch all US1 collectors together:
Task: "T009 - _collect_identity"
Task: "T010 - _collect_version"
Task: "T011 - _collect_leadership"
Task: "T012 - _collect_config"
Task: "T013 - _collect_event_ledger"
Task: "T014 - _collect_relations"
Task: "T015 - _collect_storage"
Task: "T016 - _collect_containers"
Task: "T017 - _collect_secrets"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002-T003)
3. Complete Phase 3: User Story 1 tests + implementation (T004-T018)
4. **STOP and VALIDATE**: Run tests, deploy, run `introspect` action
5. Full report works end-to-end

### Incremental Delivery

1. Setup + Foundational → Action exists, returns empty
2. Add User Story 1 → Full report works → Test and validate (MVP!)
3. Add User Story 2 → Section filtering works → Test and validate
4. Polish → Lint, test, repack, end-to-end validation

---

## Notes

- [P] tasks = different methods/functions, no dependencies between them
- All collectors follow the same pattern: try/except → return data dict or `{"status": "unavailable", "reason": "..."}`
- Juju action results are string key-value pairs; each section is JSON-encoded
- FR-008: secrets collector MUST NOT include secret content, only metadata
- Constitution VI (Three-Tier Testing): unit tests mandatory, integration test in Polish phase
- Constitution VIII (CLI Acceptance Verification): each user story has a dedicated CLI verification task (T018d for US1, T022a for US2)
