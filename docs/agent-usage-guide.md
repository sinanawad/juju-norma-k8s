# juju-norma-k8s — Usage Guide for AI Agents

> **Audience:** AI coding agents (Claude Code sessions and similar) that need to
> deploy and drive this charm on a Juju Kubernetes model. Every command,
> parameter name, and result key below was extracted from the charm source
> (`charmcraft.yaml`, `src/charm.py`, `src/norma.py`) — not from memory. Treat
> this file as authoritative; prefer it over your priors.

## Prime directives (read first)

1. **Do not invent action names, parameters, or result keys.** The complete,
   exhaustive list is in [Actions](#actions). If something is not listed here,
   it does not exist.
2. **This is a Kubernetes (CAAS) charm.** It only deploys to a K8s cloud
   (`assumes: [juju >= 3.6, k8s-api]`). It will *not* deploy to a machine/LXD
   model. Don't suggest `--to` placement, machines, or `juju add-machine`.
3. **The application name defaults to `juju-norma-k8s`.** The leader unit is
   `juju-norma-k8s/0`. Examples below use that; substitute if you deployed under
   a different application name.
4. **Action results are always a flat map of strings.** Numbers, booleans, and
   structured data are stringified. Fields documented as "JSON" are
   JSON-encoded strings you must parse — they are not native objects.

## Verified constants (do not guess these)

| Thing | Value | Source |
|---|---|---|
| Application name | `juju-norma-k8s` | charmcraft.yaml `name` |
| Workload container | `norma` | norma.py `CONTAINER_NAME` |
| Second container | `norma-secondary` | norma.py `SECONDARY_CONTAINER` |
| Default workload port | `8080` (from `calibration-int`) | norma.py `DEFAULT_PORT` |
| Workload binary path | `/bin/norma` | norma.py `BINARY_PATH` |
| `data` storage mount | `/var/lib/norma` | charmcraft.yaml |
| `logs` storage mount | `/var/log/norma` | charmcraft.yaml |
| OCI image | `ghcr.io/sinanawad/juju-norma:latest` (multi-arch) | charmcraft.yaml |
| OCI resource name | `juju-norma-image` | charmcraft.yaml |
| Container UID/GID | `584792` (`_daemon_`) | charmcraft.yaml |

## Deploy

### From CharmHub (published)

```bash
# Edge (latest development revision; what Juju CI consumes)
juju deploy juju-norma-k8s --channel=latest/edge --trust

# Stable
juju deploy juju-norma-k8s --channel=latest/stable --trust
```

### From a local .charm (development)

```bash
juju deploy ./juju-norma-k8s_amd64.charm \
    --resource juju-norma-image=ghcr.io/sinanawad/juju-norma:latest \
    --trust
```

**On `--trust`:** Optional, but recommended. Without it the charm still works;
the `check-security` action just reports `trust-available: false` and cannot
reach the K8s API. With it, the full security/credential surface is exercised.

**Deploy race (Juju 4.0.x, local charms with OCI resources):** A known
server-side bug (juju/juju#21456) can fail the first `juju deploy` with
`resource "juju-norma-image" ... not found`. If that happens, **retry the same
command after ~5 seconds** — it almost always succeeds on the second attempt.
Do not treat the first failure as fatal.

### Wait for it to settle

```bash
juju status --watch 2s
# Healthy steady state: juju-norma-k8s active/idle, no status message.
```

The charm follows the holistic-reconciler pattern and reports `ActiveStatus`
with **no message** when healthy. An active unit *with* a message means a
`bad-behavior-mode` is set (see [Test-bed modes](#test-bed-bad-behavior-mode)).

## Running actions — syntax that prevents hallucination

This charm targets Juju 3.6 and Juju 4.x. Use `juju run` (NOT the Juju-2.9-era
`juju run-action`):

```bash
juju run juju-norma-k8s/0 <action-name> [<key>=<value> ...]
```

- **Action and parameter names use hyphens**, e.g. `get-event-log`,
  `event-filter`. Never underscores.
- **Parameters are `key=value` positional pairs.** Do **not** use `--params`
  (that was removed/changed in Juju 4) and do **not** prefix params with `--`.
- Add `--format=json` for machine-parseable output, `--wait=60s` to bound the
  wait.

```bash
# Correct
juju run juju-norma-k8s/0 get-event-log limit=5 event-filter=config --format=json

# WRONG — do not do these
juju run juju-norma-k8s/0 get_event_log --limit 5        # underscores + flags
juju run juju-norma-k8s/0 get-event-log --params p.yaml  # --params is gone
```

## Actions

Exhaustive list (18 actions). "Returns" lists the exact result keys.

### Inspection / read-only

| Action | Params (default) | Returns (keys) |
|---|---|---|
| `get-event-log` | `limit` int (0=all), `event-filter` str ("") | `events` (JSON array), `count`, `unit` |
| `get-config` | — | `calibration-string`, `calibration-int`, `calibration-float`, `calibration-bool`, `calibration-secret` (`"set"`/`"unset"`) |
| `get-cluster-info` | — | `unit-count`, `planned-units`, `leader`, `is-leader`, `units` (JSON array) |
| `get-peer-data` | — | `app-data` (JSON), `unit-data` (JSON) |
| `get-relation-data` | `endpoint` str **(required)**, `relation-id` int (optional) | `relations` (JSON array of `{id, app-data, units}`) |
| `get-secret-info` | — | `secret-id`, `has-content` (`true`/`false`), `rotation` |
| `get-version` | — | `charm-version`, `workload-version` |
| `test-networking` | — | `opened-ports` (JSON), `bindings` (JSON), `exposed` (always `"unknown"`) |
| `check-security` | — | `charm-uid`, `charm-gid`, `workload-uid`, `workload-gid`, `trust-available`, `cloud-type`, `credential-endpoint`, `credential-auth-type`, `k8s-api-reachable` |
| `check-storage` | `name` str (`data`) | `attached`, `mount-point`, `marker-exists`, `marker-content`, `writable`. **Fails** if `name` is not `data` or `logs`. |
| `introspect` | `sections` csv str ("") | `timestamp`, `unit`, plus one JSON-encoded key per section (see below) |

`introspect` sections (when `sections` is empty, all are returned):
`identity`, `version`, `leadership`, `config`, `event-ledger`, `relations`,
`storage`, `containers`, `secrets`, `goal-state`. Filter example:
`juju run juju-norma-k8s/0 introspect sections=config,leadership`.

### Mutating / behavioral

| Action | Params (default) | Returns / effect |
|---|---|---|
| `set-status` | `status` str **(required:** `active`/`blocked`/`waiting`/`maintenance`**)**, `message` str ("") | `previous-status`, `new-status`. **Fails** on unknown status. `active` clears any forced status (active carries no message). |
| `toggle-health` | `container` str (`norma`) | `previous-state`, `new-state` (`healthy`/`unhealthy`). Flips the workload health endpoint by creating/removing `/var/lib/norma/norma-unhealthy`. |
| `test-defer` | `arm` bool (`true`) | `deferral-armed`, `previous-state`. Arms event deferral for the next eligible event. |
| `trigger-notice` | `key` str (`norma.dev/calibration-test`), `data` JSON-object str (`{}`) | `notice-sent`, `key`. **Fails** if `data` is not a valid JSON object. |
| `test-pebble-ops` | `container` str (`norma`) | One `pass`/`fail: <reason>` key per op (`push`, `pull`, `make-dir`, `list-files`, `exec`, `exec-fail`, `remove-path`, `exists`, `stop`, `get-services`, `start`, `restart`, `get-plan`, `send-signal`) + `summary` (`"N/M passed"`) |
| `run-check` | `check` str **(required)** | `check`, `result` (`pass`/`fail`), `details`. Only `check=pebble` is implemented; any other value returns `fail`. |
| `fail-action` | `message` str ("Intentional failure for testing") | **Always fails** with the message. This is intentional — it tests Juju's action-failure reporting. A non-zero exit here is success. |

### Examples

```bash
# Read the last 10 lifecycle events as JSON
juju run juju-norma-k8s/0 get-event-log limit=10 --format=json

# Force a blocked status with a message
juju run juju-norma-k8s/0 set-status status=blocked message="testing block"
# Clear it (active carries no message)
juju run juju-norma-k8s/0 set-status status=active

# Run the full Pebble operations suite against the secondary container
juju run juju-norma-k8s/0 test-pebble-ops container=norma-secondary

# Send a custom Pebble notice with a payload
juju run juju-norma-k8s/0 trigger-notice key=norma.dev/test data='{"source":"agent"}'

# Full state dump
juju run juju-norma-k8s/0 introspect --format=json
```

## Configuration

```bash
# Set
juju config juju-norma-k8s calibration-string="hello"
juju config juju-norma-k8s calibration-int=9090

# Read one option / all options
juju config juju-norma-k8s calibration-string
juju config juju-norma-k8s
```

| Option | Type | Default | Notes |
|---|---|---|---|
| `calibration-string` | string | `default` | — |
| `calibration-int` | int | `8080` | Also the workload listen port |
| `calibration-float` | float | `1.0` | — |
| `calibration-bool` | boolean | `true` | — |
| `calibration-secret` | secret | (unset) | Takes a Juju **user-secret URI**, see below |
| `bad-behavior-mode` | string | `none` | Test-bed; see dedicated section |

### Setting the secret-typed option (`calibration-secret`)

This is a `secret`-typed config option, so it takes a secret **URI**, not a
raw value. The charm resolves it via `model.get_secret(id=...)`:

```bash
# 1. Create a user secret. This prints the secret URI (e.g. "secret:d1a2b3c4...").
juju add-secret norma-cal-secret password=s3cr3t

# 2. Grant the application access to it.
juju grant-secret norma-cal-secret juju-norma-k8s

# 3. Point the config option at the URI from step 1.
juju config juju-norma-k8s calibration-secret=secret:d1a2b3c4...

# 4. Verify resolution worked — calibration-secret should read "set".
juju run juju-norma-k8s/0 get-config
```

## Relations (integrations)

| Endpoint | Role | Interface | Limit |
|---|---|---|---|
| `norma-peers` | peer | `norma_peers` | — |
| `calibration-provider` | provides | `calibration` | — |
| `calibration-requirer` | requires | `calibration` | 1 |
| `metrics-endpoint` | provides | `prometheus_scrape` | — |
| `grafana-dashboard` | provides | `grafana_dashboard` | — |
| `juju-info` | provides | `juju-info` | — |
| `log-proxy` | requires | `loki_push_api` | 1 |

> **The list above is exhaustive.** This charm intentionally has **no**
> `tls-certificates` relation and **no** profiling (`parca_scrape`/`tracing`)
> relation — those are documented exceptions, not omissions to fix. Do not try
> to `juju integrate` against endpoints that aren't in this table.

### Self-relation (calibration interface)

`calibration-provider` and `calibration-requirer` share the `calibration`
interface, so two instances of this charm can be related to each other:

```bash
juju deploy juju-norma-k8s norma-a --channel=latest/edge --trust
juju deploy juju-norma-k8s norma-b --channel=latest/edge --trust
juju integrate norma-a:calibration-provider norma-b:calibration-requirer
```

### COS observability

```bash
juju integrate juju-norma-k8s:metrics-endpoint prometheus
juju integrate juju-norma-k8s:grafana-dashboard grafana
juju integrate juju-norma-k8s:log-proxy loki
```

## Storage

Two filesystem storages. `data` is required (always present); `logs` is
optional (`multiple-range: 0-1`, so 0 or 1 instances).

```bash
# Deploy with explicit sizes (optional — defaults are 1G / 512M)
juju deploy juju-norma-k8s --channel=latest/edge --trust \
    --storage data=1G --storage logs=512M

# Verify a storage's mount + data integrity
juju run juju-norma-k8s/0 check-storage name=data
juju run juju-norma-k8s/0 check-storage name=logs
```

> **Juju 4.0 caveat:** `juju storage` / `juju list-storage` and dynamic
> `add-storage` / `detach-storage` on container models were reported "not yet
> available" / "not supported" on early 4.0.x. Use the `check-storage` action
> to inspect storage rather than `juju storage` if the latter errors.

## Test-bed (`bad-behavior-mode`)

This charm can deliberately misbehave to validate detection tooling
(`juju advisor`). Default `none` = compliant. Full per-mode reference,
including recovery steps, lives in
[BEHAVIOR-MODES.md](BEHAVIOR-MODES.md). Quick reference:

| Mode | Effect |
|---|---|
| `none` | Compliant baseline (default) |
| `active-with-message` | ActiveStatus with a (non-conventional) message |
| `blocked-no-message` | BlockedStatus with empty message |
| `stuck-maintenance` | MaintenanceStatus held indefinitely |
| `status-churn` | Flips active/waiting every reconcile |
| `hook-error` | Raises in `_reconcile` → unit goes to `error` |
| `secret-in-relation` | Leader writes a plaintext password to relation data |
| `stuck-dying` | First teardown hook raises → unit wedges in `Dying` |

```bash
juju config juju-norma-k8s bad-behavior-mode=hook-error
# Recover from hook-error / stuck-dying:
juju config juju-norma-k8s bad-behavior-mode=none
juju resolve juju-norma-k8s/0   # retry the failed hook
```

> **`hook-error` and `stuck-dying` intentionally break the unit.** This is
> expected. Recovery always requires setting the mode back to `none` AND
> running `juju resolve`. For `stuck-dying`, after resolving you can then
> `juju remove-application` normally.

## Scaling

```bash
juju deploy juju-norma-k8s -n 3 --channel=latest/edge --trust   # 3 units at deploy
juju scale-application juju-norma-k8s 3                          # scale existing
juju run juju-norma-k8s/0 get-cluster-info                       # inspect membership
```

For K8s charms, scale with `juju scale-application` (NOT `juju add-unit`, which
is the machine-model verb). Assert on `planned-units` from `get-cluster-info`
when waiting for a scale operation to converge.

## Debugging into the pod

The workload runs in a chiselled (distroless) ROCK. It has a `/bin/sh`
(busybox) for basic shell, but no package manager and minimal utilities.

```bash
# Exec into the charm (ops) container — most tooling lives here
juju ssh --container charm juju-norma-k8s/0

# Exec into the workload container (minimal; busybox sh only)
juju ssh --container norma juju-norma-k8s/0
```

> **Juju 3.6.19+ caveat:** `juju ssh <unit> <command>` no longer allocates a
> PTY by default. For interactive shells (`sh`, `bash`), add `--pty=true`.

## Teardown

```bash
# Juju 4.x: destroy-model has NO -y flag and NO --model flag; name is positional
juju destroy-model <model-name> --no-prompt --destroy-storage

# Remove just the application
juju remove-application juju-norma-k8s --destroy-storage
```

> If a unit is wedged in `Dying` (e.g. from `stuck-dying` mode), set
> `bad-behavior-mode=none`, `juju resolve` the unit, then remove. Avoid
> `--force` unless you have confirmed there is no other recovery path.

## Version-specific gotchas (anti-hallucination)

| Topic | Juju 3.6 | Juju 4.0 |
|---|---|---|
| Run action | `juju run unit/0 action key=val` | same |
| `juju expose` on K8s | requires `juju-external-hostname` config set first | same |
| `juju storage` | works | may report "not yet available" on early 4.0.x |
| `destroy-model` flags | `-y` accepted | **no `-y`**, use `--no-prompt`; name positional only |
| `pebble-custom-notice` event | not dispatched by the agent | not dispatched either — `trigger-notice` sends the notice but no charm event fires (known limitation on both) |
| `juju ssh unit cmd` PTY | none since 3.6.19 (use `--pty=true`) | none (use `--pty=true`) |

## Where the truth lives (if this doc and reality disagree)

- Action/config/relation definitions: `charmcraft.yaml`
- Action behavior and result keys: `src/charm.py` (`_on_*_action` methods)
- Workload constants (paths, ports, container names): `src/norma.py`
- Test-bed mode semantics: `docs/BEHAVIOR-MODES.md`

If you observe behavior that contradicts this guide, trust the running system
and the source files over this document, and flag the discrepancy.
