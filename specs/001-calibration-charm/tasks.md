# Tasks: Juju K8s Calibration Charm

**Input**: Design documents from `/specs/001-calibration-charm/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Included per constitution Principle VI (Three-Tier Testing) and SC-007.

**Organization**: Tasks grouped by user story for independent implementation. 24 user stories from spec.md, organized in priority order (P1-P24).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1-US24)
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
- [X] T008 Create `charmcraft.yaml` at repo root from `contracts/charmcraft-schema.yaml`: type charm, name norma-k8s, base ubuntu@24.04, uv plugin part with git describe version, assumes juju>=3.6 and k8s-api, two containers (norma with data storage mount at /var/lib/norma, norma-secondary), norma-image OCI resource, data filesystem storage 1G, 5 config options (calibration-string/int/float/bool/secret), peers norma-peers, provides (calibration-provider, metrics-endpoint, grafana-dashboard), requires (calibration-requirer limit 1, log-proxy limit 1), charm-libs for prometheus_scrape/grafana_dashboard/loki_push_api, charm-user non-root
- [X] T009 [P] Implement workload abstraction module `src/norma.py` with zero ops dependency: `build_pebble_layer(container_name, port, version)` returning dict for primary container (service name, override replace, startup enabled, command `/bin/norma`, environment PORT/VERSION, user `_daemon_`), `build_secondary_layer(version)` stub (returns empty — completed in US16), `validate_config(config_dict)` returning `(valid: bool, error_msg: str)` checking string non-empty, port 1-65535, and float >0.0, constants `CONTAINER_NAME="norma"`, `SECONDARY_CONTAINER="norma-secondary"`, `DEFAULT_PORT=8080`, `HEALTH_FLAG_FILE="/tmp/norma-unhealthy"`, `STORAGE_PATH="/var/lib/norma"`, `MARKER_FILE="calibration-marker.json"`
- [X] T010 Implement base charm skeleton in `src/charm.py`: `NormaK8sCharm(ops.CharmBase)` with `__init__` that observes all lifecycle events (install, start, stop, remove, config-changed, leader-elected, leader-settings-changed, upgrade-charm, update-status) routed to `_reconcile()`, observes pebble-ready for both containers, observes collect-unit-status and collect-app-status; `_reconcile(event)` method that checks container connectivity and returns early with WaitingStatus if not connected; import constants and builders from `norma` module
- [X] T011 [P] Create test infrastructure: `tests/conftest.py` (shared fixtures), `tests/unit/test_norma.py` (tests for `validate_config` valid/invalid cases, `build_pebble_layer` returns correct structure, constants defined), `tests/integration/__init__.py` (empty), `tests/integration/conftest.py` (jubilant fixtures placeholder)
- [X] T012 [P] Create initial `tests/unit/test_charm.py` with ops.testing/Scenario setup: import NormaK8sCharm, create Scenario `Context(NormaK8sCharm)`, verify charm instantiates with both containers defined, verify `_reconcile` sets WaitingStatus when container not connected, verify ActiveStatus when primary container connected

**Checkpoint**: Foundation ready — all tooling configured, Go workload implemented, base charm skeleton deployed. User story implementation can now begin.

---

## Phase 3: User Story 1 — Charm Lifecycle Events (P1) — MVP

**Goal**: Log all lifecycle events to an in-memory event ledger, queryable via action

**Independent Test**: Deploy → wait for active → `juju run norma-k8s/0 get-event-log` → verify install, leader-elected, config-changed, start in order

### Implementation

- [X] T013 [US1] Add event ledger to `src/charm.py`: define `_event_ledger: list[dict]` in `__init__`, add `_log_event(event_name, extra=None)` helper that appends `{"timestamp": datetime.utcnow().isoformat(), "event_name": event_name, "unit_name": self.unit.name, "extra": extra or {}}`, call `_log_event` at the start of `_reconcile()` using `type(event).__name__` converted to kebab-case, and in all other observed handlers (stop, remove)
- [X] T014 [US1] Add `get-event-log` action to `charmcraft.yaml` actions section (params: limit integer default 0, event-filter string default "") and implement `_on_get_event_log_action` handler in `src/charm.py`: observe the action event, filter ledger by event-filter substring if set, apply limit if >0, set action results with `events` (JSON list), `count` (int), `unit` (self.unit.name)
- [X] T015 [US1] Add lifecycle event unit tests in `tests/unit/test_charm.py`: verify event ledger records install event via Scenario `run("install", state)`, verify config-changed appends to ledger, verify get-event-log action returns correct entries with filtering, verify event-filter param works

**Checkpoint**: US1 complete — charm logs and reports all lifecycle events

---

## Phase 4: User Story 2 — Pebble Workload Management (P2)

**Goal**: Manage workload process via Pebble with layer definition, service start, and replan on config change

**Independent Test**: Deploy → wait active → verify workload HTTP responds 200 on `/ready`

### Implementation

- [X] T016 [US2] Enhance `_reconcile()` in `src/charm.py`: after connectivity check, build Pebble layer via `norma.build_pebble_layer()` with config port and version, call `container.add_layer("norma", layer, combine=True)` and `container.replan()`, query workload `/version` endpoint via `container.exec()` and call `self.unit.set_workload_version()`; wrap in try/except `ConnectionError` → WaitingStatus
- [X] T017 [US2] Add `run-check` action to `charmcraft.yaml` actions section (params: check string required) and implement `_on_run_check_action` handler in `src/charm.py`: for `check=pebble` verify service running via `container.get_service("norma").is_running()` and plan matches expected layer, return `{"check": "pebble", "result": "pass/fail", "details": str}`
- [X] T018 [US2] Add Pebble unit tests in `tests/unit/test_charm.py`: verify layer applied on pebble-ready event via Scenario with Container, verify replan triggered on config-changed, verify WaitingStatus when container not connected, verify run-check pebble action returns pass when service running

**Checkpoint**: US2 complete — workload managed via Pebble with proper lifecycle

---

## Phase 5: User Story 3 — Configuration (P3)

**Goal**: Handle all 5 config types with validation, blocking on invalid values

**Independent Test**: Deploy → `juju config norma-k8s calibration-string=test` → `juju run norma-k8s/0 get-config` → verify new value

### Implementation

- [X] T019 [US3] Enhance `_reconcile()` in `src/charm.py`: call `norma.validate_config()` with current config dict, if invalid set `self._forced_status = ops.BlockedStatus(error_msg)` and return early; pass validated config values to Pebble layer environment via updated `build_pebble_layer()` call
- [ ] T020 [US3] Add secret config resolution in `_reconcile()` in `src/charm.py`: if `self.config.get("calibration_secret")` is set, resolve via `self.model.get_secret(id=secret_uri)` and call `secret.get_content(refresh=True)`, handle `SecretNotFoundError` with BlockedStatus; observe `secret-changed` event routed to `_reconcile` per research.md R4
- [ ] T021 [US3] Add `get-config` action to `charmcraft.yaml` actions section and implement `_on_get_config_action` handler in `src/charm.py`: return all current config values as action results (`calibration-string`, `calibration-int`, `calibration-float`, `calibration-bool`, `calibration-secret` as "set"/"unset" without exposing content)
- [ ] T022 [US3] Add configuration unit tests in `tests/unit/test_charm.py`: verify valid config → ActiveStatus with Scenario config, verify invalid port (0 or 99999) → BlockedStatus, verify config-changed triggers Pebble replan, verify get-config action returns all values, verify secret config resolution with mock secret

**Checkpoint**: US3 complete — all config types handled with validation

---

## Phase 6: User Story 4 — Status Reporting (P4)

**Goal**: Implement collect_unit_status/collect_app_status with all status types and forced status via action

**Independent Test**: Deploy → `juju run norma-k8s/0 set-status status=blocked message="test"` → `juju status` → verify blocked

### Implementation

- [X] T023 [US4] Implement `_on_collect_unit_status` in `src/charm.py`: check `_forced_status` instance variable first, then check config validation (BlockedStatus), then check Pebble connectivity (WaitingStatus "Waiting for Pebble"), otherwise `event.add_status(ops.ActiveStatus())`; implement `_on_collect_app_status` on leader: aggregate from `_forced_status` if set
- [ ] T024 [US4] Add `set-status` action to `charmcraft.yaml` actions section (params: status string required, message string default "") and implement `_on_set_status_action` handler in `src/charm.py`: map status string to ops status class (active/blocked/waiting/maintenance), store in `_forced_status`, return previous-status and new-status; clear forced status on next successful reconcile if status="active"
- [ ] T025 [US4] Add status unit tests in `tests/unit/test_charm.py`: verify ActiveStatus when healthy via Scenario collect-unit-status, verify BlockedStatus on invalid config, verify WaitingStatus when Pebble disconnected, verify set-status action forces BlockedStatus, verify status priority (forced blocked overrides waiting)

**Checkpoint**: US4 complete — comprehensive status reporting with all types

---

## Phase 7: User Story 5 — Actions (P5)

**Goal**: Implement remaining action infrastructure: fail-action, action progress logging, error handling

**Independent Test**: Deploy → `juju run norma-k8s/0 fail-action message="expected"` → verify action fails with message

### Implementation

- [ ] T026 [US5] Add `fail-action` action to `charmcraft.yaml` actions section (params: message string default "Intentional failure for testing") and implement `_on_fail_action` handler in `src/charm.py`: call `event.fail(params["message"])`, log the failure to event ledger
- [ ] T027 [US5] Add `event.log()` progress logging to key action handlers in `src/charm.py` (get-event-log, get-config, run-check, set-status, fail-action) for operator visibility during execution
- [ ] T028 [US5] Add action unit tests in `tests/unit/test_charm.py`: verify fail-action calls `event.fail()` with provided message via Scenario action run, verify action with valid params returns structured results, verify progress logging occurs

**Checkpoint**: US5 complete — all action patterns demonstrated

---

## Phase 8: User Story 6 — Peer Relations & Leadership (P6)

**Goal**: Handle peer relation data exchange, leader writes to app bag, units write to unit bags

**Independent Test**: Deploy 3 units → `juju run norma-k8s/0 get-peer-data` → verify all see peer data

### Implementation

- [ ] T029 [US6] Enhance `_reconcile()` in `src/charm.py`: get peer relation via `self.model.get_relation("norma-peers")`, write to `relation.data[self.unit]` with `{"unit-name": self.unit.name, "leader": str(self.unit.is_leader()), "timestamp": now}`, if leader write to `relation.data[self.app]` with `{"cluster-size": str(len(relation.units)+1), "leader-unit": self.unit.name}`
- [ ] T030 [US6] Add `get-peer-data` action to `charmcraft.yaml` actions section and implement `_on_get_peer_data_action` handler in `src/charm.py`: read peer relation, return `app-data` (dict from `relation.data[self.app]`), `unit-data` (dict mapping unit names to their data bags)
- [ ] T031 [US6] Add peer relation unit tests in `tests/unit/test_charm.py`: verify unit data written to peer relation on reconcile via Scenario with PeerRelation, verify leader writes app data, verify non-leader does not write app data, verify get-peer-data returns correct structure

**Checkpoint**: US6 complete — peer relation data flows correctly between units

---

## Phase 9: User Story 7 — Provides/Requires Relations (P7)

**Goal**: Handle calibration provides/requires endpoints for two-instance relation testing and inter-charm integration

**Independent Test**: Deploy two instances (`norma-k8s` + `norma-k8s-peer`) → `juju integrate norma-k8s:calibration-provider norma-k8s-peer:calibration-requirer` → `juju run norma-k8s/0 get-relation-data endpoint=calibration-provider` → verify data

### Implementation

- [ ] T032 [US7] Add calibration relation event handling in `src/charm.py` `__init__`: observe relation-created/joined/changed/departed/broken for both `calibration_provider` and `calibration_requirer` endpoints routed to `_reconcile()`; in `_reconcile()`, for each calibration relation write role and unit name to unit data bag per research.md R3 (use unit-level databags for cross-relation safety); in relation-departed handler, log `event.departing_unit.name` to event ledger extra data as `{"departing-unit": unit_name}` to verify departing unit identity (per Juju CI `departer` charm pattern)
- [ ] T033 [US7] Add `get-relation-data` action to `charmcraft.yaml` actions section (params: endpoint string required, relation-id integer optional) and implement `_on_get_relation_data_action` handler in `src/charm.py`: iterate relations for endpoint, return `{"relations": [{"id": int, "app-data": dict, "units": {unit_name: dict}}]}`; filter by relation-id if provided
- [ ] T034 [US7] Add relation unit tests in `tests/unit/test_charm.py`: verify relation events are logged to ledger, verify data written to provider/requirer relation bags via Scenario with Relation, verify get-relation-data returns correct structure, verify two-instance relation scenario (separate apps with same charm), verify departing unit identity logged in relation-departed extra data

**Checkpoint**: US7 complete — provides/requires relation working between two charm instances

---

## Phase 10: User Story 8 — Scaling (P8)

**Goal**: Report cluster membership information across scale operations

**Independent Test**: Deploy → scale to 3 → `juju run norma-k8s/0 get-cluster-info` → verify unit-count=3

### Implementation

- [ ] T035 [US8] Add `get-cluster-info` action to `charmcraft.yaml` actions section and implement `_on_get_cluster_info_action` handler in `src/charm.py`: return `unit-count` (`len(peer_rel.units)+1`), `planned-units` (`self.app.planned_units()`), `leader` (leader unit name from peer app data), `is-leader` (`self.unit.is_leader()`), `units` (list of all unit names including self)
- [ ] T036 [US8] Add scaling unit tests in `tests/unit/test_charm.py`: verify get-cluster-info returns correct count for single unit, verify correct count with 2 peer units in Scenario, verify leader identity reported correctly

**Checkpoint**: US8 complete — cluster info accurately reported

---

## Phase 11: User Story 9 — Juju Secrets (P9)

**Goal**: Full secret lifecycle: create, rotate, expire, remove, share ID via peer data

**Independent Test**: Deploy → `juju run norma-k8s/0 get-secret-info` → verify secret exists with rotation policy

### Implementation

- [ ] T037 [US9] Add secret creation in `_reconcile()` in `src/charm.py`: on leader-elected (check if secret-id missing from peer app data), create app-owned secret via `self.app.add_secret({"password": secrets.token_urlsafe(24)}, label="calibration-password", rotate=SecretRotate.MONTHLY)`, store `secret.id` in peer app data key `"secret-id"`
- [ ] T038 [US9] Add secret event handlers in `src/charm.py` `__init__`: observe `secret-rotate` → create new revision with `secret.set_content({"password": secrets.token_urlsafe(24)})`, observe `secret-expired` → log cleanup to ledger, observe `secret-remove` → call `event.secret.remove_revision()` to clean obsolete revisions; add secret grant/revoke in relation handlers: in `_reconcile()` when a calibration-provider relation exists and leader, call `secret.grant(relation)` to share access; in relation-broken handler call `secret.revoke(relation)` to remove access
- [ ] T039 [US9] Add `get-secret-info` action to `charmcraft.yaml` actions section and implement `_on_get_secret_info_action` handler in `src/charm.py`: read secret-id from peer app data, attempt `self.model.get_secret(id=secret_id)` to verify existence, return `{"secret-id": str, "has-content": bool, "rotation": "monthly"}`
- [ ] T040 [US9] Add secret unit tests in `tests/unit/test_charm.py`: verify secret created on leader-elected via Scenario with Secret, verify secret ID stored in peer relation app data, verify secret-rotate creates new content, verify get-secret-info returns correct metadata, verify secret.grant() called when calibration-provider relation joins, verify secret.revoke() called on relation-broken

**Checkpoint**: US9 complete — full secret lifecycle operational

---

## Phase 12: User Story 10 — Storage (P10)

**Goal**: Persist marker file to filesystem storage, verify survival across restarts

**Independent Test**: Deploy → `juju run norma-k8s/0 check-storage` → verify attached and marker exists

### Implementation

- [ ] T041 [US10] Add storage handling in `_reconcile()` in `src/charm.py`: check if storage `data` is attached via `self.model.storages`, write marker file to `/var/lib/norma/calibration-marker.json` using atomic write (write to `.tmp` then `os.rename`) with `{"created_by": self.unit.name, "created_at": now_iso, "revision": int}`; observe `storage-detaching` event and log to ledger
- [ ] T042 [US10] Add `check-storage` action to `charmcraft.yaml` actions section and implement `_on_check_storage_action` handler in `src/charm.py`: return `attached` (bool), `mount-point` ("/var/lib/norma"), `marker-exists` (bool), `marker-content` (JSON if exists), `writable` (test write then delete)
- [ ] T043 [US10] Add storage unit tests in `tests/unit/test_charm.py`: verify marker file logic with Scenario Storage, verify check-storage returns correct data when attached, verify storage-detaching event logged to ledger

**Checkpoint**: US10 complete — storage persistence verified

---

## Phase 13: User Story 11 — Pebble Health Checks (P11)

**Goal**: Configure Pebble HTTP and exec health checks, handle check-failed/recovered events

**Independent Test**: Deploy → `toggle-health` → wait for pebble-check-failed → toggle back → wait for pebble-check-recovered

### Implementation

- [X] T044 [US11] Add health check definitions to Pebble layer in `src/norma.py` `build_pebble_layer()`: add `checks` dict with `health` (HTTP `http://localhost:{port}/health`, level `ready`, period `10s`, threshold 3), `alive` (exec `["/bin/norma", "--check"]`, level `alive`, period `30s`), and `tcp-alive` (TCP port `{port}`, level `alive`, period `30s`)
- [ ] T045 [US11] Add `pebble-check-failed` and `pebble-check-recovered` event handlers in `src/charm.py` `__init__`: observe for norma container, log to event ledger with check name as extra `{"check": event.info.name}`, on check-failed optionally update status
- [ ] T046 [US11] Add `toggle-health` action to `charmcraft.yaml` actions section (params: container string default "norma") and implement `_on_toggle_health_action` handler in `src/charm.py`: check if flag file exists via `container.exists(HEALTH_FLAG_FILE)`, if exists remove via `container.remove_path()` (→ healthy), if not exists create via `container.push(HEALTH_FLAG_FILE, "unhealthy")` (→ unhealthy); return `{"previous-state": str, "new-state": str}`
- [ ] T047 [US11] Add health check unit tests in `tests/unit/test_charm.py`: verify all three checks (HTTP, exec, TCP) present in Pebble layer from `build_pebble_layer()`, verify check-failed event logged to ledger, verify toggle-health action creates flag file when healthy and removes when unhealthy

**Checkpoint**: US11 complete — health checks functional with toggle mechanism

---

## Phase 14: User Story 12 — Pebble File Operations & Exec (P12)

**Goal**: Exercise all Pebble file and exec operations via test-pebble-ops action

**Independent Test**: Deploy → `juju run norma-k8s/0 test-pebble-ops` → verify all operations pass

### Implementation

- [ ] T048 [US12] Add `test-pebble-ops` action to `charmcraft.yaml` actions section (params: container string default "norma") and implement `_on_test_pebble_ops_action` handler in `src/charm.py`: execute operation suite — **file ops**: `push` (write test file), `pull` (read back and verify content match), `make-dir` (create nested dir with `make_parents=True`), `list-files` (verify dir contents), `exec` (run `echo test` and capture stdout), `exec-fail` (run failing command, catch `ExecError`), `remove-path` (delete test file), `permissions` (push with specific permissions, verify via exec `stat`), `exists` (verify `container.exists()` for known path); **service ops**: `stop` (`container.stop("norma")` then verify via `get_services()`), `start` (`container.start("norma")` then verify active), `restart` (`container.restart("norma")`), `get-plan` (`container.get_plan()` returns expected layer structure), `get-services` (`container.get_services()` lists running services); return pass/fail for each operation and `summary` ("N/M passed")
- [ ] T049 [US12] Add pebble ops unit tests in `tests/unit/test_charm.py`: verify test-pebble-ops action runs through all file ops and service ops via Scenario, verify pass/fail results reported for each operation, verify summary format, verify service stop/start/restart sequences

**Checkpoint**: US12 complete — all Pebble file and exec operations validated

---

## Phase 15: User Story 13 — Pebble Custom Notices (P13)

**Goal**: Handle custom notices from workload container via pebble-custom-notice event

**Independent Test**: Deploy → `juju run norma-k8s/0 trigger-notice` → `get-event-log event-filter=notice` → verify recorded

### Implementation

- [ ] T050 [US13] Add `pebble-custom-notice` event handler for norma container in `src/charm.py` `__init__`: observe the event, in handler extract `event.notice.key`, log to event ledger with extra `{"notice-key": key}` (notice payload omitted — may contain secrets)
- [ ] T051 [US13] Add `trigger-notice` action to `charmcraft.yaml` actions section (params: key string default "canonical.com/norma/calibration-test", data string default "{}") and implement `_on_trigger_notice_action` handler in `src/charm.py`: execute `container.exec(["pebble", "notify", key, ...data_args])` inside the norma container, return `{"notice-sent": true, "key": key}`
- [ ] T052 [US13] Add notice unit tests in `tests/unit/test_charm.py`: verify pebble-custom-notice handler logs event with key, verify trigger-notice action calls container.exec with correct pebble notify command

**Checkpoint**: US13 complete — custom notice communication working

---

## Phase 16: User Story 14 — Networking & Ports (P14)

**Goal**: Open workload port on startup, report ports and bindings via action

**Independent Test**: Deploy → `juju run norma-k8s/0 test-networking` → verify port opened and bindings reported

### Implementation

- [X] T053 [US14] Add port management in `_reconcile()` in `src/charm.py`: after Pebble layer applied, call `self.unit.set_ports(ops.Port("tcp", config_port))` to declare the workload port
- [ ] T054 [US14] Add `test-networking` action to `charmcraft.yaml` actions section and implement `_on_test_networking_action` handler in `src/charm.py`: return `opened-ports` (list from `self.unit.opened_ports()`), `bindings` (dict mapping key endpoints like "norma-peers", "calibration-provider" to their ingress/bind addresses via `self.model.get_binding(endpoint).network`)
- [ ] T055 [US14] Add networking unit tests in `tests/unit/test_charm.py`: verify `set_ports` called in reconcile with correct port, verify test-networking action returns port and binding data

**Checkpoint**: US14 complete — port management and network bindings operational

---

## Phase 17: User Story 15 — Upgrade/Refresh (P15)

**Goal**: Handle upgrade-charm event, track and report charm/workload versions

**Independent Test**: Deploy → `juju run norma-k8s/0 get-version` → refresh → verify version changed

### Implementation

- [ ] T056 [US15] Enhance upgrade-charm handling in `_reconcile()` in `src/charm.py`: log upgrade event to ledger with extra `{"type": "upgrade"}`, re-apply Pebble layer (already done in reconcile), read charm version from `version` file (written by charmcraft build `git describe`), call `self.unit.set_workload_version()` from workload `/version` response
- [ ] T057 [US15] Add `get-version` action to `charmcraft.yaml` actions section and implement `_on_get_version_action` handler in `src/charm.py`: return `charm-version` (read `version` file from charm root with fallback "unknown"), `workload-version` (from last set_workload_version value or container exec curl `/version`)
- [ ] T058 [US15] Add upgrade unit tests in `tests/unit/test_charm.py`: verify upgrade-charm triggers reconcile and logs upgrade event, verify get-version returns both versions

**Checkpoint**: US15 complete — version tracking and upgrade handling operational

---

## Phase 18: User Story 16 — Multiple Containers (P16)

**Goal**: Manage secondary container with independent Pebble layer and health check

**Independent Test**: Deploy → verify both containers running → `juju run norma-k8s/0 test-pebble-ops container=norma-secondary` → verify pass

### Implementation

- [X] T059 [US16] Complete `build_secondary_layer(version)` in `src/norma.py`: service `norma-secondary`, override replace, startup enabled, command `/bin/norma`, environment `PORT=8081` and `VERSION`, user `_daemon_`, health check `health-secondary` HTTP on `http://localhost:8081/health` level ready period 10s threshold 3
- [ ] T060 [US16] Add secondary container pebble-ready handling in `src/charm.py`: in the already-observed `norma-secondary` pebble-ready handler within `_reconcile()`, apply secondary layer from `norma.build_secondary_layer()`, call secondary container `replan()`, handle independently from primary (check each container's connectivity separately)
- [ ] T061 [US16] Add multi-container unit tests in `tests/unit/test_charm.py`: verify independent pebble-ready events for each container in Scenario, verify different layers applied (different service names, different ports), verify secondary container gets port 8081

**Checkpoint**: US16 complete — both containers independently managed

---

## Phase 19: User Story 17 — Non-Root Security & Trust (P17)

**Goal**: Verify non-root execution and trust/credential access via action

**Independent Test**: Deploy with `--trust` → `juju run norma-k8s/0 check-security` → verify non-root UID and trust available

### Implementation

- [ ] T062 [US17] Add `check-security` action to `charmcraft.yaml` actions section and implement `_on_check_security_action` handler in `src/charm.py`: return `charm-uid` (`os.getuid()`), `charm-gid` (`os.getgid()`), `workload-uid`/`workload-gid` (via `container.exec(["id", "-u"])` and `["id", "-g"]`), `trust-available` (try `self.model.get_cloud_spec()` in try/except, True if accessible), `cloud-type` and `credential-attrs` if trust granted
- [ ] T063 [US17] Add security unit tests in `tests/unit/test_charm.py`: verify check-security action returns UID/GID fields, verify trust detection logic with and without trust

**Checkpoint**: US17 complete — security posture validated

---

## Phase 20: User Story 18 — COS Observability Integration (P18)

**Goal**: Integrate with Prometheus, Grafana, and Loki via COS charm libraries

**Independent Test**: Deploy with COS → `juju integrate norma-k8s:metrics-endpoint prometheus-k8s` → verify metrics scraped

### Implementation

- [ ] T064 [US18] Fetch COS charm libraries via `charmcraft fetch-libs` (prometheus_scrape, grafana_dashboard, loki_push_api) into `lib/charms/` and add initialization in `src/charm.py` `__init__`: `MetricsEndpointProvider(self, jobs=[{"static_configs": [{"targets": [f"*:{port}"]}]}])`, `GrafanaDashboardProvider(self)`, `LogForwarder(self, relation_name="log-proxy")` per research.md R5
- [ ] T065 [P] [US18] Create Grafana dashboard JSON in `src/grafana_dashboards/norma.json`: panels for HTTP request rate (`rate(norma_http_requests_total[5m])`), health status gauge (`norma_healthy`), health toggle count (`norma_health_toggles_total`), with templated datasource variable
- [ ] T066 [P] [US18] Create Prometheus alert rules in `src/prometheus_alert_rules/norma_alerts.yaml`: `NormaWorkloadDown` (up == 0 for 1m), `NormaHealthCheckFailing` (`norma_healthy == 0` for 2m), `NormaHighErrorRate` (rate of 500 status responses)
- [ ] T067 [US18] Add COS unit tests in `tests/unit/test_charm.py`: verify MetricsEndpointProvider initialized with correct jobs config, verify GrafanaDashboardProvider initialized, verify LogForwarder initialized with relation_name "log-proxy"

**Checkpoint**: US18 complete — full COS observability stack integrated

---

## Phase 21: User Story 19 — Cross-Model Relations (P19)

**Goal**: Verify calibration endpoints work identically for cross-model relations

**Independent Test**: Deploy in two models → `juju offer` → consume → integrate → verify data exchange

### Implementation

- [ ] T068 [US19] Verify CMR compatibility in `src/charm.py`: ensure calibration-provider and calibration-requirer relation handlers make no assumptions about same-model deployment (no hardcoded app names), add remote app name to event ledger extra data for relation events `{"remote-app": event.app.name if event.app else "unknown"}`
- [ ] T069 [US19] Add CMR unit tests in `tests/unit/test_charm.py`: verify relation handlers work with remote app from different model context using Scenario Relation with different app names, verify no same-model assumptions in data exchange

**Checkpoint**: US19 complete — cross-model relation support verified

---

## Phase 22: User Story 20 — Event Deferral (P20)

**Goal**: Arm deferral via action, defer eligible events, log deferrals and re-emissions

**Independent Test**: Deploy → `juju run norma-k8s/0 test-defer arm=true` → `juju config norma-k8s calibration-string=trigger` → `get-event-log event-filter=defer` → verify deferred and re-emitted

### Implementation

- [ ] T070 [US20] Add deferral arming mechanism in `src/charm.py`: instance variable `_defer_armed = False` set in `__init__`, in `_reconcile()` check if `_defer_armed` and event is deferrable (not action, not secret-rotate/expired, not update-status) → call `event.defer()`, log `{"deferred": "true"}` in event ledger, set `_defer_armed = False` after deferring; detect re-emitted events via `event.deferred` attribute and log `{"re-emitted": "true"}`
- [ ] T071 [US20] Add `test-defer` action to `charmcraft.yaml` actions section (params: arm boolean default true) and implement `_on_test_defer_action` handler in `src/charm.py`: read current `_defer_armed` as previous_state, set `_defer_armed = params["arm"]`, return `{"deferral-armed": bool, "previous-state": bool}`
- [ ] T072 [US20] Add deferral unit tests in `tests/unit/test_charm.py`: verify arming sets `_defer_armed` flag, verify deferred event logged with `deferred: true` extra, verify re-emission detected with `re-emitted: true`, verify action events are not deferred (RuntimeError)

**Checkpoint**: US20 complete — event deferral mechanism fully validated

---

## Phase 23: User Story 21 — OCI Resource Lifecycle (P21)

**Goal**: Verify charm handles OCI image resource refresh gracefully — container restart triggers pebble-ready and reconcile

**Independent Test**: Deploy → `juju attach-resource norma-k8s norma-image=<new-image>` → verify pebble-ready fires → charm returns to active → `get-version` reflects new workload version

### Implementation

- [ ] T073 [US21] Verify OCI resource refresh handling in `src/charm.py`: confirm that `_reconcile()` already handles pebble-ready from resource refresh (no new code expected — reconciler re-applies layer and replans); add resource-related context to event ledger by checking if the pebble-ready event occurs without a prior install (indicates resource refresh or pod restart), log extra `{"trigger": "resource-refresh-or-restart"}` when detected
- [ ] T074 [US21] Add OCI resource lifecycle unit tests in `tests/unit/test_charm.py`: verify pebble-ready triggers full reconcile (layer apply + replan) regardless of whether it's first-time or re-fire (resource refresh scenario), verify event ledger records pebble-ready with appropriate context

**Checkpoint**: US21 complete — OCI resource lifecycle validated through existing reconciler

---

## Phase O1: CI Pipeline (Orthogonal — Can Be Done at Any Time)

**Purpose**: Configure GitHub Actions CI workflow for automated lint, unit tests, charm pack, and integration tests

**Dependencies**: None — can be started after Phase 1 (Setup) or deferred until after MVP

- [ ] T075 [P] Create `.github/workflows/ci.yaml` with: trigger on push/PR to main and feature branches; jobs for `lint` (ruff check+format via `make lint`), `unit` (pytest via `make unit` with coverage), `pack` (charmcraft pack), `integration` (optional, manual trigger, requires MicroK8s + Juju bootstrap); use `ubuntu-24.04` runner, `astral-sh/setup-uv` action, Python 3.12+; cache uv dependencies
- [ ] T076 [P] Create `.github/workflows/rock.yaml` with: trigger on push/PR when `workload/**` or `rockcraft.yaml` changed; jobs for `build` (rockcraft pack), `test` (build Go binary + run `go test ./...`); use `ubuntu-24.04` runner, `snap install rockcraft --classic`, `snap install go --classic`

**Checkpoint**: CI pipeline operational — PRs get automated lint, test, and pack validation

---

## Phase O2: Integration Tests (Orthogonal — After Corresponding Stories Complete)

**Purpose**: Create jubilant-based integration tests that deploy the charm and validate each user story cluster against a real Juju controller

**Dependencies**: Each test group requires its corresponding user stories to be implemented. Can be started incrementally as story clusters are completed.

- [ ] T082 [P] Create `tests/integration/test_lifecycle.py` and `tests/integration/test_pebble.py` (US1-US2): deploy charm, verify active status within 120s, verify event ledger records install/leader-elected/config-changed/start in order, verify workload HTTP responds 200 on `/ready`, verify Pebble layer applied with correct service definition
- [ ] T083 [P] Create `tests/integration/test_config.py`, `tests/integration/test_status.py`, and `tests/integration/test_actions.py` (US3-US5): set each config type via `juju config`, verify get-config returns updated values, verify BlockedStatus on invalid config, verify set-status action forces status, verify fail-action reports failure, verify event.log() progress visible
- [ ] T084 [P] Create `tests/integration/test_relations.py` and `tests/integration/test_scaling.py` (US6-US8): deploy 3 units, verify get-peer-data returns all units, verify leader writes app data, verify two-instance relation via deploying `norma-k8s-peer` and `juju integrate norma-k8s:calibration-provider norma-k8s-peer:calibration-requirer`, verify get-relation-data, scale to 3 then back to 1, verify get-cluster-info reflects correct counts
- [ ] T085 [P] Create `tests/integration/test_secrets.py` and `tests/integration/test_storage.py` (US9-US10): verify get-secret-info returns secret with rotation policy, verify check-storage shows attached with marker file, verify storage data survives unit restart
- [ ] T086 [P] Create `tests/integration/test_health_checks.py`, `tests/integration/test_pebble_ops.py`, and `tests/integration/test_notices.py` (US11-US13): toggle-health action → wait for pebble-check-failed → toggle back → wait for pebble-check-recovered, run test-pebble-ops and verify all operations pass, trigger-notice and verify event-log records custom notice
- [ ] T087 [P] Create `tests/integration/test_networking.py`, `tests/integration/test_upgrade.py`, `tests/integration/test_multi_container.py`, and `tests/integration/test_security.py` (US14-US17): verify test-networking reports open port and bindings, juju refresh to new revision and verify get-version changes, verify both containers running independently via test-pebble-ops container=norma-secondary, deploy with --trust and verify check-security reports non-root UID and trust available
- [ ] T088 [P] Create `tests/integration/test_observability.py`, `tests/integration/test_cmr.py`, `tests/integration/test_defer.py`, and `tests/integration/test_oci_resource.py` (US18-US21): verify COS relation setup (metrics-endpoint integration), verify cross-model offer/consume cycle, arm deferral via test-defer then trigger config-changed and verify event-log shows deferred+re-emitted, attach new OCI resource and verify pebble-ready re-fires

**Checkpoint**: All integration test files created (US1-US21 + US22 introspect + US24 multi-storage) — `make integration` validates full charm behavior against live Juju

---

## Phase 25: User Story 22 — Charm Introspection (Priority: P22)

**Purpose**: Single action returns comprehensive structured report of all internal charm state with optional section filtering

**Dependencies**: All prior user stories (collectors read data populated by US1-US24)

- [ ] T089 Add `introspect` action definition with `sections` parameter to `charmcraft.yaml` per `contracts/actions-schema.yaml`. Register `introspect_action` observer in `__init__` and add `REPORT_SECTIONS` constant (identity, version, leadership, config, event-ledger, relations, storage, containers, secrets) in `src/charm.py`
- [ ] T090 [P] Implement 9 section collectors (`_collect_identity`, `_collect_version`, `_collect_leadership`, `_collect_config`, `_collect_event_ledger`, `_collect_relations`, `_collect_storage`, `_collect_containers`, `_collect_secrets`) as private methods on the charm class, each returning a plain dict and wrapped in try/except for graceful degradation (`{"status": "unavailable", "reason": "..."}`), in `src/charm.py`
- [ ] T091 Wire all collectors into `_on_introspect_action` handler: call each collector, JSON-encode each section, set action results with `timestamp` and `unit` metadata. Add truncation logic (if total payload exceeds 250KB, truncate largest section). Add section filtering: parse `sections` param as comma-separated list, intersect with `REPORT_SECTIONS`, run only matching collectors; empty filter returns all sections; invalid section names silently ignored. In `src/charm.py`
- [ ] T092 [P] Add unit tests for introspect action in `tests/unit/test_charm.py`: `TestIntrospectAction` class with tests for: all-sections returned, identity section accuracy, config section with changed values, containers when disconnected (graceful degradation), relations section lists endpoints, section filter returns only requested sections, empty filter returns all, invalid section silently ignored, non-leader handling, truncation on large payload
- [ ] T093 CLI Acceptance (Constitution VIII): Deploy charm, run `juju run norma-k8s/0 introspect`, verify all 9 sections present with accurate data. Run with `sections=config,leadership` and verify only those sections returned. Run with `sections=config,nonexistent` and verify only config returned. Verify action completes within 5 seconds.

**Checkpoint**: `juju run norma-k8s/0 introspect` returns full structured report, filtering works, graceful degradation on disconnected containers

---

## Phase 26: US23 — Multi-Architecture OCI Image

**Purpose**: Build ROCK image for amd64 and arm64 so CI can validate multi-arch deployment

**Dependencies**: Phase 2 (rockcraft.yaml exists)

- [ ] T094 Add `arm64` platform to `rockcraft.yaml` alongside existing `amd64`. Add `GOARCH` cross-compilation support in the Go build override (rockcraft Go plugin uses `override-build`). Verify `rockcraft pack` produces an image for the host arch.
- [ ] T095 [P] Add `arm64` platform to `charmcraft.yaml` `platforms:` section (alongside existing `amd64`).
- [ ] T096 CLI Acceptance (Constitution VIII): Build the ROCK on amd64, verify the image manifest includes the correct architecture label. Document multi-arch build procedure for CI (building arm64 images on amd64 requires `rockcraft pack --platform arm64` or QEMU emulation).

**Checkpoint**: `rockcraft.yaml` and `charmcraft.yaml` declare amd64 + arm64 platforms; ROCK builds successfully for host architecture

---

## Phase 27: US24 — Multiple Storage Definitions

**Purpose**: Add a second optional storage to enable independent attachment/detachment testing

**Dependencies**: Phase 9 (US10 storage handling exists)

- [ ] T097 Add `logs` storage definition to `charmcraft.yaml`: type filesystem, minimum-size 512M, multiple-range 0-1 (optional — not provisioned unless explicitly requested). Add mount to `norma` container at `/var/log/norma`.
- [ ] T098 Add `LOGS_STORAGE_PATH` constant to `src/norma.py` with value `/var/log/norma` and `LOGS_MARKER_FILE` constant with value `logs-marker.json`.
- [ ] T099 Extend `_on_check_storage_action` in `src/charm.py` to accept a `name` parameter (default `data`). When `name=logs`, check the `logs` storage mount path instead of `data`. Write/read a logs marker file analogous to the data marker. Report storage as unavailable (not fail) if the storage is not attached.
- [ ] T100 Extend `_collect_storage` introspect collector in `src/charm.py` to enumerate all declared storages (both `data` and `logs`), reporting status for each.
- [ ] T101 [P] Add unit tests for multiple storage in `tests/unit/test_charm.py`: `TestMultipleStorage` class with tests for: check-storage with name=data (existing), check-storage with name=logs when attached, check-storage with name=logs when not attached (reports unavailable), introspect storage section lists both storages.
- [ ] T102 CLI Acceptance (Constitution VIII): Deploy charm, verify only `data` storage attached. Run `juju add-storage norma-k8s/0 logs=1`. Verify `juju run norma-k8s/0 check-storage name=logs` reports available. Run `juju run norma-k8s/0 introspect sections=storage` and verify both storages listed.

**Checkpoint**: `check-storage name=logs` works, introspect lists both storages, `logs` storage is independently attachable

---

## Phase 24: Polish & Cross-Cutting Concerns

**Purpose**: Validation, cleanup, and final integration across all user stories

- [ ] T077 Validate all 17 actions in `charmcraft.yaml` match `contracts/actions-schema.yaml` parameter definitions, types, defaults, and descriptions
- [ ] T078 Validate `charmcraft.yaml` structure matches `contracts/charmcraft-schema.yaml` for containers, resources, storage, config, relations, charm-libs, and charm-user
- [ ] T079 [P] Run `make lint` (ruff check and format) and fix all lint issues across `src/charm.py`, `src/norma.py`, and `tests/`
- [ ] T080 [P] Run `make unit` and verify all unit tests pass with coverage report; ensure `tests/unit/test_norma.py` and `tests/unit/test_charm.py` both pass
- [ ] T081 Run quickstart.md validation: verify build commands work, deploy instructions are accurate, and per-story test commands match implemented action names and parameters

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — **BLOCKS all user stories**
- **User Stories (Phases 3-23)**: All depend on Foundational phase completion
  - US1 (Lifecycle) is the MVP — complete first
  - US2-US21 proceed in priority order or parallel if staffed
  - See cross-story dependencies below
- **CI Pipeline (Phase O1)**: Orthogonal — can start after Setup, defer until post-MVP, or do anytime
- **Integration Tests (Phase O2)**: Orthogonal — each test group can start after its story cluster is implemented
- **Introspection (Phase 25)**: Depends on foundational stories (US1-US9) being complete; can run before US10-US21
- **Multi-Arch (Phase 26)**: Depends on Phase 2 (rockcraft.yaml); can run anytime after Foundational
- **Multiple Storage (Phase 27)**: Depends on Phase 9 (US10 storage); extends existing storage handling
- **Polish (Phase 24)**: Depends on all user stories being complete

### Cross-Story Dependencies

Most stories are independent after Foundational. Notable dependencies:

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
| US22 (Introspect) | US1-US9 | Collectors read data populated by prior stories |
| US24 (Multi-Storage) | US10 (Storage) | Extends existing storage handling |
| All stories | US1 (Lifecycle) | Event ledger used for verification |

### Within Each User Story

1. Implementation tasks first (modify `src/charm.py` and `src/norma.py`)
2. Unit test tasks (add to `tests/unit/test_charm.py`)
3. Story checkpoint validation

### Parallel Opportunities

**Within Setup** (Phase 1):
- T003 (Makefile) ∥ T004 (uv sync)

**Within Foundational** (Phase 2):
- T005 (Go binary) ∥ T006 (go.mod) ∥ T007 (rockcraft.yaml) — independent files
- T009 (norma.py) ∥ T011 (test infra) — different files
- T010 (charm.py) depends on T009 (norma.py)
- T012 (test_charm.py) depends on T010 (charm.py)

**Within US18** (COS):
- T065 (Grafana dashboard) ∥ T066 (alert rules) — independent files

**Across Stories** (with team):
- After Foundational + US1: independent story clusters can parallelize:
  - **Cluster A**: US3, US4, US5 (config → status → actions)
  - **Cluster B**: US6, US8, US9 (peer → scaling/secrets)
  - **Cluster C**: US2, US11, US12, US13, US16 (Pebble features)
  - **Cluster D**: US14, US15, US17 (networking/upgrade/security)
  - **Cluster E**: US7, US19 (relations → CMR)
  - **Cluster F**: US18, US20, US21 (COS, defer, resource — independent)

---

## Parallel Example: Foundational Phase

```bash
# Launch Go workload + rockcraft in parallel (independent files):
Task: "Implement Go workload binary in workload/main.go"
Task: "Create workload/go.mod with Go 1.22 and prometheus dependency"
Task: "Create rockcraft.yaml at repo root"

# Then launch norma.py + test infra in parallel:
Task: "Implement workload abstraction in src/norma.py"
Task: "Create test infrastructure in tests/"
```

## Parallel Example: User Story 18 (COS)

```bash
# Launch COS assets in parallel (independent files):
Task: "Create Grafana dashboard JSON in src/grafana_dashboards/norma.json"
Task: "Create Prometheus alert rules in src/prometheus_alert_rules/norma_alerts.yaml"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: US1 — Charm Lifecycle Events
4. **STOP and VALIDATE**: Deploy charm, run `get-event-log`, verify lifecycle events
5. This delivers a deployable charm that logs all events

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 (Lifecycle) → Test → **MVP!**
3. US2 (Pebble) → Test → Workload managed
4. US3-US5 (Config/Status/Actions) → Test → Core operator experience
5. US6-US7 (Peer/Relations) → Test → Multi-unit and cross-charm
6. US8-US10 (Scaling/Secrets/Storage) → Test → Stateful operations
7. US11-US13 (Health/Pebble Ops/Notices) → Test → Advanced Pebble
8. US14-US17 (Network/Upgrade/Multi-Container/Security) → Test → Operational
9. US18-US21 (COS/CMR/Defer/Resource) → Test → Full calibration suite
   9a. US22 (Introspection) → Test → Single-call state report
   9b. US23 (Multi-Arch) → Build → Multi-architecture OCI images
   9c. US24 (Multi-Storage) → Test → Independent storage operations
10. Polish → **Complete!**
11. CI Pipeline (Phase O1) → Can be done at any point from step 1 onward
12. Integration Tests (Phase O2) → Can start after each story cluster is complete

### Sequential Strategy (Single Developer / LLM)

Work through phases sequentially P1→P21. Each story extends `src/charm.py` and `src/norma.py` incrementally. Unit tests validate each increment before proceeding.

---

## Notes

- [P] tasks = different files, no dependencies within same phase
- [USn] label maps task to specific user story for traceability
- Each user story independently completable and testable after Foundational phase
- `src/charm.py` grows incrementally — each story adds handlers and action code
- `src/norma.py` grows with workload-specific logic (layers, config, validation)
- `tests/unit/test_charm.py` grows with tests per story
- Commit after each completed story phase
- Stop at any checkpoint to validate story independently
