# Scaffold: Building a New Juju K8s Charm from Scratch

This guide walks through creating a new charm from zero, starting with the minimal viable charm and adding features incrementally. Each section is independent — add only what your charm needs.

## Minimal Viable Charm

The absolute minimum for a working K8s charm with a Pebble-managed workload:

### Files to create

```
my-charm-k8s/
├── charmcraft.yaml      # Metadata, containers, resources
├── pyproject.toml       # Python config
├── Makefile             # Build commands
├── src/
│   ├── charm.py         # Juju lifecycle
│   └── workload.py      # Workload logic (no ops)
└── tests/
    ├── conftest.py      # (empty)
    └── unit/
        ├── conftest.py  # Cleanup fixtures
        ├── test_charm.py
        └── test_workload.py
```

### Step 1: `charmcraft.yaml`

```yaml
type: charm
name: my-charm-k8s
title: My Charm
summary: A K8s charm for my workload
description: |
  Describe what your charm does.

base: ubuntu@24.04
platforms:
  amd64:

parts:
  my-charm:
    plugin: uv
    source: .
    build-packages: [git]
    build-snaps: [astral-uv]

assumes:
  - juju >= 3.6
  - k8s-api

containers:
  my-workload:
    resource: my-image
    uid: 584792
    gid: 584792

resources:
  my-image:
    type: oci-image
    upstream-source: ghcr.io/myorg/myimage:latest
    description: OCI image for the workload

charm-user: non-root
```

### Step 2: `pyproject.toml`

```toml
[project]
name = "my-charm-k8s"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["ops"]

[project.optional-dependencies]
dev = ["ops[testing]", "pytest", "coverage[toml]", "ruff"]

[tool.ruff]
line-length = 99
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "A", "SIM", "RUF"]

[tool.coverage.run]
source = ["src"]
omit = ["tests/*"]

[tool.coverage.report]
show_missing = true

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "lib"]
```

### Step 3: `Makefile`

```makefile
.PHONY: lint fmt unit clean

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

fmt:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

unit:
	uv run coverage run -m pytest tests/unit -v
	uv run coverage report

clean:
	rm -rf *.charm __pycache__ .coverage htmlcov .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
```

### Step 4: `src/workload.py`

```python
"""Workload abstraction — zero ops dependency."""

CONTAINER_NAME = "my-workload"
DEFAULT_PORT = 8080
BINARY_PATH = "/bin/my-binary"


def validate_config(config: dict) -> tuple[bool, str]:
    port = config.get("port", DEFAULT_PORT)
    if not (1 <= port <= 65535):
        return False, f"Port must be 1-65535, got {port}"
    return True, ""


def build_pebble_layer(port: int) -> dict:
    return {
        "summary": "workload layer",
        "services": {
            CONTAINER_NAME: {
                "override": "replace",
                "startup": "enabled",
                "command": BINARY_PATH,
                "environment": {"PORT": str(port)},
            },
        },
    }
```

### Step 5: `src/charm.py`

```python
#!/usr/bin/env python3
"""My K8s charm — holistic reconciler architecture."""

import ops

import workload


class MyCharmK8s(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(self.on.install, self._reconcile)
        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._reconcile)
        self.framework.observe(self.on.my_workload_pebble_ready, self._reconcile)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)

    def _reconcile(self, event: ops.EventBase):
        container = self.unit.get_container(workload.CONTAINER_NAME)
        if not container.can_connect():
            return

        port = int(self.config.get("port", workload.DEFAULT_PORT))
        layer = workload.build_pebble_layer(port)
        container.add_layer(workload.CONTAINER_NAME, layer, combine=True)
        container.replan()
        self.unit.set_ports(ops.Port("tcp", port))

    def _on_collect_unit_status(self, event: ops.CollectStatusEvent):
        container = self.unit.get_container(workload.CONTAINER_NAME)
        if not container.can_connect():
            event.add_status(ops.WaitingStatus("Waiting for Pebble"))
            return
        event.add_status(ops.ActiveStatus())


if __name__ == "__main__":  # pragma: nocover
    ops.main(MyCharmK8s)
```

### Step 6: `tests/unit/test_charm.py`

```python
import ops
import ops.testing

from charm import MyCharmK8s

CONTAINER = ops.testing.Container(name="my-workload", can_connect=True)
CONTAINER_OFF = ops.testing.Container(name="my-workload", can_connect=False)


class TestStatus:
    def test_waiting_when_disconnected(self):
        ctx = ops.testing.Context(MyCharmK8s)
        state = ops.testing.State(containers=[CONTAINER_OFF])
        out = ctx.run(ctx.on.collect_unit_status(), state)
        assert out.unit_status == ops.WaitingStatus("Waiting for Pebble")

    def test_active_when_connected(self):
        ctx = ops.testing.Context(MyCharmK8s)
        state = ops.testing.State(containers=[CONTAINER])
        out = ctx.run(ctx.on.collect_unit_status(), state)
        assert out.unit_status == ops.ActiveStatus()
```

### Build and deploy

```bash
uv sync
uv run ruff check src/ tests/
uv run pytest tests/unit -v
charmcraft pack
juju deploy ./my-charm-k8s_ubuntu-24.04-amd64.charm \
    --resource my-image=ghcr.io/myorg/myimage:latest
```

---

## Feature Decision Matrix

Use this table to determine what to add based on your requirements.

| You need... | Add to charmcraft.yaml | Add to charm.py | Add to workload.py | Tests |
|-------------|----------------------|-----------------|-------------------|-------|
| **Config options** | `config.options` section | Read in `_reconcile()`, validate | `validate_config()` | Config-changed test |
| **Peer data sharing** | `peers` section | Observe relation events, write in `_reconcile()` | — | Peer relation test |
| **Provides/requires relation** | `provides`/`requires` section | Observe relation events | — | Relation test |
| **Persistent storage** | `storage` + container `mounts` | Observe storage events | Storage constants | Storage test |
| **Actions** | `actions` section | Dedicated `_on_*_action` handlers | — | Action test |
| **Health checks** | — | — | Add `checks` to Pebble layer | Check event test |
| **Secrets** | — | Create in `_reconcile()`, handle rotate/expire | — | Secret test |
| **COS observability** | `provides` (metrics, dashboard) + `requires` (log-proxy) + `charm-libs` | Initialize library objects in `__init__` | `/metrics` endpoint on workload | — |
| **Multiple containers** | Additional `containers` entry | Handle each container in `_reconcile()` | Secondary layer builder | Multi-container test |
| **Custom notices** | — | Observe `pebble_custom_notice` | Pebble notify command | Notice test |
| **Non-root security** | `charm-user: non-root` + container `uid`/`gid` | — | — | Security check test |

---

## Adding Config Options

### 1. charmcraft.yaml

```yaml
config:
  options:
    port:
      type: int
      default: 8080
      description: Workload listen port
```

### 2. workload.py — Update validation

```python
def validate_config(config: dict) -> tuple[bool, str]:
    port = config.get("port", DEFAULT_PORT)
    if not (1 <= port <= 65535):
        return False, f"Port must be 1-65535, got {port}"
    return True, ""
```

### 3. charm.py — Read in reconciler

```python
def _reconcile(self, event):
    config = {"port": int(self.config.get("port", workload.DEFAULT_PORT))}
    valid, error = workload.validate_config(config)
    if not valid:
        self._blocked_message = error
        return
    # Use config["port"] ...
```

---

## Adding Peer Relations

### 1. charmcraft.yaml

```yaml
peers:
  my-peers:
    interface: my_app_peers
```

### 2. charm.py

```python
# In __init__
self.framework.observe(self.on.my_peers_relation_joined, self._reconcile)
self.framework.observe(self.on.my_peers_relation_changed, self._reconcile)
self.framework.observe(self.on.my_peers_relation_departed, self._reconcile)
self.framework.observe(self.on.leader_elected, self._reconcile)

# In _reconcile
peer = self.model.get_relation("my-peers")
if peer and self.unit.is_leader():
    peer.data[self.app]["leader"] = self.unit.name
```

---

## Adding Storage

### 1. charmcraft.yaml

```yaml
storage:
  data:
    type: filesystem
    minimum-size: 1G

containers:
  my-workload:
    mounts:
      - storage: data
        location: /var/lib/myapp
```

### 2. charm.py

```python
# In __init__
self.framework.observe(self.on.data_storage_attached, self._reconcile)
self.framework.observe(self.on.data_storage_detaching, self._reconcile)

# In _reconcile — write a marker to verify persistence
if self.model.storages.get("data"):
    container = self.unit.get_container("my-workload")
    if container.can_connect() and not container.exists("/var/lib/myapp/.marker"):
        container.push("/var/lib/myapp/.marker", "initialized", make_dirs=True)
```

---

## Adding COS Observability

### 1. charmcraft.yaml

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

### 2. Fetch libraries

```bash
charmcraft fetch-libs
```

### 3. pyproject.toml — Add cosl dependency

```toml
dependencies = ["ops", "cosl", "pyyaml"]
```

### 4. charm.py

```python
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider

# In __init__
self._metrics = MetricsEndpointProvider(
    self, jobs=[{"static_configs": [{"targets": [f"*:{workload.DEFAULT_PORT}"]}]}]
)
self._grafana = GrafanaDashboardProvider(self)
self._loki = LogForwarder(self, relation_name="log-proxy")
```

### 5. Create dashboard and alert rule files

```
src/grafana_dashboards/my-dashboard.json
src/prometheus_alert_rules/my_alerts.yaml
```

---

## Adding Actions

### 1. charmcraft.yaml

```yaml
actions:
  get-info:
    description: Return application info
  do-something:
    description: Perform an operation
    params:
      target:
        type: string
        description: Target name
    required: [target]
```

### 2. charm.py

```python
# In __init__
self.framework.observe(self.on.get_info_action, self._on_get_info_action)
self.framework.observe(self.on.do_something_action, self._on_do_something_action)

def _on_get_info_action(self, event: ops.ActionEvent):
    event.set_results({"version": "1.0", "status": "running"})

def _on_do_something_action(self, event: ops.ActionEvent):
    target = event.params.get("target", "")
    if not target:
        event.fail("target is required")
        return
    # Do work...
    event.set_results({"result": f"Done with {target}"})
```

---

## Adding Integration Tests

### 1. pyproject.toml — Add jubilant

```toml
[project.optional-dependencies]
dev = ["ops[testing]", "pytest", "coverage[toml]", "jubilant", "ruff"]
```

### 2. Makefile

```makefile
integration:
	uv run pytest tests/integration -v --tb=short
```

### 3. tests/integration/conftest.py

```python
import jubilant
import pytest

APP = "my-charm-k8s"

@pytest.fixture(scope="session")
def juju():
    with jubilant.temp_model() as j:
        j.deploy("./my-charm-k8s_ubuntu-24.04-amd64.charm",
                 app=APP,
                 resources={"my-image": "ghcr.io/myorg/myimage:latest"})
        j.wait(jubilant.all_active, timeout=300)
        yield j
```

### 4. tests/integration/test_basic.py

```python
def test_charm_active(juju):
    status = juju.status()
    assert status.apps["my-charm-k8s"].status.current == "active"

def test_get_info_action(juju):
    result = juju.run("my-charm-k8s/0", "get-info")
    assert result.results["version"] == "1.0"
```

---

## Workload Binary (Go)

If your charm manages a custom Go binary:

### workload/main.go (minimal)

```go
package main

import (
    "fmt"
    "net/http"
    "os"
)

func main() {
    port := os.Getenv("PORT")
    if port == "" {
        port = "8080"
    }
    http.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
        fmt.Fprint(w, "OK")
    })
    http.ListenAndServe(":"+port, nil)
}
```

### rockcraft.yaml

```yaml
name: my-workload
base: bare
build-base: ubuntu@24.04
version: "0.1.0"
license: Apache-2.0
platforms:
  amd64:

run_user: _daemon_

services:
  my-workload:
    override: replace
    command: /bin/my-binary
    startup: enabled

parts:
  tmp-dir:
    plugin: nil
    override-build: |
      mkdir -p ${CRAFT_PART_INSTALL}/tmp
      chmod 1777 ${CRAFT_PART_INSTALL}/tmp
    stage:
      - tmp
  my-binary:
    plugin: go
    source: workload/
    build-snaps: [go/1.22/stable]
    build-environment:
      - CGO_ENABLED: "0"
    override-build: |
      go build -o ${CRAFT_PART_INSTALL}/bin/my-binary \
        -tags "osusergo,netgo" \
        -ldflags="-s -w" ./...
    stage:
      - bin/my-binary
```

### Build and push

```bash
rockcraft pack
rockcraft.skopeo --insecure-policy copy \
    oci-archive:my-workload_0.1.0_amd64.rock \
    docker://localhost:32000/my-workload:0.1.0 \
    --dest-tls-verify=false
```
