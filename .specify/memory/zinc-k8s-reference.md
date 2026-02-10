# zinc-k8s Reference Patterns

Source: https://github.com/jnsgruk/zinc-k8s-operator
Author: Jon Seager (@jnsgruk), VP Engineering at Canonical

> NOTE: Author disclaims this as a "toy charm for experimentation"
> but the patterns are modern and well-structured.

## Key Architectural Decisions

### Minimal Event Observers
Only TWO events observed in charm.py:
- `pebble_ready` — single entry point for workload configuration
- `update_status` — periodic status refresh

No config-changed, install, or start observers. Relies on Pebble
readiness as the sole trigger. Relations are handled entirely by
charm libraries initialized in __init__.

### Clean Separation: charm.py vs zinc.py

**charm.py** handles:
- Event observation (pebble_ready, update_status)
- Relation object instantiation (5 integrations)
- Juju secrets management (password generation)
- Port opening
- Status setting

**zinc.py** handles (ZERO ops dependency):
- `pebble_layer(password)` — returns dict layer config
- `port` property (4080)
- `log_path` property
- `version` property (queries live HTTP API with retries)

### Password via Juju Secrets + Peer Relation
- Leader generates password with `secrets.token_urlsafe(24)`
- Creates Juju secret, stores secret ID in peer relation app data
- Non-leader units retrieve secret by ID from peer relation
- No StoredState used anywhere

### Version Detection with Retry
```python
def _request_version(self) -> str:
    retries = 0
    while True:
        try:
            res = urllib.request.urlopen(
                f"http://localhost:{self._port}/version"
            )
            return json.loads(res.read().decode())["version"]
        except Exception:
            if retries == 3:
                raise
            retries += 1
            time.sleep(3)
```

## Project Structure

```
charmcraft.yaml           # uv plugin, charm-libs declarative
pyproject.toml            # uv-based deps, ruff config
uv.lock                   # Committed
Makefile                  # Replaces tox.ini entirely
rockcraft.yaml            # Chiselled ROCK image build
src/
  charm.py                # Juju lifecycle
  zinc.py                 # Workload (zero ops dependency)
  grafana_dashboards/     # JSON templates
  prometheus_alert_rules/ # Alert rules
  loki_alert_rules/       # .gitkeep
lib/charms/               # Fetched libs (5 integrations)
tests/
  conftest.py             # Root fixtures
  unit/
    test_charm.py          # ops.testing (Scenario)
    test_zinc.py           # Plain pytest
  integration/
    __init__.py            # Constants + retry decorator
    conftest.py            # jubilant fixtures
    test_charm_basic.py
    test_ingress_traefik.py
    test_path_ingress_traefik.py
    test_observability_relations.py
  spread/                  # Spread test suites (bash + python)
```

## Observability Stack

5 integrations:
1. MetricsEndpointProvider (prometheus_scrape)
2. LogProxyConsumer (loki_push_api) — forwards zinc.log
3. GrafanaDashboardProvider (grafana_dashboard) — 9-panel dashboard
4. ProfilingEndpointProvider (parca_scrape)
5. IngressPerAppRequirer (traefik ingress)

Alert rule: `ZincTargetMissing` fires immediately when `up == 0`

## CI/CD Automation Chain

Fully automated supply chain:
1. `update-oci.yaml` detects upstream Zinc release (weekly)
2. Creates PR to bump rockcraft.yaml
3. Merge triggers `publish-oci.yaml`
4. Builds chiselled ROCK, pushes to ghcr.io
5. Creates PR to update charmcraft.yaml resource ref
6. Merge triggers `release.yaml`
7. Tests pass -> publishes to CharmHub edge channel

Additional:
- `update-libs.yaml` weekly auto-updates charm libraries
- Dependabot for GitHub Actions + uv deps

## Testing Patterns

### Unit Tests (ops.testing)
```python
@pytest.fixture
def loaded_ctx(charm):
    ctx = Context(charm)
    container = Container(name="zinc", can_connect=True)
    return (ctx, container)

def test_zinc_pebble_ready(loaded_ctx):
    ctx, container = loaded_ctx
    state = State(containers=[container])
    result = ctx.run(ctx.on.pebble_ready(container=container), state)

    assert result.get_container("zinc").layers["zinc"] == \
        Zinc().pebble_layer("")
    assert result.get_container("zinc").service_statuses == {
        "zinc": ServiceStatus.ACTIVE
    }
    assert result.opened_ports == frozenset({TCPPort(4080)})
    assert result.workload_version == "0.2.6"
    assert result.unit_status == ActiveStatus()
```

### Integration Tests (jubilant)
```python
@pytest.fixture(scope="module")
def juju():
    with jubilant.temp_model() as juju:
        yield juju

def test_deploy(juju, zinc_charm, zinc_oci_image):
    juju.deploy(zinc_charm, app=ZINC,
                resources={"zinc-image": zinc_oci_image})
    juju.wait(jubilant.all_active)
```

## Key Takeaways for norma-k8s

1. Keep charm.py minimal — delegate to workload module and libraries
2. No config options if not needed — auto-generate secrets
3. uv everywhere — no tox, no pip, no requirements.txt in source
4. Self-build OCI images with rockcraft for supply chain control
5. Automate the full release pipeline with GitHub Actions
6. Spread for orchestrated integration testing in LXD VMs
7. go-runner for log forwarding in distroless images
