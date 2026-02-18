# Pitfalls: Common Mistakes in Juju K8s Charm Development

Every entry here is a real mistake made during the development of this charm. Each one includes what went wrong, why, and the fix.

---

## Pebble & Container

### Bare-base ROCK + Pebble user resolution

**Symptom**: Pebble fails to start the service with a user resolution error.

**Cause**: `base: bare` has no NSS libraries (`libnss`). Pebble can't resolve usernames like `_daemon_`.

**Wrong**:
```yaml
# In Pebble layer
services:
  my-service:
    user: _daemon_    # Pebble can't resolve this on bare base
```

**Fix**: Don't set `user` in Pebble layers. Let the OCI image's `run_user: _daemon_` handle it. Set matching UID/GID in charmcraft.yaml:
```yaml
containers:
  my-container:
    uid: 584792    # Numeric UID for _daemon_
    gid: 584792
```

### Secondary container port conflict

**Symptom**: Both containers try to bind port 8080, one fails.

**Cause**: When reusing the same ROCK image for multiple containers, the image's default Pebble service starts in both containers on the same port.

**Fix**: In the secondary container's Pebble layer, explicitly disable the default service and create a new one on a different port:
```python
{
    "services": {
        "norma": {  # The default service from the ROCK
            "override": "replace",
            "startup": "disabled",  # Disable it
            "command": "/bin/norma",
        },
        "norma-secondary": {  # New service on different port
            "override": "replace",
            "startup": "enabled",
            "command": "/bin/norma",
            "environment": {"PORT": "8081"},
        },
    },
}
```

### Health flag file path on bare-base

**Symptom**: Health toggle fails with "permission denied" when writing to `/tmp/`.

**Cause**: On bare-base images, `/tmp` might not exist or might not be writable by the container's user.

**Fix**: Add a `tmp-dir` part to `rockcraft.yaml` that creates `/tmp` with mode 1777. Or use a path under a mounted storage volume instead.

---

## Rockcraft & OCI

### Go plugin doesn't support ldflags

**Symptom**: Version injection via `-ldflags="-X main.version=..."` doesn't work with the `go` plugin.

**Cause**: The rockcraft Go plugin only supports `go-buildtags` and `go-generate` keys. It does not support arbitrary build flags.

**Fix**: Use `override-build` with an explicit `go build` command:
```yaml
parts:
  my-binary:
    plugin: go
    override-build: |
      go build -o ${CRAFT_PART_INSTALL}/bin/myapp \
        -tags "osusergo,netgo" \
        -ldflags="-s -w -X main.version=0.1.0" ./...
    stage:
      - bin/myapp
```

### Multi-arch ROCK build architecture variable

**Symptom**: Building for arm64 still produces an amd64 binary.

**Cause**: The Go plugin doesn't automatically set `GOARCH` from the target platform.

**Fix**: Use `CRAFT_ARCH_BUILD_FOR` in `override-build`:
```yaml
override-build: |
  export GOARCH=${CRAFT_ARCH_BUILD_FOR:-amd64}
  go build -o ${CRAFT_PART_INSTALL}/bin/myapp ./...
```

---

## Charmcraft

### charm-libs field rejects `charms.` prefix

**Symptom**: `charmcraft fetch-libs` fails with an error about invalid library name.

**Cause**: charmcraft 4.x `charm-libs` field expects short names.

**Wrong**:
```yaml
charm-libs:
  - lib: charms.prometheus_k8s.v0.prometheus_scrape
```

**Fix**:
```yaml
charm-libs:
  - lib: prometheus-k8s.prometheus_scrape
    version: "0"
```

### Secret config cannot have a default

**Symptom**: `charmcraft pack` fails validation on a secret-type config option.

**Cause**: Juju secret-type config options cannot have default values — the value must always be explicitly set by the user.

**Wrong**:
```yaml
config:
  options:
    my-secret:
      type: secret
      default: ""    # Not allowed
```

**Fix**: Omit the `default` field entirely:
```yaml
config:
  options:
    my-secret:
      type: secret
      description: A secret URI
```

---

## Juju CLI (v4)

### No `-y` flag on destroy-model

**Symptom**: `juju destroy-model -y model-name` fails with "unknown flag".

**Cause**: Juju 4.x replaced `-y` with `--no-prompt`.

**Fix**: Use `--no-prompt`:
```bash
juju destroy-model model-name --no-prompt --destroy-storage
```

### Action params use `key=value`, not `--params`

**Symptom**: `juju run unit/0 my-action --params file.yaml` fails.

**Cause**: Juju 4.x uses inline `key=value` syntax for action parameters.

**Fix**:
```bash
juju run my-charm/0 set-status status=blocked message="test"
```

### OCI deploy race condition

**Symptom**: Charm deploys but unit never becomes active. Pod shows image pull error.

**Cause**: Juju bug (juju/juju#21456) — `deployResources()` races with `Deploy()`. The unit starts before the OCI resource is attached.

**Fix**: Patched in Juju 4.0.2+. For earlier versions, `juju attach-resource` after deploy.

---

## Python

### datetime.UTC is Python 3.11+

**Symptom**: `AttributeError: module 'datetime' has no attribute 'UTC'`.

**Cause**: `datetime.UTC` was added in Python 3.11. Charmcraft builds with 3.12, but local dev environments may use 3.10.

**Wrong**:
```python
datetime.datetime.now(datetime.UTC)
```

**Fix**:
```python
datetime.datetime.now(datetime.timezone.utc)
```

Note: If your `pyproject.toml` specifies `requires-python = ">=3.12"`, you can use `datetime.UTC` safely. The pitfall only applies when supporting older Python.

---

## Relations

### Relation data feedback loops

**Symptom**: `relation-changed` events fire continuously in a loop.

**Cause**: Writing to relation data triggers `relation-changed` on all related units. If the handler writes back unconditionally, it creates an infinite loop.

**Fix**: Always check if values changed before writing:
```python
existing = peer.data[self.unit]
new_data = {"key": "value"}
if any(existing.get(k) != v for k, v in new_data.items()):
    existing.update(new_data)
```

### Self-relations don't work in Juju 4

**Symptom**: `juju integrate my-app:provider my-app:requirer` fails.

**Cause**: Juju 4 does NOT support same-application provides/requires self-relations. Only peer relations are self-relations.

**Fix**: Deploy two instances of the same charm under different names:
```bash
juju deploy ./my-charm.charm my-app
juju deploy ./my-charm.charm my-app-peer --resource ...
juju integrate my-app:provider my-app-peer:requirer
```

### Broken relation — don't re-grant secrets

**Symptom**: Secret grant error during `relation-broken` event.

**Cause**: When a relation is broken, the reconciler still iterates over all relations to grant secret access. Granting to the broken relation fails.

**Fix**: Track the broken relation and skip it:
```python
broken_relation = None
if isinstance(event, ops.RelationBrokenEvent):
    broken_relation = event.relation

for rel in self.model.relations.get("my-provider", []):
    if rel is not broken_relation:
        secret.grant(rel)
```

---

## Testing

### ops.testing requires all containers in State

**Symptom**: `KeyError` or missing container error in unit tests.

**Cause**: If your charm references multiple containers, all must be defined in the test State — even if disconnected.

**Fix**: Always include all containers:
```python
state = ops.testing.State(
    containers=[
        ops.testing.Container(name="primary", can_connect=True),
        ops.testing.Container(name="secondary", can_connect=False),
    ],
)
```

### Event ledger pollution across tests

**Symptom**: Test assertions fail because the event ledger contains events from previous tests.

**Cause**: The event ledger persists to a file on disk. Without cleanup, events accumulate.

**Fix**: Use an autouse fixture:
```python
@pytest.fixture(autouse=True)
def _clean_ledger():
    pathlib.Path("/tmp/my-event-ledger.json").unlink(missing_ok=True)
    yield
    pathlib.Path("/tmp/my-event-ledger.json").unlink(missing_ok=True)
```

---

## Status

### ActiveStatus with a message

**Symptom**: Code review rejection.

**Cause**: Convention violation. `ActiveStatus` should never carry a message. If you need to communicate information, use a different status type or an action.

**Wrong**:
```python
event.add_status(ops.ActiveStatus("Running on port 8080"))
```

**Fix**:
```python
event.add_status(ops.ActiveStatus())  # No message
```

### Setting status in individual handlers

**Symptom**: Status flickers between different values.

**Cause**: Different handlers set different statuses. The last handler to run "wins", regardless of priority.

**Fix**: Never set status in lifecycle handlers. Use `collect_unit_status` exclusively, where you can add multiple statuses and ops resolves priority.

---

## StoredState

### Using StoredState at all

**Symptom**: State lost after pod restart.

**Cause**: `StoredState` is stored in the Juju agent's local database, which is lost when a K8s pod is recreated (scale down/up, node eviction, OOM kill).

**Fix**: Never use StoredState. Use instead:
1. Re-read from workload/environment
2. Peer relation data (persists across pod restarts)
3. Juju storage
4. Database relation

---

## Build Environment

### Missing astral-uv snap for charmcraft pack

**Symptom**: `charmcraft pack` fails during the build step.

**Cause**: The `uv` plugin in charmcraft requires the `astral-uv` snap.

**Fix**:
```bash
sudo snap install astral-uv --classic
```

### podman vs docker for ROCK management

**Symptom**: `docker` commands not found, or permissions issues.

**Cause**: Some environments have podman instead of docker.

**Fix**: Use `rockcraft.skopeo` (bundled with rockcraft snap) for image management:
```bash
rockcraft.skopeo --insecure-policy copy \
    oci-archive:my-image.rock \
    docker://localhost:32000/my-image:tag \
    --dest-tls-verify=false
```
