# Research: Juju K8s Calibration Charm

**Branch**: `001-calibration-charm` | **Date**: 2026-02-11

## R1: Go Workload Binary Design

**Decision**: Single-file Go binary (`workload/main.go`) using Go 1.22+
standard library `net/http.ServeMux` (enhanced method routing) with one
external dependency (`prometheus/client_golang`).

**Rationale**: Go 1.22+ `ServeMux` supports `"GET /health"` method-based
routing natively, eliminating third-party router dependencies. A single file
of ~150-200 lines keeps the workload trivially auditable.

**Alternatives considered**:
- Third-party router (chi, gorilla/mux): Unnecessary since Go 1.22+ ServeMux
  covers our needs.
- Multi-file Go package: Over-engineered for 5 endpoints.
- Off-the-shelf binary (caddy, nginx): Cannot provide the toggle-health and
  custom metrics endpoints needed for calibration.

### Endpoint Specification

| Endpoint | Method | Response | Purpose |
|----------|--------|----------|---------|
| `/health` | GET | 200 "OK" or 500 "UNHEALTHY" | Pebble HTTP check (level: ready) |
| `/version` | GET | `{"version":"X.Y.Z"}` JSON | Charm queries for workload version |
| `/ready` | GET | 200 "READY" | Simple readiness (always 200 when up) |
| `/metrics` | GET | Prometheus text exposition | `promhttp.Handler()` with custom metrics |
| `/toggle-health` | POST | `{"health":"unhealthy"}` JSON | Flips atomic health state |

### Health Toggle Design

Two complementary mechanisms:
1. **HTTP endpoint** (`POST /toggle-health`): Atomic flip via `sync/atomic.Bool`.
2. **Flag file** (`HEALTH_FLAG_FILE` env var, default `/tmp/norma-unhealthy`):
   If file exists → unhealthy. Charm uses `container.push()` / `container.remove_path()`
   to toggle. Preferred for chiselled containers (no curl).

### Configuration

| Env Var | Default | Purpose |
|---------|---------|---------|
| `PORT` | `8080` | Listen port |
| `HEALTH_FLAG_FILE` | `/tmp/norma-unhealthy` | Health override flag file path |
| `VERSION` | (build-time via ldflags) | Reported on `/version` |

### Build Command

```bash
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
  go build -trimpath \
    -ldflags="-s -w -X main.Version=1.0.0" \
    -o norma \
    ./workload/
```

- `CGO_ENABLED=0`: Fully static binary, no libc dependency.
- `-trimpath`: Removes local paths for reproducibility.
- `-ldflags="-s -w"`: Strips symbols/debug info (~30% smaller).
- `-X main.Version=...`: Injects version at compile time.
- Expected binary size: ~8-12 MB.

### Dependencies

```
# workload/go.mod
module github.com/canonical/juju-norma-k8s/workload

go 1.22

require github.com/prometheus/client_golang v1.21.0
```

### Custom Prometheus Metrics

- `norma_http_requests_total` (CounterVec: endpoint, status)
- `norma_health_toggles_total` (Counter)
- `norma_healthy` (Gauge: 0 or 1)

---

## R2: Chiselled ROCK (OCI Image)

**Decision**: `base: bare` (distroless) with Go plugin, `run_user: _daemon_`,
no libc or ca-certificates needed.

**Rationale**: `CGO_ENABLED=0` with `osusergo` and `netgo` build tags produces
a fully static binary. No dynamic library dependencies. The binary is an HTTP
server only (no outbound TLS), so CA certificates are unnecessary.

**Alternatives considered**:
- `base: ubuntu@24.04` full: 10x larger image, unnecessary runtime.
- Including `libc6_libs` slice: Only needed if CGO is enabled.
- Including `ca-certificates_data`: Only needed for outbound HTTPS.
- go-runner for log forwarding: Unnecessary; Pebble captures service stdout.

### rockcraft.yaml Design

```yaml
name: norma
base: bare
build-base: ubuntu@24.04
version: "0.1.0"
summary: Chiselled ROCK for Norma calibration workload
description: |
  Minimal distroless image containing the Norma Go binary.
  Used by the norma-k8s charm as a Pebble-managed workload.
license: Apache-2.0
platforms:
  amd64:
run_user: _daemon_

services:
  norma:
    override: replace
    command: /bin/norma
    startup: enabled

parts:
  norma:
    plugin: go
    source: workload/
    build-snaps:
      - go/1.22/stable
    build-environment:
      - CGO_ENABLED: "0"
      - GOFLAGS: "-trimpath"
    go-buildtags:
      - osusergo
      - netgo
    organize:
      bin/norma: bin/norma
    stage:
      - bin/norma
```

### Image Composition

The final image contains only:
1. Pebble binary (auto-injected by rockcraft for all ROCKs)
2. `/bin/norma` (the Go static binary)

Expected image size: < 20 MB total.

### Non-root Execution

- `run_user: _daemon_` sets the image default UID.
- `charmcraft.yaml` container `uid: 10000` / `gid: 10000` sets the K8s
  securityContext, which takes precedence at runtime.

---

## R3: Self-Relations in Juju

**Decision**: Declare `calibration-provider` (provides) and
`calibration-requirer` (requires) with the same `calibration` interface.
Self-relate with `juju integrate norma-k8s:calibration-provider norma-k8s:calibration-requirer`.

**Rationale**: Standard Juju provides/requires mechanism. Both endpoints on the
same app create a regular (non-peer) relation where the same app appears on
both sides.

**Key findings**:

- **Event firing**: Events fire on BOTH endpoints independently. Each unit
  receives `relation-created`, `relation-joined`, etc. for both provider and
  requirer sides.
- **Critical gotcha**: Juju 4 does NOT support same-application provides/requires
  self-relations (only peer self-relations). To test provides/requires, deploy
  two instances of the same charm as separate applications (e.g., `norma-k8s`
  and `norma-k8s-peer`). Use **unit-level databags** (`rel.data[self.unit]`)
  for directional data, or embed role information in keys.
- **Two-instance pattern**: Deploy the same charm twice under different app names,
  then `juju integrate app-a:provides app-b:requires`. Each relation object has
  separate databags. Requires explicit `juju integrate` and can be removed.

### Implementation Pattern

```python
# In charm __init__, route all relation events to _reconcile
for endpoint in ("calibration_provider", "calibration_requirer"):
    for suffix in ("relation_created", "relation_joined",
                   "relation_changed", "relation_departed",
                   "relation_broken"):
        event = getattr(self.on, f"{endpoint}_{suffix}")
        framework.observe(event, self._reconcile)
```

---

## R4: Secret-Type Config Options

**Decision**: Declare `calibration-secret` with `type: secret` in
charmcraft.yaml. No default value (unset by default). Charm resolves the
URI with `self.model.get_secret(id=...)`.

**Rationale**: Juju 3.x `secret` config type validates that the value is a
valid secret URI at the CLI level. Charm must resolve it explicitly.

**Key findings**:

- **No default**: Secret-type config cannot have a default value.
- **User workflow**: `juju add-secret` → `juju grant-secret <name> <app>` →
  `juju config <app> calibration-secret=secret:<id>`.
- **Grant required**: The user must grant the secret to the app before or
  when setting config. Without grant, charm gets permission error.
- **`secret-changed` event**: Fires when the secret owner creates a new
  revision. Charm should call `secret.get_content(refresh=True)`.
- **Validation**: Juju rejects non-URI strings for secret-type config.

### Access Pattern

```python
secret_uri = self.config.get("calibration_secret")
if secret_uri:
    secret = self.model.get_secret(id=secret_uri)
    content = secret.get_content(refresh=True)
```

---

## R5: COS Charm Libraries

**Decision**: Use the standard COS charm libraries at their current API versions.

**Libraries needed**:

| Library | Package | Version |
|---------|---------|---------|
| MetricsEndpointProvider | `charms.prometheus_k8s.v0.prometheus_scrape` | v0 |
| GrafanaDashboardProvider | `charms.grafana_k8s.v0.grafana_dashboard` | v0 |
| LogForwarder | `charms.loki_k8s.v1.loki_push_api` | v1 |

**Declaration in charmcraft.yaml** under `charm-libs:` and fetched via
`charmcraft fetch-libs`.

**Integration pattern** (from zinc-k8s reference):
```python
self._metrics = MetricsEndpointProvider(
    self, jobs=[{"static_configs": [{"targets": [f"*:{port}"]}]}]
)
self._grafana = GrafanaDashboardProvider(self)
self._loki = LogForwarder(
    self, relation_name="log-proxy"
)
```

---

## R6: Charm Introspection Action (US22)

**Decision**: Each report section is a JSON-encoded string value in the Juju action results dict, keyed by section name. Individual private collector methods on the charm class (`_collect_config()`, `_collect_relations()`, etc.), each returning a plain dict.

**Rationale**: Juju action results are key-value pairs where values must be strings. JSON encoding per-section allows CI to parse individual sections with standard tooling (`jq .results.config | jq -r . | jq .`). Keeping each collector as a separate method makes them independently testable. Collectors need direct access to `self.model`, `self.unit`, `self.config`, so they belong on the charm class rather than in a separate module.

**Graceful degradation**: Each collector wraps its logic in try/except, returning `{"status": "unavailable", "reason": "<error>"}` on failure. The action handler never fails due to a subsystem error. Container disconnection, missing storage, or absent secrets return partial data rather than failing the action.

**Truncation**: If total serialized payload exceeds 250KB, the largest section (typically event-ledger) is truncated and its `truncated` flag set to true.

**Alternatives considered**:
- Single JSON blob as one result key: Simpler but harder to extract individual sections.
- Separate `introspection.py` module: Would require passing the charm model/unit objects, adding coupling without benefit.
- Fail action if any section fails: Less informative for CI — knowing *why* a section is unavailable is valuable.

---

## R7: Subordinate Charm Overlay Strategy (US25)

**Decision**: Reuse the same juju-norma-k8s charm source packed with a different
charmcraft overlay (`charmcraft-subordinate.yaml`) that adds `subordinate: true`
and flips the `juju-info` endpoint from provides to requires with
`scope: container`.

**Rationale**: Avoids maintaining a separate charm codebase. Same code, same
actions, same logic — different packaging. The subordinate variant shares the
principal's pod and Pebble environment. CI packs both variants from the same
source tree.

**Key findings**:

- **`scope: container`** is a requires-side attribute only. The principal's
  `juju-info` provides endpoint does NOT specify scope.
- **Subordinate packaging**: A subordinate charm cannot declare `containers`,
  `resources`, or `storage` — it shares the principal's pod.
- **Build approach**: Either use `charmcraft pack -c charmcraft-subordinate.yaml`
  if supported, or copy the overlay as `charmcraft.yaml` in a temp directory.
- **Principal changes**: Only needs `juju-info` provides endpoint added to
  `charmcraft.yaml` (FR-027). No code changes required.

### Overlay Delta

```yaml
# charmcraft-subordinate.yaml — only fields that differ from principal
subordinate: true

provides:
  # Remove juju-info from provides
  calibration-provider: ...
  metrics-endpoint: ...
  grafana-dashboard: ...

requires:
  juju-info:
    interface: juju-info
    scope: container
  calibration-requirer: ...
  log-proxy: ...

# Omit: containers, resources, storage (subordinates share principal's pod)
```

---

## R8: K8s Storage CLI Limitations

**Decision**: Write integration tests for `juju attach-storage`, `juju
import-filesystem`, and `juju deploy --attach-storage` with
`@pytest.mark.xfail(strict=False)` markers.

**Rationale**: These are real Juju capabilities that should work on K8s container
models. Tests document expected behavior and auto-detect when Juju adds support,
without blocking CI.

**Key findings**:

- `juju storage` / `juju list-storage`: "not yet available in 4.0.2"
- `juju add-storage` / `juju detach-storage`: "not supported on container models"
- `juju import-filesystem`: Not available for K8s container models
- `juju deploy --attach-storage`: Not available for K8s container models
- These limitations apply to both Juju 3.6 and 4.x on K8s
- The storage API works correctly for initial attachment and pod rescheduling

---

## R9: charm-user Variants (FR-031)

**Decision**: Test both `non-root` (primary) and `sudoer` (variant) execution
modes via CI build matrix using separate charmcraft overlay files.

**Rationale**: Juju supports three charm-user modes: root (default), non-root
(UID 170), and sudoer (UID 171 with sudo). The calibration charm must validate
all modes used by K8s charms.

**Key findings**:

- `charm-user: non-root` sets UID 170, no sudo access
- `charm-user: sudoer` sets UID 171, has sudo access via PAM
- `charm-user` is a build-time setting in charmcraft.yaml, not runtime-configurable
- The primary charm uses `non-root` per Constitution IV
- The sudoer variant is a CI-only build artifact (`charmcraft-sudoer.yaml`)

---

## R10: Juju K8s Coverage Audit (FR-033 through FR-037)

**Decision**: Add 5 new FRs to close gaps identified by a multi-source coverage audit
comparing our spec against Juju test charms, Juju source code, Juju documentation,
and Discourse community patterns.

**Methodology**: 4 research agents analyzed in parallel:
1. Juju test charms (`testcharms/` in juju repo) — 17 K8s charms mapped
2. Juju documentation (documentation.ubuntu.com/juju/latest/) — all K8s hooks, tools, operations
3. Juju source code (hook tools, CAAS provider, API facades) — all jujuc commands
4. Discourse (discourse.charmhub.io) — community patterns and edge cases

**Findings**: Our spec covers ~90% of Juju's K8s charm surface (100% of test charms,
100% of active events, 100% of Pebble ops). Gaps were in Juju CLI operations ON
the charm rather than charm internal capabilities.

**Gaps closed**:

| Gap | FR | Description |
|-----|-----|-------------|
| `juju expose`/`unexpose` | FR-033 | K8s creates LoadBalancer/NodePort service |
| Model migration | FR-034 | `juju migrate` preserving charm state between controllers |
| `goal-state` hook tool | FR-035 | Planned model state (units, relations) in introspect |
| `update-status-hook-interval` | FR-036 | Model-config affecting hook dispatch frequency |
| `juju ssh` + constraints | FR-037 | K8s exec-via-API path + resource requests/limits |

**Gaps deferred (LOW severity)**:
- `--bind` / network spaces (niche on K8s)
- Init containers (very new feature, rarely used)
- Payloads (`payload-*` tools, deprecated)

**Key insight**: The audit scope is "everything Juju can do WITH a K8s charm" —
not just what the charm does internally, but every `juju` CLI operation that
targets a K8s charm. This broader framing caught gaps in expose, migrate, ssh,
constraints, and model-config that a charm-centric view would miss.

---

## Summary of All NEEDS CLARIFICATION Resolved

| Item | Resolution |
|------|-----------|
| Go binary architecture | Single-file, Go 1.22+, prometheus/client_golang |
| Go binary endpoints | 5 endpoints with health toggle (atomic + flag file) |
| ROCK image design | `base: bare`, static binary only, no libc/ca-certs |
| Self-relation mechanism | Two instances of same charm with matching interface (Juju 4 limitation) |
| Secret config type | `type: secret`, resolve with `model.get_secret()` |
| COS library versions | prometheus_scrape v0, grafana_dashboard v0, loki_push_api v1 |
| Introspect action format | Per-section JSON strings in action results, private collector methods |
| Subordinate strategy | Overlay charmcraft-subordinate.yaml, same source, no separate codebase |
| K8s storage CLI | xfail(strict=False) for attach-storage, import-filesystem, deploy --attach-storage |
| charm-user variants | CI build matrix: non-root (primary) + sudoer (overlay) |
| Juju K8s coverage gaps | 5 new FRs: expose/unexpose, model migration, goal-state, update-status-interval, ssh+constraints |
