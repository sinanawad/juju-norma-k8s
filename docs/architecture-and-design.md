# Architecture & Design — for Agents Building a New K8s Charm

> **Audience:** an AI coding agent tasked with building a *new* Juju Kubernetes
> charm. This document explains the **architecture and the reasoning behind it**
> so you make the same good decisions on a fresh charm. It is the "why" layer.
> For the "how" (file contents, copy-paste code, step-by-step), follow the links
> into `docs/reference/`.
>
> **How to use this doc:** read it top to bottom once to build the mental model,
> then jump to `scaffold.md` to start, and pull in `patterns.md` per feature.
> Every principle here is enforced in this repo's constitution
> (`.specify/memory/constitution.md`) — treat that file as the normative source
> if anything conflicts.

> ⚠️ **Read this before you copy any code from this repo.** `juju-norma-k8s` is
> a **calibration / test harness**, not a plain production charm. Its *purpose*
> is to exercise Juju features — including the ones you should normally avoid.
> It therefore **deliberately contains anti-patterns** and **omits two
> normally-mandatory integrations**, all documented as justified exceptions
> below. The principles in §1–§9 are the rules for a *new production charm*
> (your charm). Where this repo deviates, it is flagged inline as
> **[EXCEPTION Ex-N]** and explained in
> [§E — This implementation's exceptions](#e-this-implementations-exceptions-and-how-to-challenge-them).
> The **compliant baseline** (`bad-behavior-mode=none`, the straight reconcile
> path, `ActiveStatus()` with no message) is the part to learn from; the gated
> deviations are counter-examples.

---

## E. This implementation's exceptions (and how to challenge them)

These are the documented, justified ways `juju-norma-k8s` departs from the
principles below. Source of truth: the constitution-compliance gate in
`specs/001-calibration-charm/plan.md` (§"Complexity Tracking"). Each exception
lists a **Revisit-when** trigger — if that condition becomes true, a future
agent should re-open the decision rather than treating the exception as
permanent. **Challenge these freely**: an exception is a deferred decision, not
a law.

| ID | Principle deviated | What the rule says | What this charm does instead | Why (justification) | Revisit when |
|---|---|---|---|---|---|
| **Ex-1** | IV — Security-First | TLS MUST be supported via the `tls-certificates` relation | No `tls-certificates` relation or code at all | TLS is orthogonal to the Juju primitives being calibrated; the `tls-certificates` interface is just a standard relation already exercised by other endpoints. Adding it would grow deploy complexity without testing a new Juju mechanism. | The charm gains a real networked endpoint that must be encrypted, or testing `tls-certificates` relation handling itself becomes part of the calibration mission. |
| **Ex-2** | V — Observable by Design | COS integration MUST include profiling (`parca_scrape` or `tracing`) | Integrates metrics + dashboards + logs only (`prometheus_scrape`, `grafana_dashboard`, `loki_push_api`); no profiling/tracing | Profiling/tracing charm libs were not yet stable; a tracing backend is not part of a standard COS deploy. Adding it risked test flakiness without exercising a novel Juju mechanism. | The tracing/parca charm libraries stabilize and a tracing backend ships in standard COS — then wire `tracing` and drop this exception. |
| **Ex-3** | VII — Simplicity & Idempotency | `event.defer()` MUST NOT be used as control flow | Uses `event.defer()` — but only inside `_on_defer_gate` (`src/charm.py:170-189`), never inside `_reconcile()`, and only when armed by the `test-defer` action | The charm's job includes validating Juju's defer/re-emit mechanism. The gate quarantines `defer()` so the reconciler stays pure; a normal charm would route events straight to `_reconcile()` with no gate. | Permanent for *this* charm (it's the point). Challenge only if the deferral-testing user story (US20) is dropped — then delete the gate and route directly to `_reconcile()`. |
| **Ex-4** | IV — Security-First | `charm-user: non-root` (the primary artifact) | Ships a second build artifact `charmcraft-sudoer.yaml` with `charm-user: sudoer` (FR-031) | The calibration mission must validate *all* Juju K8s privilege modes, including `sudoer`. The sudoer variant is CI-only and never published to CharmHub; the default/published charm is always `non-root`. | Juju removes or changes the `sudoer` charm-user mode, or the sudoer test is moved elsewhere. |

### Deliberate anti-patterns (test instruments — NOT exceptions, NOT templates)

Separate from the constitutional exceptions above, the charm can be *configured*
to misbehave via `bad-behavior-mode` (default `none` = compliant). These exist
to give detection tooling (`juju advisor`) a target. They are **counter-examples
on purpose** — never copy them into a real charm:

- `active-with-message` → `ActiveStatus` with a message (`src/charm.py:482`) — violates "active carries no message"
- `blocked-no-message` → `BlockedStatus("")` (`src/charm.py:488`) — violates "blocked must be actionable"
- `stuck-maintenance`, `status-churn` → status-stability violations
- `hook-error` → uncaught exception in reconcile
- `secret-in-relation` → plaintext secret in relation data
- `stuck-dying` → teardown hook raises, wedging the unit in `Dying`

Full reference: [`BEHAVIOR-MODES.md`](BEHAVIOR-MODES.md). The compliant code path
(`bad-behavior-mode=none`) is what §1–§9 describe and what you should emulate.

---

## 0. The mental model: a charm is a control plane, not the workload

A Juju charm is an **operator**: a small Python program that reacts to events
and drives a workload toward a desired state. On Kubernetes specifically:

```
        Juju controller
              │  dispatches events (install, config-changed, relation-*, …)
              ▼
   ┌─────────────────────────┐         ┌──────────────────────────┐
   │  charm container        │ Pebble  │  workload container(s)   │
   │  (your operator code,   │────────▶│  (the actual service —   │
   │   src/charm.py via ops) │  API    │   here: the Go binary)   │
   └─────────────────────────┘         └──────────────────────────┘
```

Two ideas follow immediately and shape everything else:

1. **The charm and the workload are different programs in different containers.**
   The charm talks to the workload through Pebble (a lightweight service
   manager), never by running the workload's code in-process.
2. **The charm is event-driven and stateless.** It is invoked, reacts, and
   exits. It does not run a loop. It must reconstruct everything it needs from
   the model on each invocation.

Internalize these before writing code; most charm bugs are violations of one of
them.

Background reading:
- ops (the charm framework): https://documentation.ubuntu.com/ops/
- Juju SDK / charm developer docs: https://juju.is/docs/sdk
- Pebble (workload service manager): https://documentation.ubuntu.com/pebble/

---

## 1. Holistic reconciler — one path, not N event handlers

**Decision:** every Juju event (config-changed, relation-changed, pebble-ready,
…) routes to a single `_reconcile()` method that (a) reads *all* inputs, (b)
computes the *complete* desired state, (c) writes outputs. Dedicated handlers
exist **only** for `stop`, `remove`, action events, and secret
rotation/expiration.

**Why:** Kubernetes pods are recreated, events arrive out of order, and events
are sometimes coalesced or missed. If each handler patches one slice of state,
you get combinatorial bugs ("works on config-changed but not after a pod
bounce"). A single idempotent reconciler that always converges from current
model state is immune to event ordering.

**If you ignore this:** you will write `if event.relation.name == ...` branches,
then chase state-divergence bugs that only appear after scale events or pod
restarts.

- How: `docs/reference/patterns.md` §1 (Holistic Reconciler)
- ops concept: search the ops docs for "holistic vs delta charming"

---

## 2. Two-module separation — charm logic vs workload logic

**Decision:** split the code in two:
- `src/charm.py` — Juju lifecycle, relations, status. Imports `ops`.
- `src/<workload>.py` — workload logic (Pebble layer construction, ports,
  config shaping). **Zero `ops` import.** Pure functions over primitives.

Event objects **must never** cross into the workload module. Extract the data
you need in the charm, pass strings/ints/dicts to the workload module.

**Why:** the workload module becomes testable with plain `pytest` and no Juju
mocking, and the boundary forces you to think about *what data* the workload
actually needs rather than smuggling the whole event in. It also keeps the
charm file focused on orchestration.

**If you ignore this:** your unit tests need a full Juju harness for trivial
logic, and workload changes ripple into Juju-coupled code.

- How: `docs/reference/patterns.md` §2 (Two-Module Separation)
- Constitution: Principle II (Workload Abstraction)

---

## 3. Stateless by default — no StoredState

**Decision:** never use `ops.StoredState` for persistent data. When you need to
remember something across invocations, in priority order:
1. Re-read it from the workload/environment.
2. Peer relation data (leader writes to `relation.data[self.app]`; values are
   strings — JSON-encode complex data).
3. Juju storage.
4. A database relation.

Sensitive values go in **Juju Secrets**; store the secret *ID* in peer data,
never the secret value.

**Why:** on Kubernetes the charm container is ephemeral — StoredState lives on
local disk that is lost on pod recreation. Relation data and secrets are
controller-backed and survive.

**If you ignore this:** state silently vanishes on the next pod reschedule and
you debug a "works until it doesn't" ghost.

- How: `docs/reference/patterns.md` (relation-data + secrets patterns)
- Constitution: Principle III (Stateless by Default)
- Juju secrets: https://juju.is/docs/sdk (Secrets section)

---

## 4. Status via `collect_unit_status` — never set status inline

**Decision:** compute unit/app status exclusively in `collect_unit_status` /
`collect_app_status` handlers. Never call `self.unit.status = ...` inside a
reconcile or event handler. Priority order when multiple conditions hold:
`Blocked > Maintenance > Waiting > Active`. `ActiveStatus` carries **no
message**.

**Why:** Juju fires the collect-status event at the end of every dispatch and
aggregates the results. Computing status in one place from current state means
status can never go stale or contradict itself. The "active = no message"
convention lets operators trust that any message means "needs attention".

**If you ignore this:** status flickers, lies, or shows a stale message from
three events ago.

- How: `docs/reference/patterns.md` §3 (Status Reporting via collect_unit_status)
- Constitution: Principle (Status Reporting)

> **In this repo:** the compliant path emits `ops.ActiveStatus()` with no message
> (`src/charm.py:421`). The message-bearing `ActiveStatus` and empty
> `BlockedStatus` you'll find in `_bad_behavior_unit_status()` are **deliberate
> counter-examples** gated behind `bad-behavior-mode` — see §E. Do not copy them.

---

## 5. Idempotency — every handler is safe to re-run

**Decision:** every handler must produce identical results when re-run, and must
base decisions on current model state, not on "what event am I handling".
Forbidden as control flow: `event.defer()` (the reconciler handles retry by
re-running), blocking sleeps/polls, and any "do this once" flag that isn't
derived from observable state.

**Why:** Juju re-emits events; a handler that isn't idempotent corrupts state on
the second run. EVERYTHING FAILS — design for re-entry.

- Constitution: Principle VII (Simplicity & Idempotency)

> **[EXCEPTION Ex-3] In this repo:** `event.defer()` *is* used — but only inside
> `_on_defer_gate` (`src/charm.py:170-189`), as a deliberate instrument to test
> Juju's defer/re-emit mechanism, and never inside `_reconcile()`. **Your charm
> should not have a defer-gate**; route events straight to `_reconcile()`. See §E.

---

## 6. Security-first — non-root, distroless, secrets

**Decision (all mandatory):**
- `charm-user: non-root` in `charmcraft.yaml`; set container `uid`/`gid`.
- Workload OCI image is a **chiselled ROCK** (distroless: no shell tooling, no
  package manager, minimal attack surface) built with `rockcraft`.
- Passwords via `secrets.token_urlsafe()`; secrets via Juju Secrets; TLS via the
  `tls-certificates` relation. Never hardcode sensitive data; never log it.

> **[EXCEPTION Ex-1 / Ex-4] In this repo:** there is **no** `tls-certificates`
> relation (Ex-1 — orthogonal to the calibration mission), and a CI-only
> `charm-user: sudoer` build variant exists alongside the published `non-root`
> one (Ex-4 — to test all privilege modes). Your production charm should wire
> TLS and ship a single `non-root` artifact. See §E.

**Why:** charms run with cluster credentials; a rootful, fat image with secrets
in logs is a breach waiting to happen. Distroless images also pull faster and
have far fewer CVEs.

**Gotcha you will hit:** a `base: bare` ROCK has no NSS libraries, so Pebble
can't resolve usernames — don't set `user:` in Pebble layers; set `uid`/`gid` in
`charmcraft.yaml` instead. (This repo ships a `/bin/sh` via a vendored
`busybox-static` for `juju exec`/`ssh` convenience — see `rockcraft.yaml`.)

- How: `docs/reference/patterns.md` (security + secrets), `pitfalls.md` (ROCK)
- Constitution: Principle IV (Security-First)
- Rockcraft: https://documentation.ubuntu.com/rockcraft/

---

## 7. Observable by design — wire COS from day one

**Decision:** integrate the Canonical Observability Stack via relation
endpoints: `prometheus_scrape` (metrics), `grafana_dashboard` (dashboards in
`src/grafana_dashboards/`), `loki_push_api` (logs), and `parca_scrape` or
`tracing` (profiling). Alert rules ship in `src/prometheus_alert_rules/`.

**Why:** observability bolted on later means re-plumbing the workload to expose
metrics. Declaring the relations up front (all `optional: true`) costs nothing
when COS isn't related and works instantly when it is.

- How: `docs/reference/patterns.md` (observability)
- Constitution: Principle V (Observable by Design)
- COS / charm libs are fetched from the upstream charms (prometheus-k8s,
  grafana-k8s, loki-k8s) via `charmcraft fetch-libs`.

> **[EXCEPTION Ex-2] In this repo:** profiling (`parca_scrape`/`tracing`) is
> **not** wired — only metrics, dashboards, and logs. Your charm should add
> profiling once the libraries stabilize. See §E.

---

## 8. Component & packaging architecture

Three artifacts, three tools:

| Artifact | Built by | Contains | Config file |
|---|---|---|---|
| The charm (`.charm`) | `charmcraft pack` | operator code + metadata + libs | `charmcraft.yaml` |
| The workload image (ROCK) | `rockcraft pack` | the service binary + Pebble | `rockcraft.yaml` |
| Python deps | `uv` (not pip/tox) | locked dependency tree | `pyproject.toml` + `uv.lock` |

Key conventions (this repo, enforced by constitution §"Technology Stack"):
- **`uv.lock` is committed** — reproducible builds.
- **`charmcraft.yaml` is the single source of metadata** — no separate
  `metadata.yaml`/`config.yaml`/`actions.yaml` (those are the legacy v1 layout).
- **Charm name ends in `-k8s`**; `assumes` declares `juju >= X` and `k8s-api`.
- **Declare relation cardinality explicitly.** Per charmcraft convention:
  `requires` endpoints declare `optional` and `limit` (e.g. `limit: 1`);
  `provides` endpoints declare `optional` (a provider rarely needs a `limit`);
  `peers` declare neither (`limit`/`optional` are not meaningful for peers).
  See this repo's `charmcraft.yaml` for the pattern.
- Lint/format with **ruff** only. Build orchestration in a **Makefile**, not
  `tox.ini`.

- How: `docs/reference/charm-anatomy.md` (file-by-file), `scaffold.md` (from zero)
- Charmcraft: https://canonical-charmcraft.readthedocs-hosted.com/
- Rockcraft: https://documentation.ubuntu.com/rockcraft/

---

## 9. Testing architecture — three tiers, specific tools

| Tier | Tool | What it proves | Never use |
|---|---|---|---|
| Unit | `ops[testing]` (Scenario) + plain pytest for the workload module | State-transition correctness; one event → asserted output `State` | legacy `Harness` |
| Integration | `jubilant` (`jubilant.temp_model()`, synchronous) | Real deploy on a real controller behaves | `pytest-operator` |
| CLI acceptance | live `juju run` / `juju config` / `juju status` | the user story actually works against a deployment | (none — this is mandatory) |

**Why three tiers:** unit tests are fast but can't catch bugs that only appear
across event dispatches; integration catches deploy-time reality; CLI acceptance
is the ground truth that a human/agent can reproduce. A story is **not done**
until verified at the CLI tier against a live deployment.

- How: `docs/reference/patterns.md` (testing), `scaffold.md`
- Constitution: Principles VI (Three-Tier Testing) and VIII (CLI Acceptance)
- ops testing (Scenario): https://documentation.ubuntu.com/ops/

---

## 10. Decision checklist for a new charm

Work in this order; each step links to the detailed guide.

1. **Skeleton** — minimal `charmcraft.yaml` + `src/charm.py` + workload module +
   `pyproject.toml` + `Makefile`. → `scaffold.md`
2. **Workload image** — write `rockcraft.yaml` for a chiselled ROCK; confirm the
   binary path and that Pebble can start it. → `pitfalls.md` (ROCK section)
3. **Reconciler** — single `_reconcile()`; wire all events to it. → `patterns.md` §1
4. **Two-module split** — keep `ops` out of the workload module. → `patterns.md` §2
5. **Status** — `collect_unit_status` only. → `patterns.md` §3
6. **Config & relations** — declare with `optional`/`limit`; read in the
   reconciler. → `patterns.md`
7. **State** — peer data / secrets, never StoredState. → `patterns.md`
8. **Security** — non-root, secrets, distroless. → Principle IV + `pitfalls.md`
9. **Observability** — COS relations + dashboards + alerts. → `patterns.md`
10. **Tests** — all three tiers. → `patterns.md` + Principle VIII
11. **CI/CD & publishing** — see this repo's `.github/workflows/` and
    `docs/agent-usage-guide.md` for the channel-promotion model.

---

## 11. Curated external reading (verified live)

Primary sources — prefer these over blog posts:

- **ops framework** (the API you write against):
  https://documentation.ubuntu.com/ops/ — mirror: https://ops.readthedocs.io/en/latest/
- **Juju** (the orchestrator + concepts: model, unit, relation, secret):
  https://documentation.ubuntu.com/juju/ — and https://canonical.com/juju/docs
- **Charm SDK / developer guide** (how-tos, charmcraft profiles, charm libs):
  https://juju.is/docs/sdk
- **Charmcraft** (packaging the charm): https://canonical-charmcraft.readthedocs-hosted.com/
- **Rockcraft** (building the distroless workload image):
  https://documentation.ubuntu.com/rockcraft/
- **Pebble** (managing the workload process inside the container):
  https://documentation.ubuntu.com/pebble/

In-repo normative/reference material:

- `.specify/memory/constitution.md` — the binding rules (Principles I–VIII).
- `docs/reference/charm-anatomy.md` — every file, what it's for.
- `docs/reference/patterns.md` — 18 annotated code patterns.
- `docs/reference/scaffold.md` — build a charm from zero.
- `docs/reference/pitfalls.md` — real mistakes and their fixes.
- `docs/agent-usage-guide.md` — how to *drive* this specific charm.

> If reality and any document disagree, trust (in order): the running system →
> the source files → the constitution → these docs. Then fix the doc.
