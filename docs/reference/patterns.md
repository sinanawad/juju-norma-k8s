# Patterns: Juju K8s Charm Development

Every pattern below is extracted from the working code in this repository. Each section is self-contained: the pattern, the code, and the charmcraft.yaml section needed.

---

## 1. Holistic Reconciler

**What**: All lifecycle events route to a single `_reconcile()` method that reads all inputs and writes all outputs. No event-specific branching in the reconciler.

**Why**: Idempotent by design. If the charm misses an event (pod restart, network blip), the next event triggers a full reconcile that converges to the correct state.

**charm.py pattern** (from `src/charm.py:52-92`):

```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        # Route ALL lifecycle events to the reconciler
        self.framework.observe(self.on.install, self._reconcile)
        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.leader_elected, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._reconcile)
        self.framework.observe(self.on.update_status, self._reconcile)
        self.framework.observe(self.on.norma_pebble_ready, self._reconcile)

        # Peer + regular relation events also go to reconciler
        self.framework.observe(self.on.my_peers_relation_joined, self._reconcile)
        self.framework.observe(self.on.my_peers_relation_changed, self._reconcile)

        # Dedicated handlers are ONLY for: stop, remove, actions, secret-rotate/expired
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on.remove, self._on_remove)

        # Status collection — NEVER set status in lifecycle handlers
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)

    def _reconcile(self, event):
        """Single entry point. Reads all inputs, computes desired state, writes outputs."""
        # 1. Read config
        port = int(self.config.get("port", 8080))

        # 2. Check container readiness
        container = self.unit.get_container("my-container")
        if not container.can_connect():
            return  # Status handler will set WaitingStatus

        # 3. Apply Pebble layer
        layer = my_workload.build_pebble_layer(port)
        container.add_layer("my-container", layer, combine=True)
        container.replan()

        # 4. Open ports
        self.unit.set_ports(ops.Port("tcp", port))

        # 5. Update relation data
        self._update_relation_data()
```

**What NOT to do**:
```python
# WRONG: Event-specific handling in the reconciler
def _reconcile(self, event):
    if isinstance(event, ops.ConfigChangedEvent):
        self._handle_config()  # Don't branch by event type
    elif isinstance(event, ops.PebbleReadyEvent):
        self._handle_pebble()  # The reconciler should converge regardless
```

---

## 2. Two-Module Separation

**What**: `src/charm.py` handles Juju lifecycle (imports ops). `src/workload.py` handles workload logic (zero ops dependency).

**Why**: The workload module is testable with plain pytest. No mocking of ops needed. Clean separation means workload changes don't touch lifecycle code.

**workload.py pattern** (from `src/norma.py`):

```python
"""Workload module — ZERO ops dependency."""

CONTAINER_NAME = "my-container"
DEFAULT_PORT = 8080
BINARY_PATH = "/bin/my-binary"

def validate_config(config: dict) -> tuple[bool, str]:
    """Validate config values. Returns (True, "") or (False, error_message)."""
    port = config.get("port", DEFAULT_PORT)
    if not (1 <= port <= 65535):
        return False, f"port must be 1-65535, got {port}"
    return True, ""

def build_pebble_layer(port: int, version: str) -> dict:
    """Build Pebble layer config. Returns a dict for container.add_layer()."""
    return {
        "summary": "my-workload layer",
        "services": {
            CONTAINER_NAME: {
                "override": "replace",
                "startup": "enabled",
                "command": BINARY_PATH,
                "environment": {"PORT": str(port), "VERSION": version},
            },
        },
        "checks": {
            "health": {
                "override": "replace",
                "level": "ready",
                "http": {"url": f"http://localhost:{port}/health"},
                "period": "10s",
                "threshold": 3,
            },
        },
    }
```

**charm.py calls workload.py with primitives only** (from `src/charm.py:286`):

```python
# CORRECT: Pass primitives, not ops objects
layer = workload.build_pebble_layer(port, version)
container.add_layer(workload.CONTAINER_NAME, layer, combine=True)

# WRONG: Never pass event or container to workload module
# layer = workload.build_pebble_layer(event, container)  # NO!
```

---

## 3. Status Reporting via collect_unit_status

**What**: Never set status in individual handlers. Use the `collect_unit_status` event exclusively.

**Why**: Multiple conditions can affect status simultaneously (Pebble not ready AND config invalid). The `collect_unit_status` pattern lets you add multiple statuses and ops resolves priority: Blocked > Maintenance > Waiting > Active.

**Pattern** (from `src/charm.py:376-394`):

```python
def _on_collect_unit_status(self, event: ops.CollectStatusEvent):
    # Check conditions in priority order
    container = self.unit.get_container("my-container")
    if not container.can_connect():
        event.add_status(ops.WaitingStatus("Waiting for Pebble"))
        return

    # Config validation
    config_valid, error = workload.validate_config(self._get_config())
    if not config_valid:
        event.add_status(ops.BlockedStatus(error))
        return

    # Everything OK — ActiveStatus with NO message
    event.add_status(ops.ActiveStatus())

def _on_collect_app_status(self, event: ops.CollectStatusEvent):
    if not self.unit.is_leader():
        return  # Only leader reports app status
    event.add_status(ops.ActiveStatus())
```

**Rules**:
- `ActiveStatus()` — always empty, no message
- `BlockedStatus("reason")` — user action required
- `WaitingStatus("reason")` — waiting for external condition
- `MaintenanceStatus("reason")` — charm is performing work
- Never use `ErrorStatus` for recoverable issues

---

## 4. Pebble Layer Management

**What**: Build Pebble layers in the workload module, apply them in the reconciler.

**charmcraft.yaml section**:

```yaml
containers:
  my-container:
    resource: my-image
    uid: 584792       # Non-root UID for _daemon_
    gid: 584792
    mounts:
      - storage: data
        location: /var/lib/myapp

resources:
  my-image:
    type: oci-image
    upstream-source: ghcr.io/myorg/myimage:latest
```

**Layer with health checks** (from `src/norma.py:82-129`):

```python
def build_pebble_layer(port: int) -> dict:
    return {
        "services": {
            "my-service": {
                "override": "replace",
                "startup": "enabled",
                "command": "/bin/myapp",
                "environment": {"PORT": str(port)},
            },
        },
        "checks": {
            "health": {
                "override": "replace",
                "level": "ready",         # Maps to Kubernetes readiness probe
                "http": {"url": f"http://localhost:{port}/health"},
                "period": "10s",
                "threshold": 3,           # 3 failures before unhealthy
            },
            "alive": {
                "override": "replace",
                "level": "alive",         # Maps to Kubernetes liveness probe
                "exec": {"command": "/bin/myapp --check"},
                "period": "30s",
            },
        },
    }
```

**Applying the layer** (from `src/charm.py:285-288`):

```python
container = self.unit.get_container("my-container")
if container.can_connect():
    layer = workload.build_pebble_layer(port)
    container.add_layer("my-container", layer, combine=True)
    container.replan()  # Restarts service if layer changed
```

**Pebble check events** (from `src/charm.py:98-100`):

```python
# Observe check failure/recovery in __init__
self.framework.observe(self.on.my_container_pebble_check_failed, self._reconcile)
self.framework.observe(self.on.my_container_pebble_check_recovered, self._reconcile)
```

---

## 5. Configuration with All Five Types

**charmcraft.yaml section**:

```yaml
config:
  options:
    my-string:
      type: string
      default: "hello"
      description: A string config option
    my-int:
      type: int
      default: 8080
      description: An integer config option
    my-float:
      type: float
      default: 1.0
      description: A float config option
    my-bool:
      type: boolean
      default: true
      description: A boolean config option
    my-secret:
      type: secret
      description: A secret URI (no default allowed)
```

**Reading config in the reconciler** (from `src/charm.py:255-280`):

```python
port = int(self.config.get("my-int", workload.DEFAULT_PORT))
name = self.config.get("my-string", "default")

# Secret config requires explicit resolution
secret_uri = self.config.get("my-secret")
if secret_uri:
    try:
        secret = self.model.get_secret(id=secret_uri)
        content = secret.get_content(refresh=True)
        # Use content["key"] ...
    except ops.SecretNotFoundError:
        # Handle missing secret — set BlockedStatus
        pass
```

**User workflow for secret config**:
```bash
juju add-secret my-secret password=hunter2
juju grant-secret my-secret my-charm
juju config my-charm my-secret=secret:<id>
```

---

## 6. Peer Relations (Inter-Unit Communication)

**What**: Peer relations are the primary mechanism for sharing data between units. Leader writes to app data, all units write to their own unit data.

**charmcraft.yaml section**:

```yaml
peers:
  my-peers:
    interface: my_app_peers
```

**Writing peer data** (from `src/charm.py:1115-1139`):

```python
def _update_relation_data(self):
    peer = self.model.get_relation("my-peers")
    if not peer:
        return

    # Any unit can write to its own unit data
    unit_data = {"unit-name": self.unit.name, "leader": str(self.unit.is_leader())}
    existing = peer.data[self.unit]
    # Check before writing to avoid relation-changed feedback loops
    if any(existing.get(k) != v for k, v in unit_data.items()):
        existing.update(unit_data)

    # Only the leader can write to app data
    if self.unit.is_leader():
        app_data = {"cluster-size": str(len(peer.units) + 1)}
        existing_app = peer.data[self.app]
        if any(existing_app.get(k) != v for k, v in app_data.items()):
            existing_app.update(app_data)
```

**Critical rule**: Always check if values changed before writing. Writing unchanged values triggers `relation-changed` events on all peers, creating feedback loops.

---

## 7. Provides/Requires Relations

**charmcraft.yaml section**:

```yaml
provides:
  my-provider:
    interface: my_interface
    optional: true
requires:
  my-requirer:
    interface: my_interface
    optional: true
    limit: 1
```

**Observing relation events** (from `src/charm.py:80-92`):

```python
for evt in (
    self.on.my_provider_relation_created,
    self.on.my_provider_relation_joined,
    self.on.my_provider_relation_changed,
    self.on.my_provider_relation_departed,
    self.on.my_provider_relation_broken,
):
    self.framework.observe(evt, self._reconcile)
```

**Writing relation data** (from `src/charm.py:1153-1161`):

```python
for endpoint in ("my-provider", "my-requirer"):
    for rel in self.model.relations.get(endpoint, []):
        cal_data = {"unit-name": self.unit.name, "role": endpoint.split("-")[-1]}
        existing = rel.data[self.unit]
        if any(existing.get(k) != v for k, v in cal_data.items()):
            existing.update(cal_data)
```

---

## 8. Secrets (Create, Rotate, Expire)

**What**: Juju secrets store sensitive data. The leader creates secrets and stores the ID in peer data — never the secret value.

**Creating a secret** (from `src/charm.py:1130-1136`):

```python
if self.unit.is_leader() and "secret-id" not in peer.data[self.app]:
    secret = self.app.add_secret(
        {"password": secrets.token_urlsafe(24)},
        label="my-password",
        rotate=ops.SecretRotate.MONTHLY,
    )
    peer.data[self.app]["secret-id"] = secret.id
```

**Granting access to related apps** (from `src/charm.py:1142-1151`):

```python
secret_id = peer.data[self.app].get("secret-id")
if secret_id:
    secret = self.model.get_secret(id=secret_id)
    for rel in self.model.relations.get("my-provider", []):
        secret.grant(rel)
```

**Handling rotation and expiration** (from `src/charm.py:357-370`):

```python
def _on_secret_rotate(self, event: ops.SecretRotateEvent):
    """Create a new revision with fresh content."""
    event.secret.set_content({"password": secrets.token_urlsafe(24)})

def _on_secret_expired(self, event: ops.SecretExpiredEvent):
    """Remove the expired revision."""
    event.secret.remove_revision(event.revision)

def _on_secret_remove(self, event: ops.SecretRemoveEvent):
    """Remove obsolete revision."""
    event.secret.remove_revision(event.revision)
```

**Observing secret events** (from `src/charm.py:111-113`):

```python
# These are dedicated handlers (permitted by constitution)
self.framework.observe(self.on.secret_rotate, self._on_secret_rotate)
self.framework.observe(self.on.secret_expired, self._on_secret_expired)
self.framework.observe(self.on.secret_remove, self._on_secret_remove)

# secret_changed goes through the reconciler
self.framework.observe(self.on.secret_changed, self._reconcile)
```

---

## 9. Storage

**charmcraft.yaml section**:

```yaml
storage:
  data:
    type: filesystem
    minimum-size: 1G
  logs:
    type: filesystem
    minimum-size: 512M
    multiple-range: 0-1    # Optional storage (0 or 1 instances)

containers:
  my-container:
    mounts:
      - storage: data
        location: /var/lib/myapp
      - storage: logs
        location: /var/log/myapp
```

**Handling storage events** (from `src/charm.py:103-106`):

```python
self.framework.observe(self.on.data_storage_attached, self._reconcile)
self.framework.observe(self.on.data_storage_detaching, self._reconcile)
```

**Writing storage markers** (from `src/charm.py:308-331`):

```python
# In the reconciler, write a marker file to verify storage persistence
for s_name, s_cfg in workload.STORAGE_CONFIG.items():
    if self.model.storages.get(s_name):
        marker_path = f"{s_cfg['path']}/{s_cfg['marker']}"
        try:
            if not container.exists(marker_path):
                container.push(marker_path, json.dumps({
                    "created_by": self.unit.name,
                    "storage": s_name,
                }), make_dirs=True)
        except (ops.pebble.ConnectionError, ops.pebble.PathError):
            pass  # Storage not ready yet — reconciler will retry
```

---

## 10. Actions

**charmcraft.yaml section**:

```yaml
actions:
  get-config:
    description: Return current effective configuration
  check-storage:
    description: Check storage status
    params:
      name:
        type: string
        description: "Storage name: data or logs"
        default: data
  fail-action:
    description: Intentionally fail
    params:
      message:
        type: string
        default: "Intentional failure"
```

**Action handler pattern** (from `src/charm.py:420-433`):

```python
def _on_get_config_action(self, event: ops.ActionEvent):
    event.log("Retrieving configuration")    # Logged to juju run output
    event.set_results({
        "my-string": str(self.config.get("my-string", "default")),
        "my-int": str(self.config.get("my-int", 8080)),
    })

def _on_fail_action(self, event: ops.ActionEvent):
    message = event.params.get("message", "Intentional failure")
    event.fail(message)  # Marks the action as failed
```

**Key rules**:
- Action results values must be strings
- Use `event.log()` for progress messages
- Use `event.fail()` for errors (not exceptions)
- Use `event.set_results()` for success output

---

## 11. COS Observability Integration

**charmcraft.yaml section**:

```yaml
provides:
  metrics-endpoint:
    interface: prometheus_scrape
    optional: true
  grafana-dashboard:
    interface: grafana_dashboard
    optional: true
requires:
  log-proxy:
    interface: loki_push_api
    optional: true
    limit: 1

charm-libs:
  - lib: prometheus-k8s.prometheus_scrape
    version: "0"
  - lib: grafana-k8s.grafana_dashboard
    version: "0"
  - lib: loki-k8s.loki_push_api
    version: "1"
```

**Initialization** (from `src/charm.py:143-152`):

```python
# In __init__, after all event observers
self._metrics_endpoint = MetricsEndpointProvider(
    self,
    jobs=[{"static_configs": [{"targets": [f"*:{workload.DEFAULT_PORT}"]}]}],
)
self._grafana_dashboard = GrafanaDashboardProvider(self)
self._log_forwarder = LogForwarder(self, relation_name="log-proxy")
```

**Dashboard and alert rule files**:
- `src/grafana_dashboards/my-dashboard.json` — auto-loaded by GrafanaDashboardProvider
- `src/prometheus_alert_rules/my_alerts.yaml` — auto-loaded by MetricsEndpointProvider

**Deploying with COS**:
```bash
juju integrate my-charm:metrics-endpoint prometheus-k8s:metrics-endpoint
juju integrate my-charm:grafana-dashboard grafana-k8s:grafana-dashboard
juju integrate my-charm:log-proxy loki-k8s:logging
```

---

## 12. Security (Non-Root Execution)

**charmcraft.yaml section**:

```yaml
charm-user: non-root    # Charm code runs as UID 170

containers:
  my-container:
    uid: 584792          # Workload runs as _daemon_
    gid: 584792
```

**rockcraft.yaml section**:

```yaml
base: bare              # Distroless — no shell, no package manager
run_user: _daemon_      # Default UID in the image
```

**Checking security posture** (from `src/charm.py:873-911`):

```python
def _on_check_security_action(self, event: ops.ActionEvent):
    results = {
        "charm-uid": str(os.getuid()),     # Should be 170 (non-root)
        "charm-gid": str(os.getgid()),
    }
    container = self.unit.get_container("my-container")
    if container.can_connect():
        proc = container.exec(["id", "-u"])
        stdout, _ = proc.wait_output()
        results["workload-uid"] = stdout.strip()  # Should be 584792
```

**Password generation**: Always use `secrets.token_urlsafe()`, never hardcoded values.

---

## 13. Pebble File and Exec Operations

**File operations** (from `src/charm.py:701-738`):

```python
container = self.unit.get_container("my-container")

# Push a file
container.push("/path/to/file.txt", "content", make_dirs=True)

# Pull a file
content = container.pull("/path/to/file.txt").read()

# Check existence
exists = container.exists("/path/to/file.txt")

# Remove
container.remove_path("/path/to/file.txt")

# Make directory
container.make_dir("/path/to/dir", make_parents=True)

# List files
files = container.list_files("/path/to")
names = [f.name for f in files]
```

**Exec operations** (from `src/charm.py:717-727`):

```python
# Run a command and wait
proc = container.exec(["/bin/myapp", "--check"])
proc.wait()

# Run a command and capture output
proc = container.exec(["id", "-u"])
stdout, stderr = proc.wait_output()
uid = stdout.strip()

# Service operations
container.start("my-service")
container.stop("my-service")
container.restart("my-service")
```

---

## 14. Custom Pebble Notices

**What**: Workload-to-charm signaling. The workload sends a notice, Juju dispatches `pebble-custom-notice` to the charm.

**Observing** (from `src/charm.py:140`):

```python
self.framework.observe(self.on.my_container_pebble_custom_notice, self._reconcile)
```

**Sending a notice from inside the container** (from `src/charm.py:802-808`):

```python
# Using the Pebble binary inside the container
cmd = ["/charm/bin/pebble", "notify", "myapp.com/event-key"]
for k, v in data.items():
    cmd.append(f"{k}={v}")
process = container.exec(cmd)
process.wait()
```

**Reading notice data in the reconciler**:

```python
if isinstance(event, ops.PebbleCustomNoticeEvent):
    key = event.notice.key  # e.g., "myapp.com/event-key"
```

---

## 15. Unit Testing with ops.testing (Scenario)

**Basic test** (from `tests/unit/test_charm.py:34-56`):

```python
def test_active_when_pebble_connected(self):
    ctx = ops.testing.Context(NormaK8sCharm)
    state = ops.testing.State(
        containers=[
            ops.testing.Container(name="norma", can_connect=True),
            ops.testing.Container(name="norma-secondary", can_connect=False),
        ],
    )
    out = ctx.run(ctx.on.collect_unit_status(), state)
    assert out.unit_status == ops.ActiveStatus()
```

**Testing with config** (from `tests/unit/test_charm.py`):

```python
state = ops.testing.State(
    containers=[container],
    config={"calibration-int": 9090, "calibration-string": "test"},
)
```

**Testing with relations**:

```python
peer = ops.testing.PeerRelation(
    endpoint="norma-peers",
    peers_data={1: {"unit-name": "norma-k8s/1"}},
)
state = ops.testing.State(containers=[container], relations=[peer])
```

**Testing with storage**:

```python
storage = ops.testing.Storage(name="data")
state = ops.testing.State(containers=[container], storage=[storage])
```

**Testing actions**:

```python
ctx = ops.testing.Context(NormaK8sCharm)
out = ctx.run(ctx.on.action("get-config"), state)
assert out.action_results["calibration-string"] == "default"
```

---

## 16. Integration Testing with jubilant

**Fixture pattern** (from `tests/integration/conftest.py:104-153`):

```python
@pytest.fixture(scope="session")
def juju(environment_ready, charm_path, oci_image):
    with jubilant.temp_model(controller="microk8s-localhost") as j:
        j.deploy(str(charm_path), app=APP, resources={RESOURCE_NAME: oci_image})
        j.wait(jubilant.all_active, timeout=300)
        yield j
```

**Test pattern**:

```python
def test_get_config(juju):
    result = juju.run("my-charm/0", "get-config")
    assert result.results["my-string"] == "default"

def test_config_change(juju):
    juju.config("my-charm", {"my-int": "9090"})
    juju.wait(jubilant.all_active, timeout=60)
    result = juju.run("my-charm/0", "get-config")
    assert result.results["my-int"] == "9090"
```

---

## 17. Event Deferral (Testing Only)

**What**: `event.defer()` re-queues an event for later dispatch. This charm tests it but does NOT use it for control flow.

**Pattern** — deferral lives OUTSIDE the reconciler (from `src/charm.py:158-177`):

```python
def _on_defer_gate(self, event):
    """Intercept events before the reconciler. Defer if armed."""
    if self._defer_armed:
        event.defer()
        self._defer_armed = False
        return
    self._reconcile(event)  # Normal path
```

**Constitutional rule**: The reconciler itself MUST NEVER call `event.defer()`. If you need deferral for testing purposes, use a gate handler that sits between the event and the reconciler.

---

## 18. Multiple Containers

**charmcraft.yaml section**:

```yaml
containers:
  primary:
    resource: my-image
    uid: 584792
    gid: 584792
    mounts:
      - storage: data
        location: /var/lib/myapp
  secondary:
    resource: my-image    # Can reuse the same image
    uid: 584792
    gid: 584792
```

**Handling in the reconciler** (from `src/charm.py:337-345`):

```python
# Primary container
container = self.unit.get_container("primary")
if container.can_connect():
    container.add_layer("primary", primary_layer, combine=True)
    container.replan()

# Secondary container (different port to avoid conflicts)
secondary = self.unit.get_container("secondary")
if secondary.can_connect():
    secondary.add_layer("secondary", secondary_layer, combine=True)
    secondary.replan()
```

**Pebble events for each container**:

```python
self.framework.observe(self.on.primary_pebble_ready, self._reconcile)
self.framework.observe(self.on.secondary_pebble_ready, self._reconcile)
```

**Key gotcha**: When reusing the same ROCK image, the image's default Pebble service will start on both containers. Override the default service to `startup: disabled` in the secondary container's layer, then define a new service on a different port.
