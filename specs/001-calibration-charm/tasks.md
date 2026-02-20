# Tasks: Juju K8s Calibration Charm

**Input**: Design documents from `/specs/001-calibration-charm/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Included per constitution Principle VI (Three-Tier Testing) and SC-007.

**Organization**: Tasks grouped by user story for independent implementation. 25 user stories from spec.md (US1-US24, US26; US25 removed — K8s subordinates unsupported), organized in priority order. 44 functional requirements (FR-001 through FR-044) and 5 non-functional requirements.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1-US24, US26)
- Exact file paths included in descriptions

---

## Phase 1: Setup (Project Initialization)

**Purpose**: Create project structure, configure tooling, install dependencies

- [X] T001 Create project directory structure: `src/`, `src/grafana_dashboards/`, `src/prometheus_alert_rules/`, `tests/`, `tests/unit/`, `tests/integration/`, `workload/`, `lib/charms/`
- [X] T002 Initialize Python project with `pyproject.toml` including ops, ops[testing], ruff, coverage[toml], jubilant dependencies and ruff configuration per constitution (line-length 99, Python 3.12 target)
- [X] T003 [P] Create `Makefile` with targets: `lint` (ruff check+format), `unit` (pytest tests/unit), `integration` (pytest tests/integration), `clean` (remove build artifacts), `fmt` (ruff format)
- [X] T004 [P] Run `uv sync` to generate `uv.lock` and verify dependency resolution

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can begin

**CRITICAL**: No user story work can begin until this phase is complete

- [X] T005 [P] Implement Go workload binary in `workload/main.go`: HTTP server using Go 1.22+ `net/http.ServeMux` with `GET /health` (200 OK or 500 UNHEALTHY via `sync/atomic.Bool` + `HEALTH_FLAG_FILE` check), `GET /version` (JSON `{"version":"X.Y.Z"}` from ldflags), `GET /ready` (always 200 READY), `GET /metrics` (`promhttp.Handler()` with custom `norma_http_requests_total` CounterVec, `norma_health_toggles_total` Counter, `norma_healthy` Gauge), `POST /toggle-health` (atomic flip, JSON response); support `--port` flag (default from `PORT` env, fallback 8080), `--check` flag (HTTP GET to own `/health`, exit 0/1); per research.md R1
- [X] T006 [P] Create `workload/go.mod` with module `github.com/canonical/juju-norma-k8s/workload`, Go 1.22, `prometheus/client_golang v1.21.0` dependency; run `go mod tidy` to generate `workload/go.sum`
- [X] T007 [P] Create `rockcraft.yaml` at repo root with `base: bare`, `build-base: ubuntu@24.04`, Go plugin, source `workload/`, build-snaps `go/1.22/stable`, `CGO_ENABLED=0`, build tags `osusergo,netgo`, `run_user: _daemon_`, service `norma` command `/bin/norma` startup enabled, stage only `bin/norma`; per research.md R2
- [X] T008 Create `charmcraft.yaml` at repo root from `contracts/charmcraft-schema.yaml`: type charm, name juju-norma-k8s, base ubuntu@24.04, uv plugin part with git describe version, assumes juju>=3.6 and k8s-api, two containers (norma with data+logs storage mounts, norma-secondary), juju-norma-image OCI resource, data+logs filesystem storage, 5 config options (calibration-string/int/float/bool/secret), peers norma-peers, provides (calibration-provider, metrics-endpoint, grafana-dashboard), requires (calibration-requirer limit 1, log-proxy limit 1), charm-libs for prometheus_scrape/grafana_dashboard/loki_push_api, charm-user non-root
- [X] T009 [P] Implement workload abstraction module `src/norma.py` with zero ops dependency: `build_pebble_layer(container_name, port, version)` returning dict for primary container (service name, override replace, startup enabled, command `/bin/norma`, environment PORT/VERSION, user `_daemon_`), `build_secondary_layer(version)` for secondary container (disables default norma service, defines norma-secondary on port 8081), `validate_config(config_dict)` returning `(valid: bool, error_msg: str)` checking string non-empty, port 1-65535, and float >0.0, constants `CONTAINER_NAME`, `SECONDARY_CONTAINER`, `DEFAULT_PORT`, `SECONDARY_PORT`, `HEALTH_FLAG_FILE`, `STORAGE_CONFIG`, `BINARY_PATH`, `LEDGER_FILE`, `DEFER_FLAG_FILE`, persistence functions for event ledger and defer state
- [X] T010 Implement base charm skeleton in `src/charm.py`: `NormaK8sCharm(ops.CharmBase)` with `__init__` that observes all lifecycle events (install, start, stop, remove, config-changed, leader-elected, leader-settings-changed, upgrade-charm, update-status, secret-changed) routed to `_reconcile()`, observes pebble-ready for both containers, observes collect-unit-status and collect-app-status, observes peer and calibration relation events; `_reconcile(event)` method that checks container connectivity and returns early with WaitingStatus if not connected; import constants and builders from `norma` module
- [X] T011 [P] Create test infrastructure: `tests/conftest.py` (shared fixtures), `tests/unit/test_norma.py` (tests for `validate_config` valid/invalid cases, `build_pebble_layer` returns correct structure, constants defined), `tests/integration/__init__.py` (empty), `tests/integration/conftest.py` (jubilant fixtures)
- [X] T012 [P] Create initial `tests/unit/test_charm.py` with ops.testing/Scenario setup: import NormaK8sCharm, create Scenario `Context(NormaK8sCharm)`, verify charm instantiates with both containers defined, verify `_reconcile` sets WaitingStatus when container not connected, verify ActiveStatus when primary container connected

**Checkpoint**: Foundation ready — all tooling configured, Go workload implemented, base charm skeleton deployed. User story implementation can now begin.

---

## Phase 3: User Story 1 — Charm Lifecycle Events (P1) — MVP

**Goal**: Log all lifecycle events to an in-memory event ledger, queryable via action

**Independent Test**: Deploy -> wait for active -> `juju run juju-norma-k8s/0 get-event-log` -> verify install, leader-elected, config-changed, start in order

### Implementation

- [X] T013 [US1] Add event ledger to `src/charm.py`: define event ledger with disk persistence via norma module, add `_log_event(event_name, extra=None)` helper that appends `{"timestamp": iso, "event_name": name, "unit_name": self.unit.name, "extra": extra or {}}`, call `_log_event` at the start of `_reconcile()` and in all dedicated handlers (stop, remove)
- [X] T014 [US1] Add `get-event-log` action to `charmcraft.yaml` actions section (params: limit integer default 0, event-filter string default "") and implement `_on_get_event_log_action` handler in `src/charm.py`: observe the action event, filter ledger by event-filter substring if set, apply limit if >0, set action results with `events` (JSON list), `count` (int), `unit` (self.unit.name)
- [X] T015 [US1] Add lifecycle event unit tests in `tests/unit/test_charm.py`: verify event ledger records install event via Scenario `run("install", state)`, verify config-changed appends to ledger, verify get-event-log action returns correct entries with filtering, verify event-filter param works

**Checkpoint**: US1 complete — charm logs and reports all lifecycle events

---

## Phase 4: User Story 2 — Pebble Workload Management (P2)

**Goal**: Manage workload process via Pebble with layer definition, service start, and replan on config change

**Independent Test**: Deploy -> wait active -> verify workload HTTP responds 200 on `/ready`

### Implementation

- [X] T016 [US2] Enhance `_reconcile()` in `src/charm.py`: after connectivity check, build Pebble layer via `norma.build_pebble_layer()` with config port and version, call `container.add_layer("norma", layer, combine=True)` and `container.replan()`, query workload `/version` endpoint via `container.exec()` and call `self.unit.set_workload_version()`; wrap in try/except `ConnectionError` -> WaitingStatus
- [X] T017 [US2] Add `run-check` action to `charmcraft.yaml` actions section (params: check string required) and implement `_on_run_check_action` handler in `src/charm.py`: for `check=pebble` verify service running via `container.get_service("norma").is_running()` and plan matches expected layer, return `{"check": "pebble", "result": "pass/fail", "details": str}`
- [X] T018 [US2] Add Pebble unit tests in `tests/unit/test_charm.py`: verify layer applied on pebble-ready event via Scenario with Container, verify replan triggered on config-changed, verify WaitingStatus when container not connected, verify run-check pebble action returns pass when service running

**Checkpoint**: US2 complete — workload managed via Pebble with proper lifecycle

---

## Phase 5: User Story 3 — Configuration (P3)

**Goal**: Handle all 5 config types with validation, blocking on invalid values

**Independent Test**: Deploy -> `juju config juju-norma-k8s calibration-string=test` -> `juju run juju-norma-k8s/0 get-config` -> verify new value

### Implementation

- [X] T019 [US3] Enhance `_reconcile()` in `src/charm.py`: call `norma.validate_config()` with current config dict, if invalid set blocked status and return early; pass validated config values to Pebble layer environment via updated `build_pebble_layer()` call
- [X] T020 [US3] Add secret config resolution in `_reconcile()` in `src/charm.py`: if `self.config.get("calibration_secret")` is set, resolve via `self.model.get_secret(id=secret_uri)` and call `secret.get_content(refresh=True)`, handle `SecretNotFoundError` with BlockedStatus; observe `secret-changed` event routed to `_reconcile` per research.md R4
- [X] T021 [US3] Add `get-config` action to `charmcraft.yaml` actions section and implement `_on_get_config_action` handler in `src/charm.py`: return all current config values as action results (`calibration-string`, `calibration-int`, `calibration-float`, `calibration-bool`, `calibration-secret` as "set"/"unset" without exposing content)
- [X] T022 [US3] Add configuration unit tests in `tests/unit/test_charm.py`: verify valid config -> ActiveStatus with Scenario config, verify invalid port (0 or 99999) -> BlockedStatus, verify config-changed triggers Pebble replan, verify get-config action returns all values, verify secret config resolution with mock secret

**Checkpoint**: US3 complete — all config types handled with validation

---

## Phase 6: User Story 4 — Status Reporting (P4)

**Goal**: Implement collect_unit_status/collect_app_status with all status types and forced status via action

**Independent Test**: Deploy -> `juju run juju-norma-k8s/0 set-status status=blocked message="test"` -> `juju status` -> verify blocked

### Implementation

- [X] T023 [US4] Implement `_on_collect_unit_status` in `src/charm.py`: check forced status first, then check config validation (BlockedStatus), then check Pebble connectivity (WaitingStatus), otherwise `event.add_status(ops.ActiveStatus())`; implement `_on_collect_app_status` on leader
- [X] T024 [US4] Add `set-status` action to `charmcraft.yaml` actions section (params: status string required, message string default "") and implement `_on_set_status_action` handler in `src/charm.py`: map status string to ops status class, store in forced status, return previous-status and new-status
- [X] T025 [US4] Add status unit tests in `tests/unit/test_charm.py`: verify ActiveStatus when healthy via Scenario collect-unit-status, verify BlockedStatus on invalid config, verify WaitingStatus when Pebble disconnected, verify set-status action forces BlockedStatus, verify status priority

**Checkpoint**: US4 complete — comprehensive status reporting with all types

---

## Phase 7: User Story 5 — Actions (P5)

**Goal**: Implement remaining action infrastructure: fail-action, action progress logging, error handling

**Independent Test**: Deploy -> `juju run juju-norma-k8s/0 fail-action message="expected"` -> verify action fails with message

### Implementation

- [X] T026 [US5] Add `fail-action` action to `charmcraft.yaml` actions section (params: message string default "Intentional failure for testing") and implement `_on_fail_action` handler in `src/charm.py`: call `event.fail(params["message"])`, log the failure to event ledger
- [X] T027 [US5] Add `event.log()` progress logging to key action handlers in `src/charm.py` for operator visibility during execution
- [X] T028 [US5] Add action unit tests in `tests/unit/test_charm.py`: verify fail-action calls `event.fail()` with provided message via Scenario action run, verify action with valid params returns structured results

**Checkpoint**: US5 complete — all action patterns demonstrated

---

## Phase 8: User Story 6 — Peer Relations & Leadership (P6)

**Goal**: Handle peer relation data exchange, leader writes to app bag, units write to unit bags

**Independent Test**: Deploy 3 units -> `juju run juju-norma-k8s/0 get-peer-data` -> verify all see peer data

### Implementation

- [X] T029 [US6] Enhance `_reconcile()` in `src/charm.py`: get peer relation via `self.model.get_relation("norma-peers")`, write to `relation.data[self.unit]` and if leader write to `relation.data[self.app]` with cluster state
- [X] T030 [US6] Add `get-peer-data` action to `charmcraft.yaml` actions section and implement `_on_get_peer_data_action` handler in `src/charm.py`: read peer relation, return `app-data` and `unit-data`
- [X] T031 [US6] Add peer relation unit tests in `tests/unit/test_charm.py`: verify unit data written to peer relation on reconcile, verify leader writes app data, verify non-leader does not write app data, verify get-peer-data returns correct structure

**Checkpoint**: US6 complete — peer relation data flows correctly between units

---

## Phase 9: User Story 7 — Provides/Requires Relations (P7)

**Goal**: Handle calibration provides/requires endpoints for two-instance relation testing

**Independent Test**: Deploy two instances -> `juju integrate` -> `juju run juju-norma-k8s/0 get-relation-data endpoint=calibration-provider` -> verify data

### Implementation

- [X] T032 [US7] Add calibration relation event handling in `src/charm.py` `__init__`: observe relation-created/joined/changed/departed/broken for both endpoints routed to `_reconcile()`; log departing unit identity to event ledger
- [X] T033 [US7] Add `get-relation-data` action to `charmcraft.yaml` actions section (params: endpoint string required, relation-id integer optional) and implement `_on_get_relation_data_action` handler in `src/charm.py`
- [X] T034 [US7] Add relation unit tests in `tests/unit/test_charm.py`: verify relation events are logged, verify data written to provider/requirer relation bags, verify departing unit identity

**Checkpoint**: US7 complete — provides/requires relation working between two charm instances

---

## Phase 10: User Story 8 — Scaling (P8)

**Goal**: Report cluster membership information across scale operations

**Independent Test**: Deploy -> scale to 3 -> `juju run juju-norma-k8s/0 get-cluster-info` -> verify unit-count=3

### Implementation

- [X] T035 [US8] Add `get-cluster-info` action to `charmcraft.yaml` actions section and implement `_on_get_cluster_info_action` handler in `src/charm.py`: return `unit-count`, `planned-units`, `leader`, `is-leader`, `units`
- [X] T036 [US8] Add scaling unit tests in `tests/unit/test_charm.py`: verify get-cluster-info returns correct count for single unit, verify correct count with peer units in Scenario

**Checkpoint**: US8 complete — cluster info accurately reported

---

## Phase 11: User Story 9 — Juju Secrets (P9)

**Goal**: Full secret lifecycle: create, rotate, expire, remove, share ID via peer data

**Independent Test**: Deploy -> `juju run juju-norma-k8s/0 get-secret-info` -> verify secret exists with rotation policy

### Implementation

- [X] T037 [US9] Add secret creation in `_reconcile()` in `src/charm.py`: on leader-elected create app-owned secret with rotation policy, store ID in peer app data
- [X] T038 [US9] Add secret event handlers in `src/charm.py`: observe `secret-rotate` (new revision), `secret-expired` (cleanup), `secret-remove` (remove old revision); grant/revoke in relation handlers
- [X] T039 [US9] Add `get-secret-info` action to `charmcraft.yaml` actions section and implement handler
- [X] T040 [US9] Add secret unit tests in `tests/unit/test_charm.py`: verify secret created on leader-elected, verify secret ID stored in peer data, verify rotation creates new content, verify grant/revoke

**Checkpoint**: US9 complete — full secret lifecycle operational

---

## Phase 12: User Story 10 — Storage (P10)

**Goal**: Persist marker file to filesystem storage, verify survival across restarts

**Independent Test**: Deploy -> `juju run juju-norma-k8s/0 check-storage` -> verify attached and marker exists

### Implementation

- [X] T041 [US10] Add storage handling in `_reconcile()` in `src/charm.py`: write marker file to storage mount with atomic write; observe `storage-detaching` event and log to ledger
- [X] T042 [US10] Add `check-storage` action with `name` parameter to `charmcraft.yaml` and implement handler: return `attached`, `mount-point`, `marker-exists`, `marker-content`, `writable`
- [X] T043 [US10] Add storage unit tests in `tests/unit/test_charm.py`: verify marker file logic, verify check-storage returns correct data, verify storage-detaching event logged

**Checkpoint**: US10 complete — storage persistence verified

---

## Phase 13: User Story 11 — Pebble Health Checks (P11)

**Goal**: Configure Pebble HTTP and exec health checks, handle check-failed/recovered events

**Independent Test**: Deploy -> `toggle-health` -> wait for pebble-check-failed -> toggle back -> wait for pebble-check-recovered

### Implementation

- [X] T044 [US11] Add health check definitions to Pebble layer in `src/norma.py` `build_pebble_layer()`: HTTP (level ready), exec alive, TCP alive
- [X] T045 [US11] Add `pebble-check-failed` and `pebble-check-recovered` event handlers in `src/charm.py`: log to event ledger with check name
- [X] T046 [US11] Add `toggle-health` action to `charmcraft.yaml` and implement handler: toggle flag file, return previous/new state
- [X] T047 [US11] Add health check unit tests in `tests/unit/test_charm.py`: verify all three checks in layer, verify check events logged, verify toggle-health action

**Checkpoint**: US11 complete — health checks functional with toggle mechanism

---

## Phase 14: User Story 12 — Pebble File Operations & Exec (P12)

**Goal**: Exercise all Pebble file and exec operations via test-pebble-ops action

**Independent Test**: Deploy -> `juju run juju-norma-k8s/0 test-pebble-ops` -> verify all operations pass

### Implementation

- [X] T048 [US12] Add `test-pebble-ops` action to `charmcraft.yaml` and implement handler in `src/charm.py`: file ops (push, pull, make-dir, list-files, exec, exec-fail, remove-path, permissions, exists) and service ops (stop, start, restart, get-plan, get-services); return pass/fail for each operation and summary
- [X] T049 [US12] Add pebble ops unit tests in `tests/unit/test_charm.py`: verify action runs through all operations, verify pass/fail results

**Checkpoint**: US12 complete — all Pebble file and exec operations validated

---

## Phase 15: User Story 13 — Pebble Custom Notices (P13)

**Goal**: Handle custom notices from workload container via pebble-custom-notice event

**Independent Test**: Deploy -> `juju run juju-norma-k8s/0 trigger-notice` -> `get-event-log event-filter=notice` -> verify recorded

### Implementation

- [X] T050 [US13] Add `pebble-custom-notice` event handler for norma container in `src/charm.py`: observe, extract key, log to event ledger
- [X] T051 [US13] Add `trigger-notice` action to `charmcraft.yaml` (params: key default "norma.dev/calibration-test", data default "{}") and implement handler: exec `pebble notify` inside container
- [X] T052 [US13] Add notice unit tests in `tests/unit/test_charm.py`: verify handler logs event with key, verify trigger-notice calls correct pebble command

**Checkpoint**: US13 complete — custom notice communication working

---

## Phase 16: User Story 14 — Networking & Ports (P14)

**Goal**: Open workload port on startup, report ports and bindings via action

**Independent Test**: Deploy -> `juju run juju-norma-k8s/0 test-networking` -> verify port opened and bindings reported

### Implementation

- [X] T053 [US14] Add port management in `_reconcile()` in `src/charm.py`: call `self.unit.set_ports()` to declare the workload port
- [X] T054 [US14] Add `test-networking` action to `charmcraft.yaml` and implement handler: return opened-ports and bindings
- [X] T055 [US14] Add networking unit tests in `tests/unit/test_charm.py`: verify `set_ports` called in reconcile, verify test-networking action returns data

**Checkpoint**: US14 complete — port management and network bindings operational

---

## Phase 17: User Story 15 — Upgrade/Refresh (P15)

**Goal**: Handle upgrade-charm event, track and report charm/workload versions

**Independent Test**: Deploy -> `juju run juju-norma-k8s/0 get-version` -> refresh -> verify version changed

### Implementation

- [X] T056 [US15] Enhance upgrade-charm handling in `_reconcile()`: log upgrade event, re-apply Pebble layer, read charm version, set workload version
- [X] T057 [US15] Add `get-version` action to `charmcraft.yaml` and implement handler: return charm-version and workload-version
- [X] T058 [US15] Add upgrade unit tests in `tests/unit/test_charm.py`: verify upgrade-charm triggers reconcile and logs event

**Checkpoint**: US15 complete — version tracking and upgrade handling operational

---

## Phase 18: User Story 16 — Multiple Containers (P16)

**Goal**: Manage secondary container with independent Pebble layer and health check

**Independent Test**: Deploy -> verify both containers running -> `juju run juju-norma-k8s/0 test-pebble-ops container=norma-secondary` -> verify pass

### Implementation

- [X] T059 [US16] Complete `build_secondary_layer(version)` in `src/norma.py`: service `norma-secondary`, disables default norma service, port 8081, health check
- [X] T060 [US16] Add secondary container handling in `_reconcile()` in `src/charm.py`: apply secondary layer, replan independently from primary
- [X] T061 [US16] Add multi-container unit tests in `tests/unit/test_charm.py`: verify independent pebble-ready events, verify different layers, verify secondary gets port 8081

**Checkpoint**: US16 complete — both containers independently managed

---

## Phase 19: User Story 17 — Non-Root Security & Trust (P17)

**Goal**: Verify non-root execution and trust/credential access via action

**Independent Test**: Deploy with `--trust` -> `juju run juju-norma-k8s/0 check-security` -> verify non-root UID and trust available

### Implementation

- [X] T062 [US17] Add `check-security` action to `charmcraft.yaml` and implement handler: return charm-uid/gid, workload-uid/gid, trust-available, cloud-type
- [X] T063 [US17] Add security unit tests in `tests/unit/test_charm.py`: verify check-security action returns UID/GID fields, verify trust detection logic

**Checkpoint**: US17 complete — security posture validated

---

## Phase 20: User Story 18 — COS Observability Integration (P18)

**Goal**: Integrate with Prometheus, Grafana, and Loki via COS charm libraries

**Independent Test**: Deploy with COS -> `juju integrate juju-norma-k8s:metrics-endpoint prometheus-k8s` -> verify metrics scraped

### Implementation

- [X] T064 [US18] Fetch COS charm libraries and add initialization in `src/charm.py` `__init__`: MetricsEndpointProvider, GrafanaDashboardProvider, LogForwarder
- [X] T065 [P] [US18] Create Grafana dashboard JSON in `src/grafana_dashboards/norma.json`
- [X] T066 [P] [US18] Create Prometheus alert rules in `src/prometheus_alert_rules/norma_alerts.yaml`
- [X] T067 [US18] Add COS unit tests in `tests/unit/test_charm.py`: verify providers initialized correctly

**Checkpoint**: US18 complete — full COS observability stack integrated

---

## Phase 21: User Story 19 — Cross-Model Relations (P19)

**Goal**: Verify calibration endpoints work identically for cross-model relations

**Independent Test**: Deploy in two models -> `juju offer` -> consume -> integrate -> verify data exchange

### Implementation

- [X] T068 [US19] Verify CMR compatibility in `src/charm.py`: no same-model assumptions, remote app name in event ledger
- [X] T069 [US19] Add CMR unit tests in `tests/unit/test_charm.py`: verify relation handlers work with remote app from different model context

**Checkpoint**: US19 complete — cross-model relation support verified

---

## Phase 22: User Story 20 — Event Deferral (P20)

**Goal**: Arm deferral via action, defer eligible events, log deferrals and re-emissions

**Independent Test**: Deploy -> `juju run juju-norma-k8s/0 test-defer arm=true` -> trigger config-changed -> get-event-log -> verify deferred and re-emitted

### Implementation

- [X] T070 [US20] Add deferral arming mechanism in `src/charm.py`: pre-reconcile gate that checks defer flag, defers eligible events, logs deferral/re-emission to event ledger; persist state via norma module
- [X] T071 [US20] Add `test-defer` action to `charmcraft.yaml` and implement handler: arm/disarm deferral, return state
- [X] T072 [US20] Add deferral unit tests in `tests/unit/test_charm.py`: verify arming, verify deferred event logged, verify re-emission detected, verify non-deferrable events rejected

**Checkpoint**: US20 complete — event deferral mechanism fully validated

---

## Phase 23: User Story 21 — OCI Resource Lifecycle (P21)

**Goal**: Verify charm handles OCI image resource refresh gracefully

**Independent Test**: Deploy -> `juju attach-resource` -> verify pebble-ready fires -> charm returns to active

### Implementation

- [X] T073 [US21] Verify OCI resource refresh handling in `src/charm.py`: reconciler re-applies layer on pebble-ready; detect resource refresh/restart context in event ledger
- [X] T074 [US21] Add OCI resource lifecycle unit tests in `tests/unit/test_charm.py`: verify pebble-ready triggers full reconcile regardless of context

**Checkpoint**: US21 complete — OCI resource lifecycle validated through existing reconciler

---

## Phase 25: User Story 22 — Charm Introspection (P22)

**Purpose**: Single action returns comprehensive structured report of all internal charm state

**Dependencies**: All prior user stories (collectors read data populated by US1-US24)

- [X] T089 Add `introspect` action definition with `sections` parameter to `charmcraft.yaml`. Register observer in `__init__` and add `REPORT_SECTIONS` constant in `src/charm.py`
- [X] T090 [P] Implement 9 section collectors (`_collect_identity`, `_collect_version`, `_collect_leadership`, `_collect_config`, `_collect_event_ledger`, `_collect_relations`, `_collect_storage`, `_collect_containers`, `_collect_secrets`) as private methods on the charm class, each returning a plain dict with try/except for graceful degradation, in `src/charm.py`
- [X] T091 Wire all collectors into `_on_introspect_action` handler: call each collector, JSON-encode, set action results with truncation and section filtering logic. In `src/charm.py`
- [X] T092 [P] Add unit tests for introspect action in `tests/unit/test_charm.py`: all-sections, identity accuracy, config with changed values, containers disconnected, section filtering, invalid section silently ignored
- [X] T093 CLI Acceptance (Constitution VIII): Deploy charm, run `juju run juju-norma-k8s/0 introspect`, verify all 9 sections present with accurate data

**Checkpoint**: `juju run juju-norma-k8s/0 introspect` returns full structured report, filtering works

---

## Phase 26: US23 — Multi-Architecture OCI Image

**Purpose**: Build ROCK image for amd64 and arm64

**Dependencies**: Phase 2 (rockcraft.yaml exists)

- [X] T094 Add `arm64` platform to `rockcraft.yaml` alongside existing `amd64`. Add `GOARCH` cross-compilation support in override-build.
- [X] T095 [P] Add `arm64` platform to `charmcraft.yaml` `platforms:` section.
- [ ] T096 CLI Acceptance (Constitution VIII): Build the ROCK on amd64, verify the image manifest includes the correct architecture label. Document multi-arch build procedure for CI.

**Checkpoint**: `rockcraft.yaml` and `charmcraft.yaml` declare amd64 + arm64 platforms

---

## Phase 27: US24 — Multiple Storage Definitions

**Purpose**: Add a second optional storage to enable independent attachment/detachment testing

**Dependencies**: Phase 12 (US10 storage handling exists)

- [X] T097 Add `logs` storage definition to `charmcraft.yaml`: type filesystem, minimum-size 512M, multiple-range 0-1.
- [X] T098 Add `LOGS_STORAGE_PATH` and `LOGS_MARKER_FILE` constants to `src/norma.py` via `STORAGE_CONFIG` dict.
- [X] T099 Extend `_on_check_storage_action` in `src/charm.py` to accept a `name` parameter. Report storage as unavailable if not attached.
- [X] T100 Extend `_collect_storage` introspect collector in `src/charm.py` to enumerate both storages.
- [X] T101 [P] Add unit tests for multiple storage in `tests/unit/test_charm.py`: check-storage with name=data, name=logs attached/not attached, introspect storage section.
- [ ] T102 CLI Acceptance (Constitution VIII): Deploy, verify `data` attached. Run `juju add-storage juju-norma-k8s/0 logs=1`. Verify `check-storage name=logs` reports available.

**Checkpoint**: `check-storage name=logs` works, introspect lists both storages

---

## ~~Phase 28: US25 — Subordinate Charm Integration~~ (REMOVED)

**Removed**: US25 removed — K8s subordinate charms are unsupported by Juju (machine-model only).
Tasks T103-T107 are no longer applicable. The `juju-info` provides endpoint is retained in
`charmcraft.yaml` as a standard interface (FR-027).

---

## Phase 29: New Functional Requirements (FR-028 through FR-032)

**Purpose**: Implement remaining functional requirements added post-original planning

**Dependencies**: Corresponding user story phases must be complete

### FR-028: container.send_signal() (extends US12)

- [X] T108 [US12] Add `send-signal` operation to `_on_test_pebble_ops_action` in `src/charm.py`: sends SIGHUP, verifies service survives.
- [X] T109 [P] [US12] Add unit test for send_signal in `tests/unit/test_charm.py`: verifies send-signal key in pebble-ops results.

### FR-029: Force Remove Integration Test (extends US1)

- [X] T110 [US1] Add `test_force_remove_application` to `tests/integration/test_lifecycle.py`: deploys alt app, force-removes, verifies clean model. Behind `--run-destructive`.

### FR-030: Storage CLI Operations (extends US10, xfail)

- [X] T111 [P] [US10] Add xfail integration tests to `tests/integration/test_storage.py`: TestStorageCLI with xfail for attach, import-filesystem, deploy-attach.

### FR-031: charm-user sudoer Variant (extends US17)

- [X] T112 [US17] Create `charmcraft-sudoer.yaml` at repo root: copy of charmcraft.yaml with `charm-user: sudoer`.
- [X] T113 [P] [US17] Add sudoer variant to CI in `.github/workflows/ci.yaml`: pack step packs both principal and sudoer variants.

### FR-032: Parallel Secret Operations (extends US9)

- [X] T114 [US9] Add `test_parallel_secrets` to `tests/integration/test_secrets.py`: creates 3 user secrets, grants all, cycles config, verifies independence.

### FR-038: Busybox Shell in ROCK (extends US23)

- [X] T129 [US23] Add busybox shell slice to `rockcraft.yaml`: busybox_bins part with /bin/sh symlink for juju exec/ssh.
- [X] T130 [P] [US23] Add `test_juju_exec_shell` to `tests/integration/test_lifecycle.py`: verifies `/bin/sh -c 'echo hello-norma'` via juju exec.

### FR-039: Credential-Get Action (extends US17)

- [X] T131 [US17] Extend `_on_check_security_action` in `src/charm.py`: uses `model.get_cloud_spec()` for credential-get, hits K8s API with bearer token, includes credential keys.
- [X] T132 [P] [US17] Add unit tests for credential-get in `tests/unit/test_charm.py`: verifies credential keys present without trust (graceful degradation).
- [X] T133 [US17] Add `test_credential_get` integration test to `tests/integration/test_security.py`: tests with and without trust.

### FR-040: Sudoer Overlay (extends US17)

Note: T112 already creates `charmcraft-sudoer.yaml`. FR-040 confirms the overlay pattern.

- ~~[ ] T134 [US17] Update CI pack step — consolidated into T076 (CI multi-variant pack)~~

**Checkpoint**: All new FRs (FR-028 through FR-040) have implementation and test coverage

---

## Phase O1: CI Pipeline (Orthogonal)

**Purpose**: GitHub Actions CI workflow for automated lint, unit tests, charm pack, ROCK build, and integration tests

**Dependencies**: None (can be done at any time)

- [X] T075 [P] Create `.github/workflows/ci.yaml` with: trigger on push/PR to main and feature branches; jobs for `lint`, `unit` (with coverage), `pack` (charmcraft pack), `build-rock` (rockcraft pack + push to registry), `integration` (matrix for Juju channels, SETUP_ENVIRONMENT=1); use `ubuntu-24.04` runner, `astral-sh/setup-uv` action
- [X] T076 [P] Add sudoer pack job to CI: pack sudoer variant from `charmcraft-sudoer.yaml`, make artifacts available to integration tests

**Checkpoint**: CI pipeline operational with multi-variant builds

---

## Phase O2: Integration Tests (Orthogonal)

**Purpose**: Jubilant-based integration tests for each user story

**Dependencies**: Corresponding user stories must be implemented

- [X] T082 [P] Create `tests/integration/test_lifecycle.py` and `tests/integration/test_pebble.py` (US1-US2)
- [X] T083 [P] Create `tests/integration/test_config.py`, `tests/integration/test_status.py`, and `tests/integration/test_actions.py` (US3-US5)
- [X] T084 [P] Create `tests/integration/test_relations.py` and `tests/integration/test_scaling.py` (US6-US8)
- [X] T085 [P] Create `tests/integration/test_secrets.py` and `tests/integration/test_storage.py` (US9-US10)
- [X] T086 [P] Create `tests/integration/test_health_checks.py`, `tests/integration/test_pebble_ops.py`, and `tests/integration/test_notices.py` (US11-US13)
- [X] T087 [P] Create `tests/integration/test_networking.py`, `tests/integration/test_upgrade.py`, `tests/integration/test_multi_container.py`, and `tests/integration/test_security.py` (US14-US17)
- [X] T088 [P] Create `tests/integration/test_observability.py`, `tests/integration/test_cmr.py`, `tests/integration/test_defer.py`, and `tests/integration/test_oci_resource.py` (US18-US21)

**Checkpoint**: All integration test files created (US1-US24) — `make integration` validates full charm behavior

---

## Phase O3: Integration Test Infrastructure (Orthogonal)

**Purpose**: Self-contained integration test environment setup

**Dependencies**: None

- [X] T115 Create `tests/integration/setup_env.py` with idempotent environment setup: `ensure_microk8s()`, `bootstrap_controller()`, `ensure_environment()`, `check_prerequisites()`. All functions check before acting, explicit timeouts.
- [X] T116 Enhance `tests/integration/conftest.py` with environment variables (`SETUP_ENVIRONMENT`, `JUJU_CHANNEL`, `MICROK8S_CHANNEL`, `JUJU_CLI`, `JUJU_MODEL`, `JUJU_CONTROLLER`, `CHARM_PATH`, `NORMA_IMAGE`, `KEEP_MODEL`), fixture chain (environment_ready -> charm_path -> oci_image -> juju), model reuse via `JUJU_MODEL`.
- [X] T117 Add `integration-setup` target to `Makefile`: `SETUP_ENVIRONMENT=1 uv run pytest tests/integration -v --tb=short`

**Checkpoint**: `SETUP_ENVIRONMENT=1 make integration` works on a fresh Ubuntu 24.04 machine

---

## Phase 24: Polish & Cross-Cutting Concerns

**Purpose**: Validation, cleanup, and final integration across all user stories

- [ ] T077 Validate all 18 actions (+introspect) in `charmcraft.yaml` match `contracts/actions-schema.yaml` parameter definitions, types, defaults, and descriptions
- [ ] T078 Validate `charmcraft.yaml` structure matches `contracts/charmcraft-schema.yaml` for containers, resources, storage, config, relations (including juju-info), charm-libs, and charm-user
- [ ] T079 [P] Run `make lint` (ruff check and format) and fix all lint issues across `src/charm.py`, `src/norma.py`, and `tests/`
- [ ] T080 [P] Run `make unit` and verify all unit tests pass with coverage report; ensure `tests/unit/test_norma.py` and `tests/unit/test_charm.py` both pass
- [ ] T081 Run quickstart.md validation: verify build commands work, deploy instructions are accurate, and per-story test commands match implemented action names and parameters
- [ ] T118 [NFR-005] Self-sufficiency audit: verify every Juju K8s charm API surface listed in NFR-005 (lifecycle events, Pebble operations, relations, storage, secrets, actions, status, networking, expose/unexpose, security, observability, cross-model relations, model migration, goal-state, model-config, SSH access, K8s constraints) is exercisable through this charm. Cross-reference against Juju CI test charms to confirm no gap.

---

## Phase 30: Coverage Gaps (FR-033 through FR-037, FR-038 through FR-040)

**Purpose**: Close gaps identified by the Juju K8s capability coverage audit and replacement target analysis

**Goal**: Ensure the charm exercises ALL Juju operations on K8s charms — not just internal charm capabilities but every `juju` CLI operation that targets a K8s charm. Also close gaps needed to replace upstream CI test charms (NFR-005).

### FR-033: Expose/Unexpose (US14)

- [X] T119 [US14] Add exposed status to `_on_test_networking_action` in `src/charm.py`: include `exposed` key in action results (reports "unknown" — no ops API to query exposed status from inside charm).
- [X] T120 [P] [US14] Add unit test for exposed status reporting in `tests/unit/test_charm.py`: verify test-networking action includes `exposed` key in results.
- [X] T121 [US14] Add `test_expose_unexpose` to `tests/integration/test_networking.py`: run `juju expose`/`juju unexpose`, verify exposed flag in `juju status --format=json`.

### FR-034: Model Migration

- [X] T122 Add `test_model_migration` to `tests/integration/test_lifecycle.py`: skips unless two controllers are available. Requires two bootstrapped controllers.

### FR-035: Goal-State in Introspect (US22)

- [X] T123 [US22] Add `_collect_goal_state` private method to `src/charm.py`: calls `_run_tool("goal-state", "--format", "json")`, parses JSON, returns dict. Graceful degradation via try/except.
- [X] T124 [P] [US22] Add unit test for goal-state introspect section in `tests/unit/test_charm.py`: verifies graceful degradation when hook tool unavailable.
- [X] T125 [US22] Update introspect action handler in `src/charm.py` to include `goal-state` in REPORT_SECTIONS and route to `_collect_goal_state` collector.

### FR-036: Update-Status-Hook-Interval (US1)

- [X] T126 [US1] Add `test_update_status_interval` to `tests/integration/test_lifecycle.py`: sets interval to 30s, waits 90s, verifies >=2 update-status events in ledger. Resets to 5m after test.

### FR-037: SSH and Constraints (Integration)

- [X] T127 Add `test_juju_ssh` to `tests/integration/test_lifecycle.py`: runs `juju ssh --container norma APP/0 -- ls /bin/norma`, verifies output contains binary path.
- [X] T128 Add `test_deploy_with_constraints` to `tests/integration/test_lifecycle.py`: deploys with `--constraints "mem=512M cores=1"`, verifies active, cleans up. Behind `--run-destructive` flag.

---

## Phase 31: Public Publication & Release Pipeline (US26)

**Purpose**: Prepare the charm and ROCK for public distribution via CharmHub and ghcr.io with automated release workflows

**Goal**: US26 — automated OCI publishing, CharmHub release, Dependabot, and upstream-source wiring

**Dependencies**: Phase O1 (CI Pipeline) must exist. All user stories should be implemented before cutting a release.

### FR-041: Publish OCI Workflow

- [ ] T135 [US26] Create `.github/workflows/publish-oci.yaml`: trigger on pushes to main (paths: `rockcraft.yaml`, `workload/**`) and version tags (`v*`). Steps: checkout, setup LXD, install rockcraft, `rockcraft pack --platform amd64`, log in to ghcr.io via `docker/login-action`, push image to `ghcr.io/${{ github.repository_owner }}/juju-norma:<version>` and `:latest` using `rockcraft.skopeo` copy. Use `GITHUB_TOKEN` for auth.

### FR-042: Release Workflow

- [ ] T136 [US26] Create `.github/workflows/release.yaml`: trigger on version tags (`v*`). Steps: checkout, setup uv, setup LXD, install charmcraft, `charmcraft fetch-libs`, `charmcraft pack`, upload charm to CharmHub edge via `canonical/charming-actions/upload-charm` (needs `CHARMHUB_TOKEN` secret). Include a separate job triggered on push to main for `canonical/charming-actions/release-libraries`.
- [ ] T137 [P] [US26] Add library publishing job to `.github/workflows/release.yaml`: on push to main, run `canonical/charming-actions/release-libraries` to auto-publish any charm library changes.

### FR-043: Dependabot Configuration

- [ ] T138 [P] [US26] Create `.github/dependabot.yml`: configure weekly update checks for `github-actions` (directory: `/`) and `pip` (directory: `/`, package-ecosystem covers uv lockfile). Set assignees and labels as appropriate.

### FR-044: Upstream Source in charmcraft.yaml

- [ ] T139 [US26] Add `upstream-source: ghcr.io/sinanawad/juju-norma:0.1.0` to the `juju-norma-image` resource in `charmcraft.yaml`. This allows `juju deploy juju-norma-k8s --channel=edge` to automatically pull the image from ghcr.io without `--resource` override.

### Validation

- [ ] T140 [P] [US26] Add `test_upstream_source_declared` to `tests/unit/test_charm.py`: verify that `charmcraft.yaml` contains `upstream-source` for `juju-norma-image` resource (parse YAML, assert key exists and value starts with `ghcr.io/`).
- [ ] T141 [P] [US26] Validate all workflow files are syntactically valid YAML and reference correct artifact names. Manual verification: push a test tag to confirm publish-oci and release workflows trigger.

**Checkpoint**: `publish-oci.yaml` and `release.yaml` workflows created, `dependabot.yml` configured, `upstream-source` set in `charmcraft.yaml`. Manual prerequisites documented in spec.md US26.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — **BLOCKS all user stories**
- **User Stories (Phases 3-27)**: All depend on Foundational phase completion
  - US1 (Lifecycle) is the MVP — complete first
  - US2-US24 proceed in priority order
  - See cross-story dependencies below
- ~~**US25 (Phase 28)**: REMOVED — K8s subordinates unsupported (see spec.md)~~
- **New FRs (Phase 29)**: Depends on corresponding US phases being complete. FR-038 through FR-040 added for replacement target coverage.
- **Coverage Gaps (Phase 30)**: FR-033 through FR-037, FR-038 through FR-040 — mostly integration tests, can parallelize
- **Publication (Phase 31)**: US26 — depends on Phase O1 (CI) existing. Should be done after all stories are complete.
- **CI Pipeline (Phase O1)**: Orthogonal — can start after Setup
- **Integration Tests (Phase O2)**: Each test group after its story cluster
- **Integration Infra (Phase O3)**: Orthogonal — can start after Phase 1
- **Polish (Phase 24)**: Depends on all user stories being complete

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
| US22 (Introspect) | US1-US9 | Collectors read data populated by prior stories; goal-state added in Phase 30 |
| US24 (Multi-Storage) | US10 (Storage) | Extends existing storage handling |
| US26 (Publication) | O1 (CI) | Release workflow extends CI pipeline |
| All stories | US1 (Lifecycle) | Event ledger used for verification |

### Parallel Opportunities

**Phase 29 (New FRs)**: All FR tasks are independent of each other — T108-T114 and T129-T134 can run in parallel since they touch different files and test files. T131+T133 must be sequential (charm code before integration test for credential-get).

**Phase 30 (Coverage Gaps)**: T119-T128 are mostly independent. T123+T125 must be sequential (collector method before wiring). T119+T121 sequential (charm code before integration test). All other tasks can parallelize.

---

## Implementation Strategy

### Current State

Phases 1-23, 29, 30, O1-O3 are **COMPLETE**. The charm has 184 passing unit tests (149 charm + 35 norma) and integration tests across 19 test files. All 18 actions, 25 event subscriptions, goal-state introspect, and the holistic reconciler are fully implemented.

### Remaining Work

1. ~~**Phase 29 (New FRs)**~~: COMPLETE
2. ~~**Phase 30 (Coverage Gaps)**~~: COMPLETE
3. ~~**Phase O1 update**~~: COMPLETE (T076 done)
4. **Phase 31 (US26 Publication)**: publish-oci, release workflow, dependabot, upstream-source
5. **Phase 24**: Polish tasks (validation, lint, quickstart check, self-sufficiency audit)

### Suggested Execution Order

1. T108+T110+T111+T112+T114+T129+T131 (new FR implementations — all parallel)
3. T109+T113+T130+T132+T133+T134 (new FR tests/CI — after implementations)
4. T119+T123+T125 (expose status + goal-state charm code)
5. T120+T121+T122+T124+T126+T127+T128 (integration tests — all parallel)
6. T076 (CI multi-variant)
7. T077-T081+T118 (polish)

### MVP First (Complete)

The MVP (US1 through US24) is fully implemented and tested. Remaining work is incremental feature additions (new FRs) and polish.

---

## Notes

- [P] tasks = different files, no dependencies within same phase
- [USn] label maps task to specific user story for traceability
- [X] = completed, [ ] = pending
- Tasks T082-T088 retain original IDs for backward compatibility with existing references
- Tasks T103-T118 are new (added in 2026-02-18 plan refresh)
- Tasks T119-T128 are new (added in 2026-02-18 coverage audit — FR-033 through FR-037)
- Tasks T129-T134 are new (added in 2026-02-19 replacement target analysis — FR-038 through FR-040)
- `src/charm.py` is fully implemented — remaining work is incremental additions
- Commit after each completed story phase
