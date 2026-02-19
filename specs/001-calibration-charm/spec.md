# Feature Specification: Juju K8s Calibration Charm

**Feature Branch**: `001-calibration-charm`
**Created**: 2026-02-10
**Status**: Clarified
**Input**: Create a calibration K8s charm for Juju CI that exercises all Juju features and capabilities relevant to K8s charms.

## Clarifications

### Session 2026-02-10

- Q: Should the charm be active immediately after deploy (no required relations), or require specific relations to become active? → A: Active by default — all relations optional; charm is fully functional without any integrations; status tests use action-triggered conditions instead.
- Q: Should event deferral be a separate user story or folded into lifecycle? → A: Add a new User Story 20 — dedicated story testing defer, re-emit, ordering, and non-deferrable events.
- Q: Should Juju trust / cloud credential access be tested? → A: Add to US17 (Security) — extend the security story with trust scenarios.
- Q: What should the calibration workload be? → A: Purpose-built Go binary — single static binary with /health, /version, /ready, /metrics, /toggle-health endpoints; ideal for chiselled ROCK.

### Session 2026-02-11

- Q: Where does the Go binary source code reside? → A: In this repo under a `workload/` directory, built as part of the charm CI.
- Q: What should the second container run? → A: Same Go binary on a different port — validates multi-container Pebble lifecycle using the same ROCK image.
- Q: How should the 8 listed edge cases be treated? → A: Keep as-is; resolve during planning phase when task decomposition can assign them to user stories.

### Session 2026-02-18

- Q: Where does the test subordinate charm for US25 come from? → A: Reuse the same juju-norma-k8s charm packed with a different charmcraft.yaml overlay that adds `subordinate: true` and changes the `juju-info` endpoint to `requires` with `scope: container`. This avoids maintaining a separate charm codebase — same code, different packaging.
- Q: How should US10 AC4/AC6/AC7 (attach-storage, import-filesystem, deploy --attach-storage) be handled given Juju's known K8s limitations? → A: Write tests with `xfail(strict=False)` — tests exist and run, marked as expected failures until Juju implements K8s support. This documents expected behavior and auto-detects when support lands.

### Session 2026-02-19

- Q: NFR-005 claims norma-k8s replaces ALL K8s sidecar test charms, but 3 gaps exist (no shell in bare ROCK, no credential-get action, no sudoer overlay). Narrow NFR-005 or add capabilities? → A: Keep NFR-005 as-is (aspirational), add FRs for busybox shell slice in ROCK, credential-get action, and sudoer charmcraft overlay. All three are low-effort additions that fully close the gaps.
- Q: Should storage portability (PV import across models, deploy --attach-storage) be a new US26 or is FR-030 sufficient? → A: FR-030 is sufficient — tests are added to existing storage integration tests under the existing test class, no new user story needed.
- Q: Should the spec list the specific upstream test charms norma-k8s replaces? → A: Add a brief "Replacement Targets" subsection under Assumptions referencing k8s-charm-research.md for details.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Charm Lifecycle Events (Priority: P1)

A Juju CI engineer deploys the calibration charm and verifies that all
lifecycle events fire in the correct order and can be observed. The charm
logs each event with a timestamp and event name to an in-memory event
ledger accessible via a "get-event-log" action. This is the foundation
that all other stories depend on.

**Why this priority**: Without lifecycle events working correctly, no
other Juju feature can be validated. This is the minimal deployable charm.

**Independent Test**: Deploy the charm, wait for active status, run the
get-event-log action, and verify install -> leader-elected ->
config-changed -> start fired in order.

**Acceptance Scenarios**:

1. **Given** a fresh deployment, **When** the charm is deployed, **Then** the event ledger records `install`, `leader-elected` (if leader), `config-changed`, and `start` in that order.
2. **Given** a running charm, **When** a unit is removed, **Then** the event ledger records `stop` followed by `remove`.
3. **Given** a running charm, **When** sufficient time passes (or update-status-hook-interval is shortened), **Then** the `update-status` event fires periodically and is recorded.
4. **Given** a running charm, **When** `juju remove-application --force` is executed, **Then** the application is removed even if hooks fail or hang, and the model returns to a clean state.
5. **Given** a running charm, **When** `juju model-config update-status-hook-interval=30s` is executed, **Then** the `update-status` event fires at approximately the new interval rather than the default, and the event ledger confirms the increased frequency.

---

### User Story 2 - Pebble Workload Management (Priority: P2)

A CI engineer verifies that the charm can manage a workload process
inside a sidecar container via Pebble. The charm defines a Pebble layer
with a simple HTTP server service, starts it, and confirms it is running.
The service responds to health queries so downstream tests can verify
the workload is alive.

**Why this priority**: Pebble is the primary mechanism for K8s charms to
manage workloads. Without it, the charm is an empty shell.

**Independent Test**: Deploy the charm, wait for active status, curl the
workload HTTP endpoint from within the cluster, and verify a 200 response.

**Acceptance Scenarios**:

1. **Given** a deployed charm, **When** the `pebble-ready` event fires, **Then** the charm adds a Pebble layer and starts the workload service.
2. **Given** a running workload, **When** a configuration change modifies the service environment, **Then** the charm replans the service and the workload restarts with updated settings.
3. **Given** a running workload, **When** the pod is rescheduled (container restart), **Then** `pebble-ready` fires again and the charm reconfigures the workload from scratch.
4. **Given** a Pebble layer, **When** the plan is queried, **Then** it contains the expected service definition with `override: replace` and `startup: enabled`.

---

### User Story 3 - Configuration (Priority: P3)

A CI engineer changes configuration values of every supported type
(string, int, float, boolean, secret) and verifies the charm reacts
correctly to each. Invalid configuration values cause the charm to enter
blocked status with a descriptive message.

**Why this priority**: Configuration is a core operator workflow and
validates type handling across the Juju-charm boundary.

**Independent Test**: Deploy the charm, set each config type via
`juju config`, run the get-event-log action to confirm config-changed
fired, and query current config via a "get-config" action.

**Acceptance Scenarios**:

1. **Given** a deployed charm with default config, **When** a string config option is changed, **Then** `config-changed` fires and the new value is accessible in the charm.
2. **Given** a deployed charm, **When** an integer config option is set to a valid value, **Then** the charm applies it and remains active.
3. **Given** a deployed charm, **When** a boolean config option is toggled, **Then** the charm reflects the new value in its workload environment.
4. **Given** a deployed charm, **When** a float config option is set, **Then** the charm reads it with correct precision.
5. **Given** a deployed charm, **When** a secret-type config is set to a Juju secret URI, **Then** the charm resolves and reads the secret content.
6. **Given** a deployed charm, **When** an invalid config value is provided (e.g., negative port), **Then** the charm enters `BlockedStatus` with a message describing the validation error.

---

### User Story 4 - Status Reporting (Priority: P4)

A CI engineer verifies that the charm can set and report all four status
types (Active, Blocked, Waiting, Maintenance) at both unit and
application level. The charm uses the `collect_unit_status` and
`collect_app_status` events to aggregate multiple conditions. A
"set-status" action allows testers to force specific status conditions
for validation.

**Why this priority**: Status reporting is how operators understand charm
health. Testing all status types ensures Juju's status propagation works
end-to-end.

**Independent Test**: Deploy the charm, run the set-status action with
each status type, and verify `juju status` reflects the expected status
and message.

**Acceptance Scenarios**:

1. **Given** a healthy charm, **When** all preconditions are met, **Then** `collect_unit_status` reports `ActiveStatus` with no message.
2. **Given** a running charm, **When** a "set-status" action forces a blocked condition, **Then** `collect_unit_status` reports `BlockedStatus` with a descriptive message.
3. **Given** a running charm, **When** the workload container is not yet ready, **Then** status reports `WaitingStatus`.
4. **Given** a running charm, **When** a maintenance operation is triggered (via action), **Then** `MaintenanceStatus` is reported during the operation.
5. **Given** a leader unit, **When** `collect_app_status` fires, **Then** the application-level status reflects the aggregate health of all units.
6. **Given** multiple status conditions (e.g., blocked config AND waiting for Pebble), **When** status is collected, **Then** the highest-priority status wins (Blocked > Waiting).

---

### User Story 5 - Actions (Priority: P5)

A CI engineer invokes charm actions with various parameter types and
verifies that results are returned, failures are reported, and progress
logs are emitted. The charm defines several actions: "get-event-log"
(returns the event ledger), "get-config" (returns current effective
config), "set-status" (forces a status for testing), "run-check"
(validates a specific capability and returns pass/fail), and "fail-action"
(intentionally fails to test error reporting).

**Why this priority**: Actions are the operator's primary interactive
interface with a charm. They also serve as the test harness for all other
user stories.

**Independent Test**: Deploy the charm, run each action with valid and
invalid params, verify results and failure messages.

**Acceptance Scenarios**:

1. **Given** a deployed charm, **When** an action is invoked with valid parameters, **Then** the action handler fires, processes params, and returns structured results.
2. **Given** a deployed charm, **When** an action is invoked with invalid parameters, **Then** the action fails with a descriptive error message.
3. **Given** a deployed charm, **When** the "fail-action" action is invoked, **Then** the action reports failure via `event.fail()` with the provided message.
4. **Given** a deployed charm, **When** an action emits progress logs via `event.log()`, **Then** the logs are visible to the operator during execution.
5. **Given** a deployed charm, **When** an action handler attempts to defer, **Then** a RuntimeError is raised (actions cannot be deferred).

---

### User Story 6 - Peer Relations & Leadership (Priority: P6)

A CI engineer deploys multiple units and verifies that peer relations
are established automatically, leader election works, and data can be
shared between units via peer relation data bags. The charm writes
unit-specific data to `relation.data[self.unit]` and the leader writes
shared data to `relation.data[self.app]`. A "get-peer-data" action
allows querying peer state from any unit.

**Why this priority**: Peer relations and leadership are the foundation
for multi-unit coordination, which is required for scaling stories.

**Independent Test**: Deploy with 3 units, run get-peer-data on each
unit, verify each unit sees its own data and the leader's app-level data.

**Acceptance Scenarios**:

1. **Given** a single-unit deployment, **When** the charm starts, **Then** the peer relation is created automatically and `leader-elected` fires on that unit.
2. **Given** a multi-unit deployment, **When** a new unit joins, **Then** `relation-joined` fires on existing units for the new peer.
3. **Given** a leader unit, **When** the leader writes to `relation.data[self.app]`, **Then** all peer units can read the data after `relation-changed` fires.
4. **Given** any unit, **When** it writes to `relation.data[self.unit]`, **Then** other peer units can read that unit's data.
5. **Given** a non-leader unit, **When** it attempts to write to `relation.data[self.app]`, **Then** the write is rejected.
6. **Given** a running cluster, **When** the leader unit is removed, **Then** a new leader is elected and receives `leader-elected`.

---

### User Story 7 - Provides/Requires Relations (Priority: P7)

A CI engineer integrates the calibration charm with another charm (or
a second instance of itself) to exercise the full relation lifecycle.
The charm declares both provides and requires endpoints. When integrated,
both sides exchange data via their respective data bags and log all
relation events. Testing uses two instances of the same charm (e.g.,
`norma-k8s` and `norma-k8s-peer`) since Juju 4 does not support
same-application provides/requires self-relations (only peer).

**Why this priority**: Relations are Juju's core mechanism for
inter-charm communication and service composition.

**Independent Test**: Deploy two instances of the calibration charm,
integrate them, verify relation events fire and data is exchanged
bidirectionally via a "get-relation-data" action.

**Acceptance Scenarios**:

1. **Given** two deployed applications, **When** they are integrated via matching interfaces, **Then** `relation-created` and `relation-joined` fire on both sides.
2. **Given** an active relation, **When** the provider sets data in its app bag, **Then** the requirer receives `relation-changed` and can read the data.
3. **Given** an active relation with multiple units on one side, **When** a unit departs, **Then** `relation-departed` fires on the remaining side.
4. **Given** an active relation, **When** the relation is removed (`juju remove-relation`), **Then** `relation-broken` fires on both sides and relation data is no longer accessible.
5. **Given** two instances of the calibration charm deployed as separate applications, **When** they are integrated via the calibration interface (provider ↔ requirer), **Then** the full relation lifecycle works identically to cross-charm relations.
6. **Given** a requires endpoint with `limit: 1`, **When** a second integration is attempted, **Then** the integration is rejected.
7. **Given** an active relation with multiple units, **When** a unit departs, **Then** `event.departing_unit` is set correctly in the `relation-departed` handler, identifying which specific unit is leaving.

---

### User Story 8 - Scaling (Priority: P8)

A CI engineer scales the calibration charm up and down and verifies that
units are added/removed correctly, peer data propagates, and leader
failover works under scaling operations. The charm reports its view of
the cluster membership (number of units, which is leader) via a
"get-cluster-info" action.

**Why this priority**: Scaling is a core Juju operation for K8s
deployments and validates stateful set behavior, peer coordination,
and leader failover under dynamic conditions.

**Independent Test**: Deploy with 1 unit, scale to 3, verify all units
report consistent cluster info, scale down to 1, verify clean departure.

**Acceptance Scenarios**:

1. **Given** a single-unit deployment, **When** scaled to 3 units via `juju scale-application`, **Then** two new units are created with their own lifecycle event sequences.
2. **Given** a 3-unit deployment, **When** queried, **Then** `self.app.planned_units()` returns 3 on all units.
3. **Given** a 3-unit deployment, **When** scaled down to 1, **Then** departing units fire `stop` and `remove`, and remaining units observe `relation-departed` for each removed peer.
4. **Given** a 3-unit deployment, **When** the leader unit is removed during scale-down, **Then** a new leader is elected from the remaining units.
5. **Given** a scaled deployment, **When** a new unit joins, **Then** it can read all existing peer app-level data immediately after `relation-changed`.

---

### User Story 9 - Juju Secrets (Priority: P9)

A CI engineer exercises the full Juju secrets lifecycle: create
application and unit secrets, grant/revoke access via relations, update
content (creating new revisions), and handle rotation and expiry events.
The charm stores a generated password as an app secret on leader
election and shares the secret ID via peer relation data.

**Why this priority**: Secrets are the recommended mechanism for managing
sensitive data in Juju 3.x. Testing the full lifecycle ensures
credential management works end-to-end.

**Independent Test**: Deploy the charm, run a "get-secret-info" action
to verify the auto-generated secret exists, trigger rotation via short
rotation policy, verify the secret content changes.

**Acceptance Scenarios**:

1. **Given** a leader unit, **When** the charm creates an app-owned secret, **Then** the secret is stored in Juju and its ID is shared via peer relation data.
2. **Given** a non-leader unit, **When** it reads the secret ID from peer data, **Then** it can retrieve the secret content via `model.get_secret(id=...)`.
3. **Given** a secret with rotation policy, **When** the rotation interval elapses, **Then** `secret-rotate` fires and the charm creates a new revision with fresh content.
4. **Given** a secret with an expiry, **When** the expiry time is reached, **Then** `secret-expired` fires and the charm handles cleanup.
5. **Given** an active relation, **When** the secret owner grants access, **Then** the remote charm can read the secret content.
6. **Given** a granted secret, **When** access is revoked, **Then** the remote charm can no longer read the secret.
7. **Given** a secret with multiple revisions, **When** all consumers refresh to the latest, **Then** `secret-remove` fires for obsolete revisions and the charm removes them.
8. **Given** multiple user-created secrets, **When** they are granted and consumed in parallel, **Then** the charm correctly tracks all secret IDs and can retrieve each secret's content independently.

---

### User Story 10 - Storage (Priority: P10)

A CI engineer deploys the charm with persistent filesystem storage and
verifies that data survives across unit restarts. The charm writes
a marker file to storage on startup and reads it back to confirm
persistence. A "check-storage" action reports storage status, mount
point, and data integrity.

**Why this priority**: Storage validates the StatefulSet behavior of K8s
charms and ensures data persistence across pod rescheduling.

**Independent Test**: Deploy with storage, write data via action, restart
the unit (or reschedule the pod), verify data persists via action.

**Acceptance Scenarios**:

1. **Given** a charm declaring filesystem storage, **When** deployed, **Then** `storage-attached` fires and the storage mount point is accessible.
2. **Given** attached storage, **When** the charm writes data to the mount point, **Then** the data persists across charm hook invocations.
3. **Given** a unit with attached storage, **When** the unit is removed, **Then** `storage-detaching` fires before `stop`.
4. **Given** a previously detached storage volume, **When** re-attached to a new unit via `juju attach-storage`, **Then** the data written by the original unit is still present. *(Integration test: `xfail(strict=False)` — K8s container model storage CLI not yet supported in Juju.)*
5. **Given** a deployed charm with storage, **When** the pod is rescheduled, **Then** the PersistentVolume is re-mounted and data is intact.
6. **Given** an existing PersistentVolume, **When** `juju import-filesystem` is used to import it as charm storage, **Then** the charm receives `storage-attached` and can read the volume's existing data. *(Integration test: `xfail(strict=False)` — K8s container model storage CLI not yet supported in Juju.)*
7. **Given** a built charm with storage, **When** deployed with `juju deploy --attach-storage <name>/<index>`, **Then** the pre-existing storage is bound to the new unit on first deploy rather than provisioning a new volume. *(Integration test: `xfail(strict=False)` — K8s container model storage CLI not yet supported in Juju.)*

---

### User Story 11 - Pebble Health Checks (Priority: P11)

A CI engineer configures Pebble health checks (HTTP, TCP, exec) and
verifies that check-failed and check-recovered events fire correctly.
The charm's workload exposes a controllable health endpoint that can
be toggled healthy/unhealthy via a "toggle-health" action, allowing
CI to test the full check lifecycle.

**Why this priority**: Health checks map to Kubernetes liveness and
readiness probes. Correct check behavior ensures proper pod lifecycle
management.

**Independent Test**: Deploy the charm, verify health checks are UP,
toggle health to unhealthy via action, wait for check-failed event,
toggle back, wait for check-recovered event.

**Acceptance Scenarios**:

1. **Given** a running workload with an HTTP health check configured at level "ready", **When** the health endpoint returns 200, **Then** the check status is UP and the pod is marked ready.
2. **Given** a healthy workload, **When** the health endpoint is toggled to return 500, **Then** after the check threshold is exceeded, `pebble-check-failed` fires.
3. **Given** a failed health check, **When** the health endpoint is restored to 200, **Then** `pebble-check-recovered` fires.
4. **Given** a TCP health check on the workload port, **When** the service is running, **Then** the check reports UP.
5. **Given** an exec health check running a test command, **When** the command returns exit code 0, **Then** the check reports UP; when it returns non-zero, the check fails.

---

### User Story 12 - Pebble File Operations & Exec (Priority: P12)

A CI engineer exercises all Pebble file and command execution operations.
The charm pushes config files to the workload container, pulls them back
to verify contents, creates directories, lists files, and executes
commands inside the container. A "test-pebble-ops" action runs the full
suite and reports results.

**Why this priority**: File operations and exec are how charms configure
workloads and run administrative commands. They are used extensively in
real-world charms for config rendering and migrations.

**Independent Test**: Deploy the charm, run the test-pebble-ops action,
verify all operations succeed with expected results.

**Acceptance Scenarios**:

1. **Given** a connected container, **When** a file is pushed with `container.push()`, **Then** `container.pull()` returns identical content.
2. **Given** a connected container, **When** `container.make_dir()` is called with `make_parents=True`, **Then** nested directories are created.
3. **Given** a connected container, **When** `container.list_files()` is called on a directory, **Then** it returns the expected entries.
4. **Given** a connected container, **When** `container.exec()` runs a command, **Then** stdout and stderr are captured correctly.
5. **Given** a connected container, **When** `container.exec()` runs a failing command, **Then** `ExecError` is raised with the correct return code.
6. **Given** a connected container, **When** `container.remove_path()` is called, **Then** the file or directory is deleted.
7. **Given** a connected container, **When** a file is pushed with specific permissions, **Then** the file has the expected ownership and mode.
8. **Given** a running service, **When** `container.stop("norma")` is called, **Then** the service stops and `container.get_services()` shows it as inactive.
9. **Given** a stopped service, **When** `container.start("norma")` is called, **Then** the service starts and `container.get_services()` shows it as active.
10. **Given** a running service, **When** `container.restart("norma")` is called, **Then** the service restarts (PID changes) and remains active.
11. **Given** a connected container, **When** `container.get_plan()` is called, **Then** it returns the full Pebble plan matching the applied layer.
12. **Given** a running service, **When** `container.send_signal()` sends SIGHUP to the service, **Then** the service receives the signal without restarting (verified by PID remaining unchanged).

---

### User Story 13 - Pebble Custom Notices (Priority: P13)

A CI engineer verifies that the workload can signal the charm via Pebble
custom notices. The workload process (or an exec command) sends a notice
with key and data, and the charm observes the `pebble-custom-notice`
event and logs the received data. A "trigger-notice" action sends a
notice from within the workload container.

**Why this priority**: Custom notices enable asynchronous workload-to-charm
communication, which is essential for event-driven charm architectures.

**Independent Test**: Deploy the charm, run the trigger-notice action,
verify the charm's event log records the custom notice with correct key
and data.

**Acceptance Scenarios**:

1. **Given** a running workload, **When** a custom notice is sent via `pebble notify` inside the container, **Then** the charm's `pebble-custom-notice` handler fires.
2. **Given** a custom notice with a specific key, **When** the handler fires, **Then** `event.notice.key` matches the sent key.
3. **Given** a custom notice with data payload, **When** the handler fires, **Then** `event.notice.last_data` contains the sent key-value pairs.

---

### User Story 14 - Networking & Ports (Priority: P14)

A CI engineer verifies that the charm can open and close ports, that
network binding information is accessible, and that `juju expose`/`unexpose`
controls external access. The charm opens its workload port on startup,
and a "test-networking" action reports open ports, binding addresses, and
exposed status.

**Why this priority**: Port management and network bindings are how
charms declare their connectivity requirements to the Juju model.

**Independent Test**: Deploy the charm, verify the workload port is
opened, run the test-networking action, verify port and binding info.

**Acceptance Scenarios**:

1. **Given** a deployed charm, **When** it calls `self.unit.open_port("tcp", port)`, **Then** the port appears in the unit's opened ports list.
2. **Given** an open port, **When** `self.unit.close_port("tcp", port)` is called, **Then** the port is removed from the opened ports list.
3. **Given** a deployed charm, **When** `self.model.get_binding(endpoint).network` is queried, **Then** it returns valid ingress and bind addresses.
4. **Given** a deployed charm, **When** `self.unit.set_ports()` is called with a specific set, **Then** only those ports are open; all others are closed.
5. **Given** a deployed charm with open ports, **When** `juju expose juju-norma-k8s` is executed, **Then** the application is exposed and the workload port becomes accessible outside the Juju model (K8s creates a LoadBalancer or NodePort service).
6. **Given** an exposed application, **When** `juju unexpose juju-norma-k8s` is executed, **Then** external access is revoked and only model-internal traffic reaches the workload port.
7. **Given** a deployed charm, **When** `juju expose juju-norma-k8s` is called and then the test-networking action is run, **Then** the action reports the exposed status.

---

### User Story 15 - Upgrade/Refresh (Priority: P15)

A CI engineer upgrades the calibration charm to a new revision and
verifies that the `upgrade-charm` event fires, the charm reconciles
state between versions, and `config-changed` fires after the upgrade.
The charm tracks its version and reports it via a "get-version" action
and the workload version in `juju status`.

**Why this priority**: Upgrade is a critical operational workflow. Charms
must handle transitions between versions without data loss or downtime.

**Independent Test**: Deploy the charm, build a new revision with a
different version string, `juju refresh` to the new revision, verify
upgrade-charm and config-changed fire, verify the new version is reported.

**Acceptance Scenarios**:

1. **Given** a running charm, **When** `juju refresh` is executed with a new charm revision, **Then** `upgrade-charm` fires before `config-changed`.
2. **Given** an upgrade in progress, **When** `upgrade-charm` fires, **Then** the charm reconciles its workload to the new version.
3. **Given** a completed upgrade, **When** `juju status` is queried, **Then** the application version reflects the new charm version.
4. **Given** a completed upgrade, **When** the get-version action is run, **Then** the charm-version and workload-version both reflect the new revision.

---

### User Story 16 - Multiple Containers (Priority: P16)

A CI engineer deploys the calibration charm with two workload containers
and verifies that each gets independent `pebble-ready` events, can run
separate services, and can have their own Pebble layers and health checks.

**Why this priority**: Multi-container charms are common for architectures
where the workload consists of multiple processes (e.g., app + sidecar).

**Independent Test**: Deploy the charm, verify both containers reach
running state, verify each has its own independent service and health
check.

**Acceptance Scenarios**:

1. **Given** a charm with two containers defined (both using the same ROCK image, each running the Go binary on a different port), **When** deployed, **Then** each container fires its own `pebble-ready` event independently.
2. **Given** two running containers, **When** each has a different Pebble layer (different port, service name, and environment), **Then** each container runs its own service independently.
3. **Given** two running containers, **When** one container's pod is restarted, **Then** only that container's `pebble-ready` fires again.
4. **Given** two containers, **When** a file is pushed to container A, **Then** it is NOT visible in container B (filesystem isolation).

---

### User Story 17 - Non-Root Security & Trust (Priority: P17)

A CI engineer verifies that the charm runs as non-root (`charm-user:
non-root`) and that workload containers run with non-root uid/gid. The
charm and workload should function correctly without root privileges.
Additionally, the engineer verifies that Juju trust (cloud credential
access) works by deploying with `--trust` and confirming the charm can
read cloud credentials. A "check-security" action reports process
UID/GID, trust status, and cloud credential availability.

**Why this priority**: Non-root execution is a security requirement for
production deployments and validates Juju's rootless charm support.
Trust is required by charms that interact with the K8s API directly.

**Independent Test**: Deploy the charm with `--trust`, run the
check-security action, verify non-root UID/GID and cloud credential
availability.

**Acceptance Scenarios**:

1. **Given** `charm-user: non-root` in charmcraft.yaml, **When** the charm is deployed, **Then** the charm process runs as a non-root user (UID 170).
2. **Given** a container configured with non-root uid/gid (584792 for `_daemon_`), **When** the workload starts, **Then** the Pebble process and service run as a non-root user.
3. **Given** a non-root charm, **When** all standard operations are performed (config, relations, actions, status), **Then** they succeed without permission errors.
4. **Given** the charm is deployed with `juju deploy --trust`, **When** the check-security action queries cloud credentials, **Then** the cloud type, endpoint, and credential attributes are accessible.
5. **Given** the charm is deployed without `--trust`, **When** `juju trust <app>` is executed post-deploy, **Then** `config-changed` fires and cloud credentials become available.
6. **Given** a CI variant of the charm built with `charm-user: sudoer`, **When** deployed, **Then** the charm process runs as UID 171 with sudo privileges, and all standard operations succeed. *(Note: `sudoer` is a build-time variant tested via CI matrix, not a runtime toggle. The primary charm uses `non-root`.)*

---

### User Story 18 - COS Observability Integration (Priority: P18)

A CI engineer integrates the calibration charm with the Canonical
Observability Stack (Prometheus, Grafana, Loki) and verifies that
metrics are scraped, dashboards are provided, and logs are forwarded.
The charm exposes a metrics endpoint, ships a Grafana dashboard template,
and configures log forwarding via Pebble.

**Why this priority**: Observability is mandatory for production charms
and validates the charm library integrations for the COS ecosystem.

**Independent Test**: Deploy the charm with COS charms, verify Prometheus
scrapes metrics, Grafana receives the dashboard, and Loki receives logs.

**Acceptance Scenarios**:

1. **Given** a `prometheus_scrape` relation, **When** integrated with Prometheus, **Then** metrics are scraped from the charm's metrics endpoint.
2. **Given** a `grafana_dashboard` relation, **When** integrated with Grafana, **Then** the shipped JSON dashboard appears in Grafana.
3. **Given** a `loki_push_api` relation, **When** integrated with Loki, **Then** the `LogForwarder` library configures Pebble native log forwarding and workload logs are visible in Loki.
4. **Given** shipped Prometheus alert rules, **When** the relation is active, **Then** alert rules are loaded into Prometheus.

---

### User Story 19 - Cross-Model Relations (Priority: P19)

A CI engineer tests cross-model relations (CMR) by deploying the
calibration charm in two different Juju models and integrating them
across models. The charm's provides/requires endpoints work identically
whether the relation is same-model or cross-model.

**Why this priority**: CMR is a key Juju capability for distributed
architectures where services span multiple models or clouds.

**Independent Test**: Deploy the charm in model A and model B, create
an offer in model A, consume it in model B, integrate, verify data
exchange works across models.

**Acceptance Scenarios**:

1. **Given** a charm in model A, **When** its provides endpoint is offered via `juju offer`, **Then** the offer is visible and consumable from other models.
2. **Given** an offer from model A, **When** a charm in model B consumes and integrates with it, **Then** relation events fire on both sides identically to same-model relations.
3. **Given** an active CMR, **When** the provider sets data, **Then** the consumer in the other model receives `relation-changed` and reads the data.
4. **Given** an active CMR, **When** the offer is removed, **Then** `relation-broken` fires on the consumer side.

---

### User Story 20 - Event Deferral (Priority: P20)

A CI engineer verifies that the charm correctly handles event deferral:
saving an event for later re-emission, verifying it fires before the
next scheduled event, and confirming that non-deferrable events (actions,
secret-rotate, secret-expired, update-status) raise errors or are
silently ignored when deferred. A "test-defer" action triggers a
condition that causes the next eligible event to be deferred, and the
event ledger records both the deferral and the re-emission.

**Why this priority**: Event deferral is a core Juju mechanism that is
frequently misused in charm development. Testing its precise behavior
(ordering, re-fire timing, restrictions) validates Juju's event queue.

**Independent Test**: Deploy the charm, run the test-defer action to
arm deferral, trigger a config-changed event, verify the event ledger
shows the event was deferred and then re-emitted on the next hook.

**Acceptance Scenarios**:

1. **Given** a charm with deferral armed, **When** a `config-changed` event fires, **Then** the event is deferred and the event ledger records "deferred:config-changed".
2. **Given** a deferred event, **When** the next event arrives (e.g., `update-status`), **Then** the deferred event re-fires before the new event and the ledger records "re-emitted:config-changed" followed by "update-status".
3. **Given** a running charm, **When** an action handler attempts to call `event.defer()`, **Then** a RuntimeError is raised.
4. **Given** a running charm, **When** `secret-rotate` or `secret-expired` fires and deferral is attempted, **Then** the framework prevents deferral.
5. **Given** an event that is deferred twice, **When** it re-fires, **Then** the ordering relative to other deferred events may change (validating that double-deferral breaks ordering guarantees).

---

### User Story 21 - OCI Resource Lifecycle (Priority: P21)

A CI engineer verifies that the charm handles OCI resource attachment and
runtime image refresh correctly. When `juju attach-resource` updates the
container image, the container restarts, `pebble-ready` fires, and the
charm re-applies its Pebble layer and recovers to active status. This is
distinct from `juju refresh` (US15), which updates the charm code — OCI
resource refresh only updates the workload image.

**Why this priority**: OCI resource lifecycle is a K8s-specific Juju
feature exercised by the `container-resource` test charm in Juju CI. It
validates that the sidecar pattern handles image swaps gracefully.

**Independent Test**: Deploy the charm, verify active, run
`juju attach-resource norma-k8s juju-norma-image=<new-image>`, verify
pebble-ready fires again and charm recovers to active with potentially
new workload version.

**Acceptance Scenarios**:

1. **Given** a deployed charm, **When** the initial OCI resource is attached, **Then** the container starts and `pebble-ready` fires.
2. **Given** a running charm, **When** `juju attach-resource` updates the OCI image, **Then** the container restarts, `pebble-ready` fires again, and the charm re-applies its Pebble layer.
3. **Given** a resource refresh, **When** the charm reconciles, **Then** the workload version may change and is reported correctly via `get-version` action.
4. **Given** a resource refresh, **When** the event ledger is queried, **Then** it shows a new `pebble-ready` event after the resource attachment.

---

### User Story 22 - Charm Introspection (Priority: P22)

A CI pipeline or developer runs a single action on the charm unit that
returns a comprehensive report of all internal charm state — event history,
configuration, relations, storage, containers, leadership, secrets metadata,
version, unit identity, and goal-state — so that charm internals can be verified
independently of what Juju reports. An optional section filter limits the
report to specific sections for targeted CI assertions.

**Why this priority**: Individual per-topic actions already exist in the
charm. This feature's value is the single-call aggregation that CI can
parse programmatically, reducing multiple action calls to one.

**Independent Test**: Deploy the charm, perform some operations (config
change, relate, store data), then run the introspection action and verify
the returned report contains all expected sections with accurate data.

**Acceptance Scenarios**:

1. **Given** a deployed unit in active state, **When** the operator runs the introspect action, **Then** the action returns a structured report containing sections for: event ledger, configuration, relations, storage, containers, leadership, secrets (metadata only), version, identity, and goal-state.
2. **Given** a deployed unit with active peer relations and custom configuration, **When** the operator runs the introspect action, **Then** the relations section lists all active relations with their interface, endpoint, and relation data, and the configuration section shows all current config values including any changed from defaults.
3. **Given** a deployed unit where the workload container is not yet ready, **When** the operator runs the introspect action, **Then** the report still returns successfully with available sections populated and container/workload sections indicating the unavailable state rather than failing.
4. **Given** a deployed unit, **When** the operator runs the introspect action with a section filter specifying "relations,config", **Then** the report contains only the relations and config sections.
5. **Given** a deployed unit, **When** the operator runs the introspect action with no filter, **Then** all sections are included.
6. **Given** a deployed unit, **When** the operator runs the introspect action with an unrecognised section name, **Then** that section name is silently ignored and the report contains only valid matching sections.
7. **Given** a deployed unit, **When** the introspect action includes the `goal-state` section, **Then** the report contains the output of `self.model._backend._run_tool("goal-state")` showing the planned state of the model (units and their status, relations and their status).

---

### User Story 23 - Multi-Architecture OCI Image (Priority: P23)

A Juju CI engineer deploys the calibration charm on arm64 K8s nodes (or
mixed-arch clusters) and verifies that the workload container starts and
serves health endpoints identically to amd64. The ROCK image is built
for multiple architectures so that CI can validate deployment across the
hardware targets Juju supports in production.

**Why this priority**: Juju CI tests arm64 and s390x deployment paths
(previously covered by `sidecar-sudoer`). Without multi-arch images,
norma-k8s cannot replace those test charms. Go cross-compiles trivially
and the ROCK bare base supports all three architectures.

**Independent Test**: Build the ROCK image with `rockcraft pack` on
amd64, push both amd64 and arm64 manifests to the registry, deploy on
an arm64 node, and verify the workload health endpoint responds.

**Acceptance Scenarios**:

1. **Given** the rockcraft.yaml and charmcraft.yaml declare amd64 and arm64 platforms, **When** the ROCK is built, **Then** both architecture images are produced and can be pushed to a container registry as a multi-arch manifest.
2. **Given** a multi-arch OCI image in the registry, **When** the charm is deployed on an arm64 K8s node, **Then** the workload container starts, passes health checks, and the charm reaches active status.
3. **Given** a multi-arch OCI image, **When** the charm is deployed on amd64, **Then** the deployment behaves identically to the single-arch build — no regression.

---

### User Story 24 - Multiple Storage Definitions (Priority: P24)

A Juju CI engineer tests independent storage attachment and detachment
by exercising two named storage volumes: the existing `data` storage
and a new optional `logs` storage. This enables CI to verify scenarios
where one storage is attached while the other is not, or where storages
are detached independently — previously tested by multi-storage charms
like the PostgreSQL test charm.

**Why this priority**: Juju CI storage tests exercise per-name
attachment, detachment, and import. A single storage definition cannot
test these paths. Adding a second optional storage closes this gap.

**Independent Test**: Deploy the charm, verify only `data` storage is
attached by default, attach `logs` storage, verify both appear in
check-storage output, then detach `logs` and verify `data` persists.

**Acceptance Scenarios**:

1. **Given** the charm declares `data` (required) and `logs` (optional) filesystem storages, **When** deployed without explicit storage requests, **Then** only `data` is provisioned and the charm reaches active status.
2. **Given** a running charm, **When** `logs` storage is attached via `juju add-storage`, **Then** the charm records `storage-attached` in the event ledger and the `check-storage` action with `name=logs` reports the storage as available.
3. **Given** both storages attached, **When** `logs` storage is detached, **Then** `storage-detaching` fires, `data` storage remains intact, and `check-storage` with `name=data` still passes.
4. **Given** a running charm, **When** the `check-storage` action is run with `name=logs` and logs storage is not attached, **Then** the action reports the storage as unavailable rather than failing.
5. **Given** both storages attached, **When** the `introspect` action is run, **Then** the storage section lists both `data` and `logs` with their respective mount paths and status.

---

### User Story 25 - Subordinate Charm Integration (Priority: P25)

A Juju CI engineer deploys a subordinate charm alongside the calibration
charm to verify subordinate relation mechanics: automatic unit cohabitation,
`scope: container` relations, shared Pebble access, and subordinate lifecycle
events. This exercises Juju's subordinate deployment model which is used
extensively by observability agents (grafana-agent, landscape-client) and
security charms in production.

The test subordinate is the same juju-norma-k8s charm repacked with a
charmcraft overlay (`charmcraft-subordinate.yaml`) that sets `subordinate: true`
and changes the `juju-info` endpoint from provides to requires with
`scope: container`. This reuses the existing charm code — same binary, same
Pebble layers, different packaging. CI packs both variants (principal +
subordinate) from the same source tree.

**Why this priority**: Juju CI tests subordinate attachment, removal, and
lifecycle event ordering. The calibration charm currently has no subordinate
endpoint, so these code paths are untested. Adding a `juju-info` provides
endpoint enables any subordinate to attach, and the overlay-based subordinate
variant validates the full lifecycle without maintaining a separate codebase.

**Independent Test**: Deploy the principal charm, deploy the subordinate
variant (packed from the same source with the overlay), integrate them, verify
the subordinate unit appears colocated, run an action on the principal to
confirm the subordinate relation data is visible, then remove the relation and
verify cleanup.

**Acceptance Scenarios**:

1. **Given** the charm declares a `juju-info` provides endpoint, **When** a subordinate charm (which declares `juju-info` requires with `scope: container`) is integrated, **Then** one subordinate unit is automatically created per principal unit and they share the same pod.
2. **Given** a subordinate is integrated, **When** the principal is scaled to 3 units, **Then** 3 subordinate units are automatically created (1:1 mapping).
3. **Given** a subordinate is integrated, **When** the `introspect` action is run with `sections=relations`, **Then** the subordinate relation appears in the relations output with the subordinate's unit data visible.
4. **Given** a subordinate is integrated, **When** the relation is removed, **Then** `relation-broken` fires on the principal, the subordinate units are removed, and the principal returns to active status.
5. **Given** the charm is deployed without any subordinate integration, **When** status is checked, **Then** the charm reaches active status — the subordinate endpoint is optional.

---

### Edge Cases

- What happens when `pebble-ready` fires but the container loses connectivity before the layer is applied? *(Covered by US2: `_reconcile()` wraps Pebble ops in `try/except ConnectionError`; next pebble-ready retries.)*
- What happens when the leader unit is removed while it is in the middle of writing to the peer relation app data bag? *(Covered by US6/US8: Juju ensures atomic writes; new leader re-populates app data on `leader-elected`.)*
- What happens when two config-changed events fire in rapid succession with different values? *(Covered by US3: Holistic reconciler reads current config on each invocation; intermediate values are irrelevant.)*
- What happens when a secret rotation event fires but the leader unit is not available? *(Covered by US9: `secret-rotate` fires only on the secret owner (leader); if leader is down, Juju queues the event.)*
- What happens when storage is detached while the workload is writing to it? *(Covered by US10: `storage-detaching` fires before removal; concurrent writes may get ENOENT, handled by `try/except PathError`.)*
- What happens when a relation-broken event fires for a relation that was never fully established (no relation-changed received)? *(Covered by US7: `_reconcile()` checks current relation state, not event history; relation data may be empty but handler is idempotent.)*
- What happens when an upgrade-charm event fires while the workload is unhealthy? *(Covered by US15/US11: Reconciler re-applies Pebble layer regardless of health state; health checks recover independently.)*
- What happens when scale-down removes more units than the cluster can tolerate? *(Covered by US8: `planned_units()` returns target count; remaining units update peer data; no minimum quorum enforced.)*
- What happens when `juju remove-application --force` is issued while hooks are running? *(Covered by US1 AC4: Juju forcefully terminates the unit; model returns to clean state regardless of hook status.)*
- What happens when `container.send_signal()` targets a service that has already exited? *(Covered by US12 AC12: Pebble returns an error; the action catches the exception and reports failure.)*
- What happens when `juju import-filesystem` references a PV that is still bound to another unit? *(Covered by US10 AC6: Juju rejects the import; the PV must be unbound first.)*
- What happens when `juju expose` is called on a charm that has no open ports? *(Covered by US14 AC5-6: Juju creates the K8s service but no endpoints are reachable until the charm opens ports.)*
- What happens during model migration if the target controller has a different Juju version? *(Covered by FR-034: Migration tests verify state preservation; version compatibility is Juju's responsibility.)*
- What happens when `juju ssh` targets a unit whose pod is being rescheduled? *(Covered by FR-037: The SSH connection fails; integration test retries after the pod stabilizes.)*

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The charm MUST log every observed event (name, timestamp, unit) to an ephemeral event ledger persisted to the charm container filesystem (resets on pod restart) and queryable via action.
- **FR-002**: The charm MUST manage a workload process via Pebble with a purpose-built Go binary that exposes `/health`, `/version`, `/ready`, `/metrics`, and `/toggle-health` HTTP endpoints inside a chiselled ROCK container.
- **FR-003**: The charm MUST declare config options of every supported type: string, int, float, boolean, and secret.
- **FR-004**: The charm MUST validate configuration and enter BlockedStatus with a descriptive message for invalid values.
- **FR-005**: The charm MUST use `collect_unit_status` and `collect_app_status` for all status reporting.
- **FR-006**: The charm MUST define actions for: querying event logs, querying config, querying peer data, querying relation data, querying cluster info, querying secret info, querying storage status, testing Pebble operations, triggering notices, toggling health, testing networking, checking security, getting version, and forcing status.
- **FR-007**: The charm MUST declare peer, provides, and requires relation endpoints with a self-relatable interface. All relation endpoints MUST be optional; the charm MUST reach ActiveStatus without any integrations.
- **FR-008**: The charm MUST create an app-owned Juju secret on leader election and share the secret ID via peer relation data.
- **FR-009**: The charm MUST declare filesystem storage and persist a data marker to verify survival across restarts.
- **FR-010**: The charm MUST configure Pebble health checks (HTTP, TCP, and exec) mapped to K8s liveness and readiness probes.
- **FR-011**: The charm MUST exercise Pebble file operations (push, pull, list, make_dir, remove_path, exists) and command execution.
- **FR-012**: The charm MUST handle Pebble custom notices with key and data payload.
- **FR-013**: The charm MUST open its workload port on startup and support closing it via action.
- **FR-014**: The charm MUST handle `upgrade-charm` events and report its version via both action and `juju status`.
- **FR-015**: The charm MUST define two workload containers (both using the same ROCK image, each running the Go binary on a different port) to validate independent Pebble lifecycle.
- **FR-016**: The charm MUST run as `charm-user: non-root` with non-root container uid/gid. The charm MUST support `juju trust` and report cloud credential availability via action.
- **FR-017**: The charm MUST provide prometheus_scrape, grafana_dashboard, and loki_push_api relation endpoints.
- **FR-018**: The charm MUST support cross-model relations via its provides and requires endpoints.
- **FR-019**: The workload logic MUST reside in a separate module with zero dependency on the ops framework.
- **FR-020**: The charm MUST handle secret rotation and expiry events by creating new secret revisions and removing obsolete ones.
- **FR-021**: The charm MUST support arming event deferral via action, recording deferrals and re-emissions in the event ledger, and validating that non-deferrable events cannot be deferred.
- **FR-022**: The charm MUST handle OCI resource refresh by re-applying Pebble layers and recovering to active status when `juju attach-resource` updates the container image.
- **FR-023**: The charm MUST exercise Pebble service control operations (stop, start, restart) and plan introspection (get_plan, get_services) in addition to file and exec operations.
- **FR-024**: The charm MUST provide a single `introspect` action that returns a comprehensive structured report of all internal charm state (event ledger, config, relations, storage, containers, leadership, secrets metadata, version, identity, goal-state) with optional section filtering. The action MUST succeed even when subsystems are unavailable, and MUST NOT include actual secret content.
- **FR-025**: The OCI image MUST be built for at least amd64 and arm64 architectures. The charmcraft.yaml MUST declare both platforms so that the charm can be deployed on either architecture.
- **FR-026**: The charm MUST declare at least two named filesystem storages: `data` (required, mounted at `/var/lib/norma`) and `logs` (optional, mounted at `/var/log/norma`). The `check-storage` action MUST accept a `name` parameter to query any declared storage independently.
- **FR-027**: The charm MUST declare a `juju-info` provides endpoint to allow subordinate charms to attach. The endpoint MUST be optional — the charm MUST reach ActiveStatus without any subordinate integrated.
- **FR-028**: The test-pebble-ops action MUST exercise `container.send_signal()` to send SIGHUP to a running service and verify the signal is received without restarting the process.
- **FR-029**: Integration tests MUST verify forced application removal (`juju remove-application --force`) completes cleanly and the model returns to an empty state.
- **FR-030**: Integration tests MUST verify storage import (`juju import-filesystem`) and attach-on-deploy (`juju deploy --attach-storage`) so that pre-existing PersistentVolumes can be reused by new units.
- **FR-031**: CI MUST test both `charm-user: non-root` (primary) and `charm-user: sudoer` (variant) execution modes via build matrix to validate all Juju privilege levels for K8s charms.
- **FR-032**: Integration tests MUST verify parallel secret operations — multiple user-created secrets granted and consumed concurrently — to ensure the charm correctly tracks independent secret IDs.
- **FR-033**: The charm MUST support `juju expose` and `juju unexpose` operations. The test-networking action MUST report the exposed status. Integration tests MUST verify that exposing the application makes the workload port externally accessible and unexposing revokes access.
- **FR-034**: Integration tests MUST verify model migration (`juju migrate`) by deploying the charm with state (config, secrets, storage data, relations), migrating the model to a second controller, and confirming all state is preserved and the charm reaches active status on the target controller.
- **FR-035**: The introspect action MUST include a `goal-state` section that reports the planned state of the model as returned by the `goal-state` hook tool, showing units and their status and relations and their status.
- **FR-036**: Integration tests MUST verify `juju model-config update-status-hook-interval` by setting a short interval and confirming the charm's event ledger records `update-status` events at the expected frequency.
- **FR-037**: Integration tests MUST verify `juju ssh juju-norma-k8s/0` connectivity into the K8s pod and `juju deploy` with `--constraints` (e.g., `mem=512M cores=1`) to confirm Juju correctly sets K8s resource requests/limits on the charm pod.
- **FR-038**: The ROCK image MUST include a minimal POSIX shell (`/bin/sh` via busybox) to support `juju exec` and `juju ssh` operations that require shell interpretation inside the workload container. This enables the charm to replace alertmanager-k8s and snappass-test in the secrets_k8s suite where `juju exec --unit ... secret-add` is used.
- **FR-039**: The `check-security` action MUST exercise the `credential-get` hook tool to retrieve K8s cloud credentials, hits the K8s API using those credentials, and reports the result. This enables replacement of juju-qa-credential-get-k8s in the sidecar suite. The action MUST require `--trust` at deploy time and fail gracefully without it.
- **FR-040**: The sudoer build variant MUST be packaged as a charmcraft overlay (`charmcraft-sudoer.yaml`) following the same pattern as the subordinate overlay (`charmcraft-subordinate.yaml`), producing a third `.charm` artifact from the same source tree. CI packs all three variants (principal, subordinate, sudoer) in the pack step.

### Non-Functional Requirements

- **NFR-001**: Integration tests MUST be self-contained -- running `SETUP_ENVIRONMENT=1 make integration` on a fresh Ubuntu 24.04 machine MUST install all prerequisites (microk8s, juju, controller bootstrap) and execute the full test suite without manual intervention.
- **NFR-002**: Integration tests MUST support testing against multiple Juju versions via the `JUJU_CHANNEL` environment variable (e.g., `3/stable`, `4/stable`).
- **NFR-003**: Integration test environment setup MUST be idempotent -- safe to re-run on an already-configured machine with no side effects.
- **NFR-004**: Integration tests MUST support reusing an existing deployment via `JUJU_MODEL` for fast local iteration, or creating a fresh temporary model for CI isolation.
- **NFR-005**: The charm MUST be self-sufficient as a single replacement for ALL Juju K8s sidecar test charms. Every Juju K8s charm API surface (lifecycle events, Pebble operations, relations, storage, secrets, actions, status, networking, expose/unexpose, security, observability, subordinates, cross-model relations, model migration, goal-state, model-config, SSH access, K8s constraints) MUST be exercisable through this one charm. No additional test charms should be needed for Juju K8s CI validation.

### Key Entities

- **Event Ledger**: An ordered log of all observed Juju events with timestamp, event name, and unit identity. Persisted to the charm container filesystem to survive across event dispatches; resets on pod restart (by design, since it tests event firing, not long-term persistence). Queryable via action.
- **Calibration Workload**: A purpose-built Go binary compiled as a single static executable, source code co-located in this repo under `workload/`. Runs inside a chiselled ROCK container built via `rockcraft.yaml`. Exposes `/health`, `/version`, `/ready`, `/metrics` (Prometheus format), and `/toggle-health` endpoints. Health state is toggled via the `/toggle-health` endpoint or a flag file. The binary requires no runtime dependencies.
- **Calibration Config**: The set of all config options (one per type) with validation rules and defaults.
- **Cluster State**: The charm's view of the deployment: unit count, leader identity, peer data, relation data, secret status, storage status.

### Assumptions

- The calibration charm is deployed on a Juju 3.6+ controller with a K8s cloud.
- The OCI image for the workload container is a chiselled ROCK containing a purpose-built Go binary (single static executable, no runtime dependencies), source in `workload/`, built via rockcraft as part of this repo's CI. Multi-arch builds (amd64 + arm64) require cross-compilation support in CI (Go's `GOARCH` env var).
- Cross-model relation testing requires access to two Juju models on the same controller.
- Model migration testing (FR-034) requires access to two Juju controllers. CI may skip this test if only one controller is available.
- COS integration testing requires the Prometheus, Grafana, and Loki charms to be available.
- The charm name is `juju-norma-k8s`.
- Integration test environment preparation is opt-in via `SETUP_ENVIRONMENT=1`. Without it, tests skip gracefully if prerequisites are missing.
- CI runs integration tests against both Juju 3.x (`3/stable`) and Juju 4.x (`4/stable`) channels via matrix strategy.

### Replacement Targets

This charm is designed to replace the following Juju CI test charms (see `k8s-charm-research.md` for full analysis):

| Charm Replaced | Suites | Enabling Capability |
|---------------|--------|-------------------|
| snappass-test | smoke_k8s, sidecar, secrets_k8s, ck | Deploy + HTTP health endpoint |
| juju-qa-pebble-notices | sidecar | `trigger-notice` action (US13) |
| juju-qa-pebble-checks | sidecar | `toggle-health` action (US11) |
| sidecar-non-root | sidecar | Non-root by default (US17) |
| juju-qa-credential-get-k8s | sidecar | `credential-get` action (FR-039) |
| sidecar-sudoer | sidecar | Sudoer overlay (FR-040) |
| juju-qa-container-resource | resources | OCI resource lifecycle (US21) |
| postgresql-k8s | storage_k8s | PV import/attach (FR-030) |

Suites that **must not** use norma-k8s: smoke_k8s_psql (real DB writes), deploy_caas (multi-app topology), controllercharm (controller metrics), coslite/kubeflow/ck (bundle deployments), dashboard (controller relation), caasadmission (no charm).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 25 user stories pass their acceptance scenarios when executed sequentially as a CI suite.
- **SC-002**: Each user story can be tested independently by deploying the charm and running specific actions without requiring all other stories to be implemented.
- **SC-003**: The charm reaches active status within 120 seconds of deployment on a standard MicroK8s cluster.
- **SC-004**: Scaling from 1 to 3 units completes with all units active within 180 seconds.
- **SC-005**: The charm's event ledger correctly records 100% of expected lifecycle events in the correct order.
- **SC-006**: All actions return results within 30 seconds of invocation.
- **SC-007**: The charm passes lint (ruff), unit tests (ops.testing), and integration tests (jubilant) in CI, across both Juju 3.x and 4.x versions.
- **SC-008**: The charm runs entirely as non-root (both charm process and workload) with no privilege escalation required.
