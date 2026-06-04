# juju-norma-k8s :: Juju-4.0 K8s feature-coverage + CI/CD audit

> Fresh-eyes audit before plugging this charm into Juju's own CI as a regression
> calibration standard. Multi-agent workflow (`wf_19562344-899`, 462 sub-agents,
> 14.8M tokens): per-dimension **Catalog** (Juju-4.0 K8s feature surface from
> primary source `/data/dev/juju@4.0` + ops 3.5.2 + 4.0-verified SYNTHESIS) →
> **Audit** (our actual code/test/spec coverage, evidenced) → **Verify** (each
> candidate gap double-checked: repo-refutation lens + is-it-a-real-4.0-feature
> lens). Plus 6-area CI/CD review and 2 independent blind-spot critics.
> Date: 2026-06-01. ops at audit time: 3.5.2.

## Verification status: COMPLETE (212/212 candidate gaps adjudicated)

All 212 MISSING/PARTIAL audit items now carry a definitive verdict, across 3
verification rounds (rate-limiting forced the latter two; see method note):

| Round | Method | Resolved | Confirmed REAL_GAP |
|---|---|---|---|
| 1 — main run | 2 independent adversarial lenses, 16-wide | 116 | 20 |
| 2 — re-verify | 2 lenses, 16-wide (still throttled) | +36 | +5 |
| 3 — consolidated | batched, 9 agents (low-burst, **0 failures**) | +60 | +32 |
| **Total** | — | **212** | **57** |

**57 confirmed real gaps** (5 high / 44 medium / 8 low); 155 candidates were
refuted (covered elsewhere, not a real/applicable 4.0 feature, or
partial/not-CI-relevant). Rounds 1–2 used two *independent* adversarial lenses
(repo-refutation + is-it-a-real-4.0-feature) and require both to vote REAL_GAP →
the 25 from those rounds are the highest-rigor. Round 3 used one consolidated
agent per batch doing *both* checks internally — rigorous, but single-pass; its
32 are tagged `cons` below and warrant a spot re-check before acting on the
borderline ones.

## Headline verdict: NOT yet ready to plug into Juju CI

Two systemic blockers, not the feature list, are the real problem:

1. **The 18 integration suites never run automatically.** `ci.yaml:98` gates the
   `integration` job behind `if: github.event_name == 'workflow_dispatch'`. They
   run on **zero** automatic events (not on PR, not on push, not on schedule).
   Constitution-VIII live-CLI acceptance is therefore **manual-only and
   unauditable**. A calibration charm whose tests never run calibrates nothing —
   this is the same class of problem the machine sibling has, and it dominates
   everything below.
2. ~~**The charm revision is not bound to a workload-image revision, and nothing
   reaches `latest/stable`.**~~ **CORRECTED 2026-06-04 — this BLOCKER was wrong.**
   Verified live + against Juju 4.0 source: each charm revision *is* bound to a
   **numbered, immutable** OCI resource revision (stable charm rev 11 ↔
   `juju-norma-image` rev 4; **11** numbered revisions exist), the charm *is* on
   `latest/stable`, and `juju deploy --channel/--revision` resolves the **stored
   hash-addressed** resource — it does **not** re-pull the mutable `:latest` at
   deploy time (`domain/resource/service/resource.go:555`,
   `internal/worker/caasapplicationprovisioner/ops.go:916-940`,
   `internal/provider/kubernetes/application/application.go:1879`). So deploys
   *are* reproducible per revision. The genuine residue is smaller and **not** a
   blocker: (R1) the mutable `:latest` `upstream-source` is a *build-time*
   causal-binding risk under concurrent pushes → REMEDIATION P4-2; (R2) the
   workload reports a static `VERSION=0.1.0` for every image rev so resource
   revisions aren't *runtime-distinguishable* — the actual gate for replacing
   `juju-qa-container-resource` → REMEDIATION P4-5 (elevated P1); (R3)
   stable/candidate lag edge with no automated promotion cadence → P4-6. See
   REMEDIATION-PLAN.md P0-2 (resolved/rescoped) for the full evidence trail.

**Through-line for Part A:** the charm's *implementation* surface is broad and
constitution-clean. The deficit is almost entirely in **automated verification**:
features that are *wired but never asserted on a live K8s* provide ~zero
regression-detection value, which is the only value this charm has.

## Coverage matrix (467 catalogued 4.0-K8s features across 15 dimensions)

| Bucket | Count | % of all | % of *applicable*¹ |
|---|---|---|---|
| COVERED | 184 | 39% | 46% |
| PARTIAL | 101 | 22% | 26% |
| MISSING | 111 | 24% | 28% |
| BLOCKED_JUJU (real feature, Juju can't do it on K8s) | 11 | 2% | — |
| NA_K8S (machine-only / removed / k8s-unsupported) | 60 | 13% | — |

¹ applicable = excludes NA_K8S + BLOCKED_JUJU (= 396 features).

**Read it right:** the catalog was deliberately *exhaustive* (ultracode), so
"28% missing" includes a long low-CI-relevance tail (vault secret backend,
`debug-log` flags, user-secret `#base64`/`#file` encodings…). The charm is **not
46% done** — its code is strong. The actionable signal is the **57 confirmed
gaps** + critic blind-spots + the systemic blockers, not the raw ratio. But the
ratio does say plainly: **fewer than half of the testable 4.0-K8s features are
actually verified.**

Per-dimension density (COVERED / PARTIAL / MISSING / BLOCKED / NA):

| Dimension | C | P | M | B | NA | worst gaps |
|---|--|--|--|--|--|---|
| lifecycle-hooks | 19 | 3 | 1 | 1 | 4 | `start` re-emit unverified; `leader-settings-changed` dead wiring |
| pebble-workload | 24 | 6 | 9 | 1 | 5 | push_path/pull_path, change-tracking API, start/stop_checks |
| containers-oci | 11 | 3 | 7 | 0 | 5 | attach-resource, refresh --resource, imagePullSecret |
| storage-k8s | 7 | 4 | 7 | 5 | 6 | RWX/Shared, PVC resize (rest BLOCKED on K8s) |
| networking-expose | 8 | 6 | 8 | 0 | 4 | imperative open/close-port, extra-bindings/`juju bind` |
| secrets | 14 | 9 | 14 | 0 | 0 | peek_content, set_info, get_info, unit-owned, backends, CMR secrets |
| relations-cmr | 24 | 5 | 8 | 1 | 3 | limit enforcement, dead-relation empty read |
| config | 15 | 3 | 5 | 0 | 4 | engine reject (bad type/unknown key/bad URI); **bad-behavior-mode untested** |
| status-error-defer | 9 | 11 | 7 | 0 | 2 | error-status + `juju resolve` recovery unverified |
| security-rbac-trust | 6 | 9 | 7 | 0 | 2 | root mode, SecurityContext propagation, RBAC/SA teardown |
| observability-cos | 6 | 10 | 1 | 0 | 5 | COS data never asserted vs live consumer; LogForwarder plan unverified |
| actions-introspect | 25 | 5 | 13 | 0 | 0 | (long tail of param/result-shape assertions) |
| scaling-leadership | 12 | 14 | 7 | 0 | 4 | leader re-election live, pod-eviction identity remap |
| **model-refresh-constraints-migration** | **1** | 10 | **17** | 0 | 6 | **weakest dim** — no live refresh, constraints→podspec, migrate --dry-run |
| k8s-distinct-gaps | 3 | 3 | 0 | 2 | 10 | non-stateful deploy types, GPU/devices, constraints noop |

---

## PART A — Feature-coverage gaps

### A1. Double-lens-verified gaps (25 — highest rigor, both independent lenses agreed)

Grouped; all are real present-in-4.0 K8s features that the charm does not
actually verify. `[sev]` from the verify lenses. (Beyond the groups below, the
double-lens set also confirmed 5 more from the re-verify round: **storage** —
volumeClaimTemplates immutability on refresh, `juju storage`/`list-storage` read
path on K8s, storage-class management; **relations** — `Relation.remote_model`
(relation-model-get); **networking** — `network-get egress-subnets`.)

**Refresh / OCI resource lifecycle (the charm's stated US15/US21 — weakly tested):**
- `juju refresh` to a new charm revision — never executed live (only synthetic
  `ops.testing` upgrade_charm). [med]
- `juju attach-resource` post-deploy (US21 AC2: image swap → container restart →
  pebble-ready re-fire) — no test runs it. [med]
- `juju refresh --resource` image swap — neither image-only nor code refresh is
  executed. [med]
- private-registry `imagePullSecret` generation — never exercised (public image). [low]

**Secrets depth (owner-side is strong; everything else thin):**
- `Model.get_secret(label=…)` — only id-based resolution used. [low/med]
- `Secret.peek_content` (peek without tracking) — entirely uncovered. [med]
- `Secret.set_info` (update label/expire/rotate without new revision) — never called. [med]

**Config engine-rejection paths (charm validates values; engine rejection untested):**
- secret-config bad-URI → `NotValid`; wrong-type value → coercion reject;
  unknown option key → `InvalidApplicationConfig` — none exercised. [low–med]
- **`bad-behavior-mode` has ZERO unit/integration coverage** — the flagship
  config-as-control-plane / advisor test-bed (8 modes) is completely untested. [med]

**Status / error model (implemented, never asserted live):**
- Error (agent) status from uncaught hook (`hook-error` mode) — no test triggers it. [med]
- `juju resolve` recovery (ResolvedRetryHooks/NoHooks) after a wedge — untested. [med]

**Security / RBAC:**
- `charm-user: root` (uid/gid 0) mode — never deployed/asserted (only non-root). [med]
- workload/secondary container uid/gid → pod **SecurityContext** — only verified
  in-container (`pebble exec id`), never at the pod-spec layer; secondary never
  checked. [med]
- RBAC/ServiceAccount **teardown** on app removal — never verified (a leaked
  ClusterRoleBinding would go undetected). [med]

**Relations:**
- `limit: 1` cardinality enforcement (US7 AC6: reject 2nd integration) — declared,
  never exercised. [med]
- dead-relation empty-read on teardown (US7 AC4) — never asserted. [low/med]

**Observability:**
- Pebble log-forwarding via `LogForwarder` (Juju ≥3.4) — wired, but no test joins a
  loki relation and inspects the resulting Pebble plan `log-targets`. [med]

**Lifecycle / constraints:**
- `start` hook + CAAS pod-churn re-emission — wired+logged, no test asserts it. [low/med]
- Constraints actually translating to K8s pod resources — only CLI-acceptance +
  reachability asserted; no pod-spec inspection. [med]

### A1b. Consolidated-pass confirmed gaps (+32 — single-pass adversarial, tag `cons`)

Concentrated in the 3 dimensions the rate-limit hit hardest. These are the
charm's thinnest areas.

**model-refresh-constraints-migration (17) — the weakest dimension by far:**
- *high:* `juju refresh` (charm-code upgrade) never executed live; `upgrade-charm`
  dispatch-on-refresh; OCI resource-revision binding on refresh; `cores`
  constraint rejected-on-K8s behavior.
- *med:* `upgrade-charm` skip-after-forced-upgrade-from-error (LP#2068500);
  config-changed-follows-upgrade-charm ordering; refresh cannot add/remove
  containers (#21648); `cpu-power`→millicores; `arch`→nodeSelector;
  `tags`→node/pod/anti-pod affinity; `zones`→zone affinity; workload limits
  applied to *all* containers; `set/get-constraints` post-deploy; `--trust` at
  deploy; `start` re-fire on pod churn.
- *low:* charm-container mem coupled to `mem` constraint; `juju debug-log` on K8s.

**actions-introspect (10):** auto-injected stdout/stderr/return-code on action
*exception* (vs clean `event.fail()`); multi-unit action fan-out; `parallel: true`
trait; `execution-group` trait; `juju run --background`; `juju cancel-task`;
`juju operations`/`list-operations`; `juju show-task`/`show-operation`; *low:*
`run --wait=<dur>`; `juju actions --schema`.

**scaling-leadership (5):** *high:* leader re-election on leader-unit removal
(failover); *med:* `juju scale-application <n>`; `remove-unit
--destroy-storage`/`--dry-run` unsupported-on-K8s; unit-identity persistence
across pod recreation (provider-ID/annotation remap); *low:* scale-application
input validation.

### A2. Critic blind-spots — whole API classes absent (independent of A1)

These the dimension decomposition under-weighted; flagged by both blind-spot
critics from the ops public API and the CAAS engine respectively:

- **File-type charm resource entirely absent** — only an `oci-image` resource is
  declared. `type: file` + `resource-get` + `juju attach-resource` for a file
  resource (a whole resource class) is never exercised. *(Note: the machine
  sibling's whole workload-delivery model is a file resource — strong reuse +
  calibration argument to add one here.)*
- **`Container.push_path`/`pull_path`** (recursive directory transfer) — only
  single-file push/pull is tested.
- **Pebble change-tracking API** (`get_change`/`get_changes`/`wait_change`/
  `abort_change`) — the change-id lifecycle every mutating Pebble op returns —
  untouched.
- **`Container.start_checks`/`stop_checks`** (runtime enable/disable of named
  checks) — never called; health is toggled via a workload flag file instead.
- **Imperative `open_port`/`close_port`** + `opened-ports` mutation — charm only
  uses declarative `set_ports()`.
- **Unit-owned secrets** (`unit.add_secret`), **`Secret.get_info`/SecretInfo**
  (action hardcodes `"rotation":"monthly"` instead of reading metadata),
  **secret backends** (k8s in-cluster, vault), **cross-model secret consumption**.
- **Non-stateful CAAS deployment types** — engine supports `DeploymentStateless`
  (Deployment) and `DeploymentDaemon` (DaemonSet); charm only ever exercises
  Stateful (and the provisioner only wires Stateful — so this may be NA, but it
  isn't documented as such).
- **Constraints → pod resources / placement** (node-affinity, pod/anti-pod tags,
  zones), **GPU/Device** requests (parsed-not-applied), **`set-constraints`
  post-deploy**.
- **Tracing/profiling (4th observability pillar)** — `tracing`/`parca` entirely
  absent (a documented Complexity-Tracking exception, but worth re-confirming).
- **COS relation data never verified against a live consumer** — observability
  tests only check `is_active` + introspect; scrape-job targets, shipped alert
  rules (`norma_alerts.yaml`), and the dashboard payload are never asserted on a
  real prometheus/grafana/loki.
- **Pod-eviction identity remap** (provisioner re-annotates pod↔unit on
  recreation) — no `kubectl delete pod` disruption test.
- Goal-state read via **private** `self.model._backend._run_tool('goal-state')`
  instead of a public ops path.

### A3. Resolved against 4.0 source (was contested)

- **`pebble-custom-notice` IS dispatched on K8s in Juju 4.0 — our standing
  assumption is STALE.** Verified directly in `/data/dev/juju@4.0`:
  - `domain/deployment/charm/hooks/hooks.go:101` defines
    `PebbleCustomNotice Kind = "pebble-custom-notice"` (a first-class 4.0 hook).
  - `internal/worker/uniter/uniter.go:839` starts a `pebbleNoticer` worker
    whenever `len(u.containerNames) > 0` — i.e. for **every** sidecar charm with
    workload containers (norma-k8s has two). Not IAAS-gated.
  - `internal/worker/uniter/pebblenotices.go` `processNotice` maps
    `client.CustomNotice → container.CustomNoticeEvent` and feeds it to the
    workload event channel, which dispatches the hook.
  **Impact:** JUJU.md, MEMORY, the spec, and `test_notices.py`'s
  `xfail(strict=False)` all assert the opposite ("4.0 doesn't dispatch it"). On a
  correct 4.0 controller the test silently `XPASS`es and provides ZERO calibration
  signal, and a working feature is mis-documented as unsupported. **Action: empirically
  re-test `trigger-notice` on the live controller (4.0.6/4.0.10). If it fires →
  flip to a strict positive test and correct JUJU.md/MEMORY/spec. If it does NOT
  fire despite the wiring → that is a Juju bug worth filing (exactly this charm's
  job).** This is the single highest-value correction in the audit.
- **Constraints "silently dropped" claim — corrected.** The round-1 audit note
  cited an `application.go:198` no-op that "silently drops constraints"; the
  source lens flagged that as factually wrong (the in-tree path is more nuanced).
  Net unchanged: **pod-spec verification of constraints is a real gap** (no test
  inspects the resulting pod resources/affinity), but do not repeat the
  "application.go:198 noop" mechanism claim — re-derive it from 4.0 source if it
  matters.

---

## PART B — CI/CD review (by severity)

### Blockers
- **Integration suites never auto-run** (`ci.yaml:98` workflow_dispatch-only). No
  PR gate, no push gate, no schedule. → at minimum a `-m smoke` subset on PR
  (the code comment already promises the marker split) + a nightly/edge full run.
- **Charm-rev ↔ image-rev not bound** (`publish-edge.yaml:50-56` uploads charm,
  image attached by mutable name). → pin the resource by digest; attach
  deterministically.
- **Nothing reaches `latest/stable` automatically**, yet the upstream suites this
  charm replaces deploy from a channel. → define + automate the consumption
  contract.
- ~~**OCI resource never published to CharmHub as numbered revisions**~~ **WRONG
  (corrected 2026-06-04).** `charming-actions/upload-charm` (`upload-image:true`)
  already uploads each image as a numbered CharmHub resource revision and binds
  it to the charm rev — **11 revisions exist** (rev 1…11), so the ≥2 needed to
  replace `juju-qa-container-resource` is met. The real remaining gap is that the
  revisions aren't *runtime-distinguishable* (static `VERSION=0.1.0`) → see
  REMEDIATION P4-5 (R2). `charmcraft upload-resource` is therefore unnecessary.

### High
- **No `permissions:` block on `ci.yaml` / `rock.yaml`** — `GITHUB_TOKEN` runs with
  broad default scope on `pull_request` (untrusted code). Add `permissions:
  contents: read`.
- **`canonical/setup-lxd@main`** (mutable ref) used in 4 build/publish jobs,
  including ones holding publish capability. Pin to SHA.
- **Dependabot tracks `pip`, not `uv`** — `uv.lock` (the thing actually installed)
  is never updated. Switch to `package-ecosystem: uv`.
- **arm64 charm built then discarded** — `latest/edge` is amd64-only despite the
  multi-arch ROCK and declared arm64 platform. Publish both or drop arm64.
- **`upstream-source: …:latest`** mutable → **build-time** mis-binding risk under
  concurrent pushes (NOT a deploy-reproducibility issue — deploys use the stored
  numbered resource; see P0-2 resolution). Pin to `:main-<sha>`/digest. → P4-2.
- **No build provenance / SLSA attestation / signing** on charm or ROCK — Juju CI
  can't verify artifact origin.
- **Workload version hardcoded `0.1.0`** in ldflags (`rockcraft.yaml:66`) → every
  image reports the same version; breaks the resources-suite "which image is
  running" check.
- **Constitution-VIII acceptance not enforceable in CI** (depends on a human
  running the dispatch job).
- **No `lib-check` job** — CLAUDE.md promises `lint→unit→lib-check→pack→integration`;
  `lib-check` is absent, so vendored COS libs can drift silently.

### Medium (selected)
- No `concurrency:` groups anywhere → racing `publish-rock`→`publish-edge`
  cascades can publish CharmHub revisions out of order.
- `uv sync` (not `--frozen`/`--locked`) in CI → lockfile drift undetected.
- `CHARMHUB_TOKEN` repo-scoped, not behind a GitHub Environment with required
  reviewers; no human gate before publish.
- `release-tag` promotes edge→candidate **by name** — no guarantee the edge
  revision matches the tagged commit.
- amd64-only PR pack/build-rock/integration despite arm64 surface.
- Branch-protection script (`scripts/protect-main.sh`) sets
  `required_status_checks: null` → CI is not actually required before merge to
  main (and main triggers publish).
- microk8s/juju installed twice in CI; `mk8s` vs `microk8s` cloud-name divergence;
  OCI-deploy-race retry matches the bare substring `'not found'` (over-broad).

### Juju-CI integration readiness (the actual mission)
- **Consumption contract undefined.** Juju CI consumes charms two ways: from a
  CharmHub channel, or by packing in-tree source (`tests/includes/charmcraft.sh
  pack_charm`). We support neither cleanly — no stable pinnable channel, no
  documented vendored-source tag. Decide per-replaced-charm and document it.
- **Personal namespace** — `ghcr.io/sinanawad/…` + personal CharmHub identity bake
  a single account into a would-be Canonical CI dependency. Move to an org
  namespace or parameterize.
- **Action contract not published/versioned** — `contracts/actions-schema.yaml`
  lives only in `specs/`; Juju CI calls these actions by name/params/result-keys.
  Promote to a versioned published contract + a CI drift check vs charmcraft.yaml.
- **Test the engine-under-test, not just stable.** As a regression guard it should
  run against Juju **edge / built-from-source** (where regressions appear first),
  not only `3.6/4.0 stable`.

---

## Recommended priority order

1. **Make integration runnable + meaningful in CI** (unblocks the entire mission):
   `-m smoke` subset on PR; full matrix on push-to-main + nightly; add a **Juju
   4.0/edge (and from-source)** channel; emit `--junitxml` per channel as the
   calibration artifact; set `xfail_strict=true` so a K8s-limitation that gets
   fixed fails loudly (auto-detects when Juju lands support).
2. **Supply chain — mostly DONE; reframed (2026-06-04).** charm-rev↔numbered-image-rev
   binding and numbered OCI resource publication are **already in place** (11
   revisions; deploys reproducible per revision — see P0-2 resolution). Remaining:
   pin `upstream-source` to `:main-<sha>`/digest (build-time correctness, P4-2);
   **derive ROCK + binary version from git so image revs are runtime-distinguishable
   (P4-5, elevated — the real `container-resource` replacement gate)**; define +
   automate a stable-channel promotion cadence / in-tree consumption contract
   (P0-3/P4-6); move to an org namespace.
3. **Act on the resolved `pebble-custom-notice` finding (A3):** empirically
   re-test `trigger-notice` on the live 4.0 controller; flip the stale
   `xfail(strict=False)` to a strict positive test and correct
   JUJU.md/MEMORY/spec — or file the Juju bug if it genuinely doesn't fire.
4. **Close the high-value A1 gaps** with live assertions (start with the charm's
   own stated stories that are currently unverified: refresh/attach-resource
   US15/US21, `bad-behavior-mode`, error+`juju resolve` recovery, `limit`
   enforcement, SecurityContext + RBAC teardown, COS data vs a live consumer).
5. **Add the missing API-class coverage** from A2 that is genuinely K8s-applicable
   (file-type resource, push_path/pull_path, peek_content/set_info/get_info,
   imperative open/close-port, change-tracking API, constraints→pod-spec).
6. **CI hardening** : `permissions:` blocks, SHA-pin `@main` actions, `uv` for
   Dependabot, `uv sync --frozen`, `concurrency:` groups, real
   `required_status_checks`, provenance/signing, `lib-check` job, fix amd64-only
   publish.

## Method notes / reproducing
- Catalog/Audit/CI-CD/Critic: workflow `wf_19562344-899` (462 agents). Verify
  completed across 3 runs — `wf_19562344-899` (round 1), `wf_3dbb8be7-eaf`
  (round 2 re-verify), `wf_15d67989-662` (round 3 consolidated, 9 agents, 0
  failures). The round-3 low-burst batching (≤8 gaps/agent, 9 agents) is the
  rate-limit workaround: it collapsed 120 would-be concurrent requests to 9 and
  cleared the throttle entirely.
- All 212 candidate gaps are adjudicated; the 57 confirmed are tagged by tier
  (`doub` = 2 independent lenses; `cons` = single consolidated adversarial pass).
- Every gap carries concrete evidence (file:line / action / test) in the workflow
  results; this doc is the synthesis, not the raw data.
