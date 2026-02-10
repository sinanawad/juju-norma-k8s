# Charm Implementation Patterns

## Pebble Layer Configuration

Full layer with all options:
```python
def _pebble_layer(self) -> ops.pebble.Layer:
    return ops.pebble.Layer({
        "summary": "norma layer",
        "services": {
            "norma": {
                "override": "replace",
                "startup": "enabled",
                "command": "/app/bin/server --config /etc/app/config.yaml",
                "environment": {
                    "APP_PORT": "8080",
                    "APP_LOG_LEVEL": "info",
                },
                "user": "appuser",
                "after": ["migration"],       # service ordering
                "on-success": "restart",
                "on-failure": "restart",
                "backoff-delay": "500ms",
                "backoff-factor": 2.0,
                "backoff-limit": "30s",
            },
        },
        "checks": {
            "health": {
                "override": "replace",
                "level": "ready",             # "alive" or "ready"
                "http": {"url": "http://localhost:8080/health"},
                "period": "10s",
                "threshold": 3,
                "timeout": "3s",
            },
        },
    })
```

## Pebble Operations

```python
container = self.unit.get_container("norma")

# Always wrap in try/except
try:
    container.add_layer("norma", layer, combine=True)
    container.replan()
except ops.pebble.ConnectionError:
    self.unit.status = ops.WaitingStatus("Waiting for Pebble")
    return
except ops.pebble.ChangeError as e:
    self.unit.status = ops.BlockedStatus(f"Service failed: {e}")
    return

# File operations
container.push("/etc/app/config.yaml", content, make_dirs=True)
content = container.pull("/etc/app/config.yaml").read()
container.exists("/path/to/file")

# Command execution
process = container.exec(
    ["pg_dump", "mydb"],
    environment={"PGPASSWORD": password},
    working_dir="/tmp",
    timeout=300,
    service_context="norma",  # inherit service env
)
stdout, stderr = process.wait_output()
```

## Holistic Status Pattern (collect_unit_status)

```python
class NormaCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        # ... observe other events routing to _reconcile ...

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        container = self.unit.get_container("norma")
        if not container.can_connect():
            event.add_status(ops.WaitingStatus("Waiting for Pebble"))
            return

        if not self._is_config_valid():
            event.add_status(ops.BlockedStatus("Invalid configuration"))

        if not self._has_database_relation():
            event.add_status(ops.BlockedStatus("Missing database relation"))

        if not self._is_tls_configured():
            event.add_status(ops.WaitingStatus("Waiting for TLS certificates"))

        # If nothing else was added, we're good
        event.add_status(ops.ActiveStatus())
```

Multiple add_status() calls allowed; framework picks highest priority:
BlockedStatus > MaintenanceStatus > WaitingStatus > ActiveStatus

## Secrets Pattern (from zinc-k8s)

```python
def _generated_password(self) -> str:
    relation = self.model.get_relation("norma-peers")
    if not relation:
        return ""

    secret_id = relation.data[self.app].get("initial-admin-password", None)
    if secret_id:
        secret = self.model.get_secret(id=secret_id)
        return secret.peek_content().get("password")

    if self.unit.is_leader():
        content = {"password": secrets.token_urlsafe(24)}
        secret = self.app.add_secret(content)
        relation.data[self.app]["initial-admin-password"] = secret.id
        return content["password"]
    else:
        return ""
```

## Secret Lifecycle (Full)

```python
# Owner creates and grants
secret = self.app.add_secret(
    {"password": generate_password()},
    label="db-credentials",
    rotate=ops.SecretRotate.MONTHLY,
)
secret.grant(event.relation)
event.relation.data[self.app]["secret-id"] = secret.id

# Observer retrieves
secret = self.model.get_secret(id=secret_id)
content = secret.get_content(refresh=True)

# Rotation handler
def _on_secret_rotate(self, event):
    event.secret.set_content({"password": generate_password()})

# Cleanup handler (MUST handle to prevent revision accumulation)
def _on_secret_remove(self, event):
    event.secret.remove_revision(event.revision)
```

## Relations - Databag Access Rules

| Entity     | Own unit bag | Other unit bags | App bag read | App bag write |
|------------|-------------|-----------------|-------------|---------------|
| Leader     | R/W         | Read            | Read        | R/W           |
| Non-leader | R/W         | Read            | Read        | No            |

## Charm Lifecycle Event Order

### Setup Phase
1. install
2. leader-elected
3. config-changed (always fires between install and start)
4. start

### Operation Phase
- config-changed (on juju config changes)
- update-status (every 5 min by default)
- <container>-pebble-ready (on first readiness AND after pod churn)
- relation-created/joined/changed/departed/broken
- secret-changed/rotate/remove
- <action-name>-action
- pebble-custom-notice (Juju 3.4+)
- pebble-check-failed/recovered (Juju 3.6+)

### Teardown Phase
- stop
- remove

## Events That CANNOT Be Deferred
- Action events (raises RuntimeError)
- Framework events: pre-commit, commit, update-status
- Secret lifecycle: secret-expired, secret-rotate
- Cleanup: remove, stop

## Custom Notices (Workload-to-Charm)

From workload:
```bash
/charm/bin/pebble notify canonical.com/norma/backup-done path=/tmp/backup.sql
```

From charm:
```python
def _on_pebble_custom_notice(self, event: ops.PebbleCustomNoticeEvent):
    if event.notice.key == "canonical.com/norma/backup-done":
        path = event.notice.last_data["path"]
```

## Relation Interface Libraries

Always search charm-relation-interfaces repo first. Common interfaces:
- postgresql_client (data_platform_libs)
- mysql_client
- mongodb_client
- ingress (traefik_k8s)
- prometheus_scrape
- grafana_dashboard
- loki_push_api
- tls-certificates
- parca_scrape

Using a library:
```python
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires

self.database = DatabaseRequires(
    self, relation_name="database", database_name="mydb"
)
self.framework.observe(
    self.database.on.database_created, self._on_database_created
)
```

## Rolling Upgrades

Use `charm-rolling-ops` library for coordinating rolling operations
across units via peer relation. Gate upgrades behind explicit actions:
1. upgrade-charm event sets WaitingStatus("Upgrade pending")
2. Admin runs `juju run <unit> resume-upgrade`
3. Action triggers actual migration/restart
4. Each unit upgrades in sequence
