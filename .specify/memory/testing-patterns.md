# Testing Patterns for K8s Juju Charms

## Unit Tests: ops.testing (Scenario)

Install: `ops[testing]` (NOT `ops-scenario` separately)

### Basic Structure

```python
import ops
from ops import testing

def test_pebble_ready_sets_active():
    ctx = testing.Context(NormaCharm)
    container = testing.Container(name="norma", can_connect=True)
    state_in = testing.State(containers={container})

    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    assert state_out.unit_status == testing.ActiveStatus()
```

### Testing with Config

```python
def test_config_changed_blocks_on_invalid():
    ctx = testing.Context(NormaCharm)
    state_in = testing.State(
        config={"port": -1},
        containers={testing.Container("norma", can_connect=True)},
    )
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == testing.BlockedStatus(
        "port must be between 1 and 65535"
    )
```

### Testing Container File Operations

```python
def test_config_file_written():
    ctx = testing.Context(NormaCharm)
    container = testing.Container(name="norma", can_connect=True)
    state_in = testing.State(containers={container})

    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    fs = state_out.get_container("norma").get_filesystem(ctx)
    assert (fs / "etc" / "app" / "config.yaml").read_text() == expected
```

### Testing Command Execution

```python
def test_exec_command():
    container = testing.Container(
        name="norma",
        can_connect=True,
        execs={
            testing.Exec(
                command_prefix=["pg_dump"],
                return_code=0,
                stdout="OK",
            )
        },
    )
    state_in = testing.State(containers={container})
    ctx = testing.Context(NormaCharm)
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)
```

### Testing Relations

```python
def test_database_relation():
    ctx = testing.Context(NormaCharm)
    db_relation = testing.Relation(
        endpoint="database",
        interface="pgsql",
        remote_app_data={
            "host": "10.0.0.5",
            "port": "5432",
        },
    )
    container = testing.Container(name="norma", can_connect=True)
    state_in = testing.State(
        relations={db_relation},
        containers={container},
    )
    state_out = ctx.run(
        ctx.on.relation_changed(db_relation), state_in
    )
    assert state_out.unit_status == testing.ActiveStatus()
```

### Testing Peer Relations and Secrets

```python
def test_password_generation():
    ctx = testing.Context(NormaCharm)
    peer = testing.PeerRelation(endpoint="norma-peers")
    secret = testing.Secret(
        id="secret:abc",
        label="initial-admin-password",
        owner="application",
        contents={0: {"password": "test123"}},
    )
    container = testing.Container(name="norma", can_connect=True)
    state_in = testing.State(
        leader=True,
        relations={peer},
        secrets={secret},
        containers={container},
    )
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)
```

### Testing Pebble Layers

```python
def test_pebble_layer_structure():
    ctx = testing.Context(NormaCharm)
    container = testing.Container(name="norma", can_connect=True)
    state_in = testing.State(containers={container})

    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    assert state_out.get_container("norma").layers["norma"] == \
        Norma().pebble_layer("")
    assert state_out.get_container("norma").service_statuses == {
        "norma": testing.ServiceStatus.ACTIVE
    }
```

### Testing Opened Ports

```python
def test_port_opened():
    ctx = testing.Context(NormaCharm)
    container = testing.Container(name="norma", can_connect=True)
    state_in = testing.State(containers={container})

    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    assert state_out.opened_ports == frozenset({testing.TCPPort(8080)})
```

### Live Charm Introspection (Context Manager)

```python
def test_charm_property():
    ctx = testing.Context(NormaCharm)
    state_in = testing.State(...)

    with ctx(ctx.on.start(), state_in) as manager:
        charm = manager.charm
        assert charm.some_property == expected_value
```

### Key Classes Reference

| Class | Purpose |
|---|---|
| Context(charm_type) | Main entry point |
| State(...) | Complete Juju state snapshot (immutable) |
| Relation(endpoint, ...) | Cross-app relation with databags |
| PeerRelation(endpoint, ...) | Peer relation with peers_data |
| Container(name, can_connect, ...) | Workload container |
| Mount(location, source) | Filesystem mount |
| Exec(command_prefix, return_code, ...) | Mock command execution |
| Secret(id, label, owner, content) | Juju secret |
| Storage(name, index) | Storage attachment |
| Network(binding_name, ...) | Network binding |

## Integration Tests: jubilant

Install: `jubilant`

### Conftest Pattern

```python
# tests/integration/conftest.py
import os
import pathlib
import pytest
import jubilant

@pytest.fixture(scope="module")
def juju():
    with jubilant.temp_model() as juju:
        yield juju

@pytest.fixture(scope="module")
def charm():
    path = os.environ.get("CHARM_PATH")
    if path:
        return pathlib.Path(path)
    charm_files = list(pathlib.Path(".").glob("*.charm"))
    assert charm_files, "No .charm file found; run charmcraft pack"
    return charm_files[0]

@pytest.fixture(scope="module")
def oci_image():
    return os.environ.get(
        "NORMA_IMAGE", "ghcr.io/myorg/juju-norma:latest"
    )
```

### Basic Tests

```python
def test_deploy(juju, charm, oci_image):
    juju.deploy(charm, app="norma-k8s",
                resources={"norma-image": oci_image})
    juju.wait(jubilant.all_active)

def test_config_change(juju):
    juju.config("norma-k8s", {"log-level": "debug"})
    juju.wait(jubilant.all_active)

def test_action(juju):
    result = juju.run("norma-k8s/0", "create-backup",
                      {"target": "/tmp/backup.sql"})
    assert result["backup-path"] == "/tmp/backup.sql"

def test_integration(juju, charm):
    juju.deploy("postgresql-k8s", trust=True)
    juju.integrate("norma-k8s:database", "postgresql-k8s:database")
    juju.wait(jubilant.all_active, timeout=300)
```

### Retry Decorator (from zinc-k8s)

```python
import functools
import time

def retry(retry_num, retry_sleep_sec):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(retry_num):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if i >= retry_num - 1:
                        raise Exception(
                            f"Exceeded {retry_num} retries"
                        ) from exc
                    time.sleep(retry_sleep_sec)
        return wrapper
    return decorator
```

### Running Integration Tests

```bash
charmcraft pack
CHARM_PATH=./norma-k8s_amd64.charm make integration
```

## Workload Module Tests (Plain Pytest)

Since `src/norma.py` has zero ops dependency, test with plain pytest:

```python
# tests/unit/test_norma.py
from norma import Norma

def test_pebble_layer_structure():
    norma = Norma()
    layer = norma.pebble_layer("testpass123")
    assert "norma" in layer["services"]
    assert layer["services"]["norma"]["startup"] == "enabled"

def test_port():
    norma = Norma()
    assert isinstance(norma.port, int)
    assert 1 <= norma.port <= 65535

def test_log_path():
    norma = Norma()
    assert isinstance(norma.log_path, str)
```

## Lint: ruff

```toml
# pyproject.toml
[tool.ruff]
line-length = 99
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B", "S"]

[tool.coverage.run]
source = ["src"]
```

## Test Directory Structure

```
tests/
  conftest.py              # Root: shared fixtures, CLI options
  unit/
    test_charm.py           # ops.testing state-transition tests
    test_norma.py           # Plain pytest for workload module
  integration/
    __init__.py             # Constants, retry decorator
    conftest.py             # jubilant fixtures
    test_charm_basic.py     # Deploy, HTTP, auth tests
    test_ingress.py         # Ingress relation tests
    test_observability.py   # COS relation tests
```
