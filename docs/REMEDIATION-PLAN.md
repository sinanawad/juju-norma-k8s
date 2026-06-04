# juju-norma-k8s :: remediation action plan

Derived from `docs/COVERAGE-AUDIT.md` (2026-06-01 audit). This is the working
checklist: each item is **independently pickable**, has a clear **done-when**,
and cites the relevant files. Sorted by priority tier (P0 = blockers → P4 =
hygiene/long-tail). IDs are stable so we can say "let's do P1-2".

## How we work this list
1. Pick ONE item by ID. (Default first pick: **P0-1** — it unblocks everything.)
2. Implement the smallest change that satisfies its done-when.
3. Gate: `make lint && make unit` green.
4. Live-verify on the microk8s/Juju controller per Constitution VIII (the change
   isn't "done" until proven via the same CLI Juju CI uses).
5. Present results (AC-by-AC), get review/approval, then commit. One at a time.

Legend: severity from the audit `[H]/[M]/[L]`; `(doub)` = double-lens-verified
gap, `(cons)` = consolidated-pass gap. "AUDIT" refs point at `COVERAGE-AUDIT.md`.

---

## P0 — Blockers (Juju-CI integration is meaningless until these hold)

- [x] **P0-1 — Make the integration suite actually run in CI.**  ✅ DONE (PR #8, edge smoke green)
  - Scope: the 18 jubilant suites currently run on **zero** automatic events
    (`ci.yaml:98` gates the `integration` job to `workflow_dispatch`). Wire real
    triggers: (a) a fast `-m smoke` subset on every PR (lifecycle + one config +
    one relation), (b) the full matrix on push-to-main, (c) a nightly `schedule:`
    run, and (d) at least one **Juju `4.0/edge`** channel (the engine-under-test,
    where regressions land first), alongside the existing `3.6`/`4.0/stable`.
    Juju installs from **snap channels only** — the juju source repo is out of
    scope. Note: the OCI-deploy-race (#21456) is **NOT** a blocker here — it's
    fixed in stock 4.0.5+/4.0.6+ (verified against 4.0 source @ v4.0.10-289), so
    a stock controller deploys our local `.charm`+OCI-resource cleanly with no
    patched jujud.
  - Why: a calibration charm whose tests never run calibrates nothing. This is
    the headline blocker; it also makes Constitution-VIII enforceable instead of
    manual/honour-system.
  - Done-when: a PR shows the smoke job executing on microk8s and passing; a
    scheduled/edge run is visible in Actions; the `-m smoke` marker split the
    `ci.yaml` comment already promises is implemented.
  - Refs: AUDIT Part B (pr-gate, integration-execution); `ci.yaml`, `Makefile`,
    `tests/integration/`.
  - **STATUS 2026-06-04 — DONE + MERGED (PR #8 + #10):** dynamic matrix wired
    (smoke@`4.0/edge` on PR/push; full ×{3.6/stable,4.0/stable,4.0/edge} on
    nightly+dispatch); `smoke` marker + `make integration-smoke`. Initial harness
    bugs fixed in #8 (positional `bootstrap_controller`, channel-aware
    `install_snap`, `mk8s` cloud-name); the first real full-matrix run surfaced
    more, fixed in #10 (CMR cloud + offer-URL bare-model + consolidated to one
    cycle; expose 3.6-vs-4.0 gate; storage-CLI boundary calibration;
    `--log-cli-level=INFO` visibility). **Full matrix GREEN on all 3 channels**
    (dispatch run 26936283008: 83 passed / 5 skipped / 1 xfailed each; edge
    80-min-timeout → 14 min after the CMR `destroy-model` ×3→×1 fix). Remaining:
    edge depends on the GCP `juju-testing` registry → migrate edge publishing to
    a public `ghcr.io/juju-edge` namespace (researched) — **UPSTREAM JUJU task**,
    not this repo.

- [x] **P0-2 — Published artifact reproducibility. RESOLVED as a P0 — premise
  FALSIFIED (2026-06-04). Genuine residue refiled to P4 (none a blocker).**
  - The original premise — "two `juju deploy` a week apart pull different bytes"
    — is **false** for channel/revision-pinned CharmHub deploys. Verified live +
    at Juju 4.0 source level (adversarial 3-lens check, 2 of 3 lenses HIGH-conf
    confirm; the 3rd refuted only the distinguishability sub-point, see R2):
    - **Live state:** `juju-norma-k8s` is on `latest/{stable,candidate,edge}`.
      stable = charm rev **11** ↔ OCI resource `juju-norma-image` rev **4**;
      edge = charm rev **23** ↔ resource rev **11**. **Eleven** numbered OCI
      resource revisions exist on CharmHub (rev 1@2026-02-21 … rev 11@2026-06-02).
    - **Binding is automatic + immutable:** `canonical/charming-actions/upload-charm@2.7.0`
      defaults `upload-image:true` → pulls `upstream-source`, uploads a *new
      numbered* resource revision, releases the charm rev bound to it. CharmHub
      resource revisions are hash-addressed (SHA-256/384/512 in the `Download`
      metadata) and immutable once created.
    - **Deploy uses the stored pin, NOT the mutable tag:** Juju resolves the
      channel/revision → the *stored* numbered resource (it does **not** re-pull
      `:latest` at deploy time). Evidence: `domain/deployment/charm/repository/charmhub.go`
      `ResolveResources()`; `domain/resource/service/resource.go:555 OpenResource()`
      (returns stored immutable metadata); `internal/worker/caasapplicationprovisioner/ops.go:916-940`
      (`provisioningInfo()` opens stored resources, no re-resolution);
      `internal/provider/kubernetes/application/application.go:1879` (pod image
      spec from stored `RegistryPath`). ⇒ a fixed charm rev resolves byte-identical
      forever.
  - Original sub-items (b) "bind charm-rev → numbered image-rev" and (c) "publish
    numbered resource revisions" are therefore **already DONE** (11 of them; ≥2
    needed for the `container-resource` replacement is met 5×). The genuine
    residue splits into three already-tracked, lower-priority items:
    - **R1 → P4-2 (`[P2]`): build-time causal binding.** `upstream-source: …:latest`
      is mutable; under concurrent main pushes charm-rev-N *could* bind to a
      neighbour commit's image. PR #9 concurrency (publish-edge serialized
      cancel-in-progress:false; publish-rock per-ref cancel) **narrows** the
      window; pinning to `:main-<sha>`/digest **closes** it. This is build-time
      correctness, **not** deploy reproducibility.
    - **R2 → P4-5 (ELEVATE to `[P1]` for the replacement goal): resource-revision
      *distinguishability*.** To actually replace `juju-qa-container-resource`
      (`/data/dev/juju/tests/suites/resources/container.sh:38-48` refreshes
      `--resource app-image=3 → =4` and asserts the *running image identity
      changed*), the workload must report a **per-revision-distinct** identity.
      Today it can't: workload `VERSION` is hardcoded `0.1.0` (`rockcraft.yaml:4`
      + ldflag `-X main.version=0.1.0`), so `get-version` reports `0.1.0` for
      *every* image rev, and there is **no image-digest introspection** action.
      The 11 revisions ARE distinct digests and ARE attachable (lens-3's
      "rev 3 not deployable on stable" counterexample is wrong — any uploaded
      rev N is attachable via `juju refresh --resource …=N` regardless of
      channel); the gap is purely *runtime distinguishability*. Fix = P4-5
      (derive ROCK+binary version from git) + optionally a `get-image-digest`
      action. **This is the real gate for the container-resource replacement.**
    - **R3 → P4-6 + new cadence note (`[P2]`): stable/candidate staleness.** The
      edge→candidate (tag) → stable (manual `promote.yaml`) ladder works *when
      invoked*, but nothing invokes it on a cadence → stable is currently 12 charm
      revs / 9 days behind edge. Not a reproducibility blocker (a `--revision`
      pin bypasses it); a release-hygiene gap. The Juju-CI consumption contract
      (P0-3) must therefore say **"pin `--revision N` or use `latest/edge`"**,
      not "rely on `latest/stable` being fresh."
  - Refs: live CharmHub API + `charmcraft resource-revisions`; Juju 4.0 source
    (cited above); `charmcraft.yaml:48`, `publish-{rock,edge}.yaml`,
    `release-tag.yaml`, `promote.yaml`. Supersedes AUDIT Part B BLOCKER framing
    (corrected inline in COVERAGE-AUDIT.md).

- [ ] **P0-3 — Define & document the Juju-CI consumption contract.**
  - Scope: decide, per charm we replace, HOW Juju CI consumes this charm —
    CharmHub channel (`juju deploy --channel`) vs in-tree source pack
    (`tests/includes/charmcraft.sh pack_charm`). Provide whichever the target
    suite needs: a stable pinnable channel/revision, and/or a tagged source
    snapshot for vendoring. Write it down in `docs/` and link from README.
  - Why: "drop into Juju CI" is undefined today; we support neither path cleanly.
  - Done-when: a short contract doc exists mapping each replaced upstream charm →
    consumption method → exact pin (channel+revision or tag/commit).
  - Refs: AUDIT Part B (juju-ci-readiness); `specs/001-calibration-charm/`
    (k8s-charm-research.md, spec Assumptions).

---

## P1 — High-value, mostly cheap

- [ ] **P1-1 — Resolve the stale `pebble-custom-notice` belief. `[H-value]`**
  - Scope: the 4.0 source dispatches this hook for sidecar charms
    (`uniter.go:839` + `pebblenotices.go`). Empirically re-run `trigger-notice` on
    the live 4.0 controller. If it fires → flip `test_notices.py`'s
    `xfail(strict=False)` to a strict positive assertion and correct the
    "not dispatched" claim in JUJU.md + the spec. If it genuinely does NOT fire →
    file a Juju bug (this is exactly what the charm is for).
  - Why: our test currently `XPASS`es silently = zero signal; a working feature is
    mis-documented. Highest-value correction, low effort.
  - Done-when: a deterministic test asserts the custom-notice hook fires (or a
    filed bug + a strict xfail that will flip when fixed); docs corrected.
  - Refs: AUDIT A3; `tests/integration/test_notices.py`, `src/charm.py:970`
    (`_on_trigger_notice_action`).

- [ ] **P1-2 — CI security & determinism hardening (bundle).**
  - Scope: (a) add `permissions: contents: read` to `ci.yaml` + `rock.yaml`
    (currently broad default token on untrusted PRs); (b) SHA-pin every `uses:`
    (esp. `canonical/setup-lxd@main` in 4 publish/build jobs); (c) switch
    Dependabot Python ecosystem from `pip` → `uv` (uv.lock is never updated
    today); (d) `uv sync --frozen` in all CI jobs + a `uv lock --check`; (e) set
    real `required_status_checks` in `scripts/protect-main.sh` (CI is not actually
    required before merge, and main triggers publish).
  - Why: untrusted-PR token scope, mutable action refs, and an unenforced gate are
    real supply-chain exposure for a would-be Canonical CI dependency.
  - Done-when: PRs run with read-only token; no `@main`/floating refs remain;
    Dependabot opens `uv.lock` PRs; branch protection blocks merge on red CI.
  - Refs: AUDIT Part B (security-supplychain, workflow-correctness);
    `ci.yaml`, `rock.yaml`, `.github/dependabot.yml`, `scripts/protect-main.sh`.

- [ ] **P1-3 — Add the missing `lib-check` job.**
  - Scope: add `canonical/charming-actions/check-libraries` (pin the version) to
    `ci.yaml` on PRs, so the three vendored COS libs can't silently drift.
  - Why: CLAUDE.md declares `lint→unit→lib-check→pack→integration`; `lib-check` is
    absent, so publish jobs `fetch-libs` then pack against undeclared drift.
  - Done-when: a PR that drifts a lib fails the new job.
  - Refs: AUDIT Part B (pr-gate, workflow-correctness); `ci.yaml`, `lib/charms/`.

- [ ] **P1-4 — Publish arm64 (or formally drop it). `[H]`**
  - Scope: `charmcraft.yaml` declares amd64+arm64, the ROCK is multi-arch, but
    `latest/edge` ships an **amd64-only** charm (arm64 built then discarded).
    Either upload both platform charms (`--platform`-explicit / glob) or restrict
    `charmcraft.yaml` to amd64.
  - Why: `juju deploy --channel edge` on arm64 fails today; "multi-arch" is
    half-true.
  - Done-when: both arch charms on the channel, or arm64 removed from metadata +
    matrix.
  - Refs: AUDIT Part B (release-publish, workflow-correctness);
    `charmcraft.yaml:11`, `publish-edge.yaml`, `ci.yaml` pack job.

- [ ] **P1-5 — Make CI evidence the product: `xfail_strict` + report artifacts.**
  - Scope: set `xfail_strict = true` in `pyproject.toml`; convert
    K8s-limitation markers to `strict=True` so a fixed-by-Juju feature **fails
    loudly** (auto-detects when support lands) — directly relevant to P1-1 and
    the storage xfails. Add `--junitxml=report-<channel>.xml` per integration
    run, upload as an artifact, surface via a test-reporter.
  - Why: for a calibration charm the per-channel pass/fail record IS the
    deliverable; non-strict xfails hide both regressions and fixes.
  - Done-when: a Juju-side fix flips an xfail to a CI failure; machine-readable
    reports are attached to each run.
  - Refs: AUDIT Part B (integration-execution); `pyproject.toml`,
    `tests/integration/test_storage.py`, `Makefile`.

- [ ] **P1-6 — Supply-chain integrity: provenance + signing. `[H]`**
  - Scope: add `actions/attest-build-provenance` (with `id-token`/`attestations`
    write) for the ROCK image digest and the charm; optionally cosign. Reference
    the ROCK digest in release notes; attach `SHA256SUMS` to GitHub Releases.
  - Why: a Canonical-CI dependency should be cryptographically verifiable; nothing
    is signed/attested today.
  - Done-when: pushed image + charm carry verifiable provenance.
  - Refs: AUDIT Part B (security-supplychain, release-publish);
    `publish-rock.yaml`, `release-tag.yaml`.

---

## P2 — Close the 57 confirmed coverage gaps (live assertions)

Grouped into work-units; **HIGH-severity units first**. Each unit lists the
specific confirmed gaps it closes so nothing is lost.

- [ ] **P2-1 — Refresh & OCI-resource lifecycle suite. `[H]`**
  - Closes: live `juju refresh` to a new charm revision (H, cons); `upgrade-charm`
    dispatch + ordering on a real refresh (H/M, cons); OCI resource-revision
    binding on refresh (H, cons); `juju attach-resource` post-deploy → restart →
    pebble-ready re-fire (M, doub); `juju refresh --resource` image swap (M,
    doub); `upgrade-charm` intentionally skipped after forced-upgrade-from-error
    (LP#2068500) (M, cons); refresh-cannot-add/remove-containers #21648 (M, cons,
    as a strict xfail).
  - How: real `juju refresh`/`attach-resource` in `test_upgrade.py` /
    `test_oci_resource.py` (today they do neither); assert ledger + version +
    pebble-ready re-fire on the live model.
  - Refs: AUDIT A1/A1b; `test_upgrade.py`, `test_oci_resource.py`, `src/charm.py`
    (refresh detection ~`:226`).

- [ ] **P2-2 — Constraints → K8s pod spec (incl. the `cores`-rejection case). `[H]`**
  - Closes: constraints not asserted at pod-spec layer (M, doub); `cores`
    rejected-on-K8s (H, cons — current test wrongly expects `cores=1` to succeed);
    `cpu-power`→millicores, `arch`→nodeSelector, `tags`→affinity, `zones`→zone
    affinity, workload limits applied to ALL containers, `set/get-constraints`
    post-deploy, charm-container mem coupling (all M/L, cons).
  - How: deploy with the K8s-honoured constraints and **inspect the resulting pod
    spec via kubectl** (the suite currently asserts only `is_active`); flip the
    `cores` test to expect the precheck rejection.
  - Note: re-derive any "constraints silently dropped" mechanism from 4.0 source —
    the old `application.go:198` noop claim was flagged wrong (AUDIT A3).
  - Refs: AUDIT A1b + k8s-distinct; `test_lifecycle.py:193` (TestDeployConstraints).

- [ ] **P2-3 — Leader failover & scaling. `[H]`**
  - Closes: leader re-election on leader-unit removal (H, cons); `juju
    scale-application <n>` desired-scale (M); `remove-unit
    --destroy-storage`/`--dry-run` unsupported-on-K8s (M, as xfail); unit-identity
    persistence across pod recreation / provider-ID remap (M); scale-application
    input validation (L).
  - How: in `test_scaling.py`, scale up, `remove-unit` the leader, assert
    re-election + peer-app-data rewrite by the new leader; `kubectl delete pod`
    and assert the unit/annotation survives.
  - Refs: AUDIT A1b; `test_scaling.py`.

- [ ] **P2-4 — Config engine-rejection + the `bad-behavior-mode` test-bed. `[M]`**
  - Closes: bad-URI secret config → `NotValid`; wrong-type value rejected at set
    time; unknown option key → `InvalidApplicationConfig`; **`bad-behavior-mode`
    has ZERO test coverage** (all doub).
  - How: integration tests setting bogus configs and asserting `CLIError`; unit +
    integration coverage for each of the 8 bad-behavior modes (the flagship
    config-as-control-plane feature is entirely untested).
  - Refs: AUDIT A1; `charmcraft.yaml:81`, `src/charm.py` (bad-behavior handlers),
    `test_config.py`.

- [ ] **P2-5 — Error status + `juju resolve` recovery. `[M]`**
  - Closes: error (agent) status from uncaught hook (`hook-error` mode);
    `juju resolve` recovery (ResolvedRetryHooks/NoHooks) (both doub).
  - How: set `bad-behavior-mode=hook-error`, assert the unit reaches `agent=error`
    live; then `juju resolve` and assert recovery (the recovery path is documented
    in `charmcraft.yaml:108` but never exercised).
  - Refs: AUDIT A1; `src/charm.py:510` (`_maybe_trigger_hook_error`),
    `test_status.py`.

- [ ] **P2-6 — Security: root mode, SecurityContext, RBAC teardown, deploy `--trust`. `[M]`**
  - Closes: `charm-user: root` (uid/gid 0) variant; workload/secondary container
    uid/gid → **pod SecurityContext** (only verified in-container today); RBAC/SA
    teardown on app removal (no leak check); `--trust` at deploy time (FR-039).
  - How: a sudoer/root overlay deploy asserting uid 0; `kubectl` assertions on pod
    `SecurityContext.RunAsUser` for both containers; post-removal `kubectl` check
    that ClusterRoleBinding/SA are gone; deploy with `--trust` and assert.
  - Refs: AUDIT A1; `test_security.py`, `charmcraft.yaml` (containers, charm-user).

- [ ] **P2-7 — Secrets depth. `[M]`**
  - Closes: `Model.get_secret(label=…)`; `Secret.peek_content`; `Secret.set_info`
    (metadata update w/o new revision) (all doub).
  - How: extend `test_secrets.py` + the secret handlers to exercise label
    resolution, peek-without-tracking, and `set_info` (also have `get-secret-info`
    read real `SecretInfo` instead of the hardcoded `"monthly"`).
  - Refs: AUDIT A1; `src/charm.py` (secret handlers ~`:1361`), `test_secrets.py`.

- [ ] **P2-8 — Relations: limit enforcement, dead-relation read, remote_model. `[M]`**
  - Closes: `limit: 1` cardinality (reject 2nd integration, US7 AC6);
    dead-relation empty read on teardown (US7 AC4); `Relation.remote_model`
    (relation-model-get) (all doub).
  - How: integration test deploying a 3rd app to violate `limit`; assert relation
    data is inaccessible after removal; exercise remote-model read.
  - Refs: AUDIT A1; `charmcraft.yaml:255`, `test_relations.py`, `test_cmr.py`.

- [ ] **P2-9 — Observability: assert COS data against a live consumer. `[M]`**
  - Closes: COS relation data never verified vs a real prometheus/grafana/loki
    (only `is_active` today); Pebble log-forwarding via `LogForwarder` (plan
    `log-targets` never inspected) (both doub).
  - How: relate to a real (or stub) consumer and assert scrape-job targets, the
    shipped alert rules (`norma_alerts.yaml`), the dashboard payload, and the
    resulting Pebble plan `log-targets`.
  - Refs: AUDIT A1; `test_observability.py`, `src/prometheus_alert_rules/`,
    `src/grafana_dashboards/`.

- [ ] **P2-10 — Actions subsystem coverage. `[M]`**
  - Closes (all cons): auto-injected stdout/stderr/return-code on action
    *exception* (vs clean `event.fail()`); multi-unit fan-out; `parallel: true`
    trait; `execution-group` trait; `juju run --background`; `juju cancel-task`;
    `juju operations`/`list-operations`; `juju show-task`/`show-operation`;
    `run --wait=<dur>` (L); `juju actions --schema` (L).
  - How: declare `parallel`/`execution-group` on a couple of actions; add a
    deliberately-crashing action to exercise auto-injection; drive fan-out /
    background / cancel / operations via raw `juju.cli` (jubilant lacks helpers).
  - Refs: AUDIT A1b; `charmcraft.yaml:129`, `test_introspect.py` + a new actions
    suite.

- [ ] **P2-11 — Storage: VCT immutability, read CLI, storage-class. `[M]`**
  - Closes: volumeClaimTemplates immutability on refresh (strict xfail; ref
    juju#21722, NOT #21648); `juju storage`/`list-storage` read path on K8s (the
    "not yet available" memo is stale — it works); storage-class management
    (auto-create / qualified name) (all doub).
  - How: a `juju refresh` that adds/removes a storage definition asserting the
    domain `NotSupported` error; a `juju storage` read assertion; storage-class
    inspection.
  - Refs: AUDIT A1; `test_storage.py`, `charmcraft.yaml:51`.

- [ ] **P2-12 — Lifecycle & migration tail. `[M/L]`**
  - Closes: `start` hook + CAAS pod-churn re-emission asserted (M, doub);
    `migrate --dry-run` (precheck-only, works with a single controller — fits CI)
    (M); `juju debug-log` on K8s (L).
  - How: assert `start` in the ledger and count re-fires after a pod churn; use
    `migrate --dry-run` to exercise migration prechecks without a 2nd controller.
  - Refs: AUDIT A1 + A1b model-refresh; `test_lifecycle.py`.

---

## P3 — API-class blind-spots (whole classes absent; from AUDIT A2)

- [ ] **P3-1 — Add a file-type charm resource.** Only `oci-image` is declared;
  `type: file` + `resource-get` + `attach-resource` is a whole untested resource
  class — and it's the machine sibling's entire delivery model (high reuse value).
- [ ] **P3-2 — Pebble API completeness.** `Container.push_path`/`pull_path`
  (recursive), Pebble change-tracking (`get_change`/`wait_change`/…),
  `start_checks`/`stop_checks` (runtime check enable/disable). Extend
  `test-pebble-ops`.
- [ ] **P3-3 — Imperative ports + binding completeness.** `open_port`/`close_port`
  (vs declarative `set_ports`), `opened-ports` mutation, `network-get
  egress-subnets` (L, doub), `extra-bindings`/`juju bind`.
- [ ] **P3-4 — Secret API completeness.** Unit-owned secrets (`unit.add_secret`),
  `Secret.get_info`/`SecretInfo`, secret backends (k8s in-cluster; vault is
  out-of-scope/long-tail), cross-model secret consumption.
- [ ] **P3-5 — Deployment-type applicability decision.** Engine has
  Stateless/Daemon; the provisioner only wires Stateful. Decide: document as
  NA-by-provisioner, or add a calibration probe. (Likely a doc note, not a test.)
- [ ] **P3-6 — Tracing/parca pillar decision.** 4th observability pillar is absent
  (a documented Complexity-Tracking exception). Re-confirm the exception still
  holds for a Juju-CI standard, or add `tracing`.
- [ ] **P3-7 — Replace the private goal-state call.** `introspect` reads
  goal-state via `self.model._backend._run_tool(...)`; move to a supported ops
  path (fragile across ops versions).

---

## P4 — CI/CD hygiene & long tail

- [x] **P4-1 — `concurrency:` groups** ✅ DONE (PR #9, merged) — publish-rock
  per-ref `cancel-in-progress:true`, publish-edge serialized, ci cancel-superseded.
  Proven in prod: the #9 and #10 merges triggered **no** publish (paths-ignore).
- [ ] **P4-2 — Build-time causal binding (was a P0-2 sub-item, R1) `[P2]`.** Pin
  `charmcraft.yaml` `upstream-source` to the per-commit ref (`:main-<sha>` / a
  digest) instead of the mutable `:latest`, so charm-rev-N provably carries
  commit-N's image. PR #9 concurrency only *narrows* the concurrent-push race;
  this *closes* it. (Deploy reproducibility already holds — this is build-time
  correctness.) Also reserve/serialize the `:latest` manifest retag.
- [~] **P4-3 — `timeout-minutes` on all jobs, `paths-ignore` for docs-only PRs,
  pack/ROCK caching** (cheap-job hang protection + wasted-LXD avoidance). PARTIAL:
  `paths-ignore` (incl. `.github/**`, `tests/**`, `Makefile`) DONE via PR #9 and
  proven (no churn from #9/#10 merges); per-job `timeout-minutes` + pack/ROCK
  caching still TODO.
- [ ] **P4-4 — Make the sudoer-overlay swap atomic** (`charmcraft pack
  --project-dir`/temp copy or a `trap` restore) so a mid-pack failure doesn't
  leave `charmcraft.yaml` clobbered (`ci.yaml:54`, `release-tag.yaml:61`).
- [ ] **P4-5 — De-duplicate version sources → image distinguishability. ELEVATED
  `[P1]` (was a P0-2 sub-item, R2 — the real gate for replacing
  `juju-qa-container-resource`).** Charm (`git describe`), ROCK
  (`rockcraft.yaml:4` hardcoded `0.1.0`), and Go ldflag (`-X main.version=0.1.0`)
  all diverge; the workload reports `VERSION=0.1.0` for **every** OCI resource
  revision, so `get-version` cannot tell rev 3 from rev 4. Derive ROCK + binary
  version from the git tag so each image rev is **runtime-distinguishable**;
  optionally add a `get-image-digest` action. Without this, the resources-suite
  refresh test (`/data/dev/juju/tests/suites/resources/container.sh:38-48`,
  asserts the running image identity *changed* across `--resource …=3 → =4`)
  cannot be satisfied — even though 11 distinct numbered resource revisions
  already exist on CharmHub and are attachable. Pairs with **P2-1**.
- [ ] **P4-6 — Release polish.** Validate the promote ladder (forbid
  edge→stable skip in `promote.yaml`); attach `SHA256SUMS` + arm64 to GitHub
  Releases; build the release charm from the tagged commit rather than
  promote-by-name (`release-tag.yaml:34`).
- [ ] **P4-7 — Long tail.** Move image/CharmHub identity to an **org namespace**
  (off the personal `sinanawad` account); publish a **versioned action contract**
  (`contracts/actions-schema.yaml` → docs + a CI drift check); add `govulncheck`
  to `rock.yaml`; consolidate the duplicate PR vs publish ROCK pack definitions
  into a reusable workflow; unify the `mk8s` vs `microk8s` cloud-name + drop the
  duplicate microk8s install; the OCI-deploy-race retry wrapper is now
  **belt-and-suspenders only** (race fixed upstream in 4.0.6+, verified) — keep it
  but tighten its over-broad `'not found'` substring matcher to the resource-race
  regex so it can't silently mask unrelated deploy errors.

---

## Dependencies / sequencing notes
- **P0-1 first** — without running tests, none of P2/P3 can be *proven* (and
  Constitution VIII can't be met).
- **P0-2 RESOLVED** (premise falsified — artifact is already reproducible
  per-revision). P0-3 no longer gated by it; P0-3 must specify the consumption
  pin as **`--revision N` or `latest/edge`** (stable can lag — see R3/P4-6). The
  real container-resource-replacement gate is **R2 → P4-5** (image
  distinguishability), now the highest-value residue.
- **P1-5 (`xfail_strict`) pairs with P1-1** and **P2-11** (so a Juju fix flips the
  xfail to a visible CI signal).
- **P2-2 / P2-3 / P2-6** all need a kubectl-side assertion helper — build it once
  (a small `tests/integration` util) and reuse.
- Severity counts to burn down: **5 High** (P2-1, P2-2, P2-3, P1-4, P1-6),
  44 Medium, 8 Low across P2/P3.
