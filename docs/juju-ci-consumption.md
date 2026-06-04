# Juju-CI Consumption Contract

How Juju's own CI (`juju/juju`) should consume **juju-norma-k8s** when it replaces
the upstream K8s test charms. This is the contract referenced by remediation item
P0-3: for each charm we replace, it states *how* to obtain norma-k8s and the *exact
pin* to use.

> Status as of 2026-06-04. Concrete revisions drift — confirm current numbers with
> `juju info juju-norma-k8s` or `charmcraft status juju-norma-k8s`.

## TL;DR — pick a mode

Juju CI obtains charms two ways today, and norma-k8s supports both:

| Mode | What it is | Use when |
|------|-----------|----------|
| **CharmHub channel** (default) | `juju deploy juju-norma-k8s --channel=… [--revision N]`. The OCI image ships as a **numbered CharmHub resource**, served by CharmHub — no external image registry needed at deploy. | Replacing charms Juju CI already pulls from CharmHub (snappass-test, `juju-qa-*`), and **mandatory** for any test that refreshes between numbered resource revisions. |
| **In-tree source pack** | Vendor this repo into `juju/juju` `testcharms/charms/norma-k8s/`, `pack_charm` it, deploy by path with `--resource juju-norma-image=<ref>`. | Replacing charms Juju CI builds in-tree (`sidecar-non-root`, `credential-get-k8s`, `sidecar-sudoer`, storage), or when CI needs a hermetic, per-commit charm. **Mandatory** for the **sudoer variant** (never published to CharmHub). |

**Reproducibility:** pin a **`--revision N`** (byte-identical charm + a specific
numbered image resource — verified per-revision; see `docs/REMEDIATION-PLAN.md`
P0-2). Use **`--channel=latest/edge`** to track the engine-under-test (edge is
where regressions land first). Do **not** rely on `latest/stable` being fresh — it
has no automated promotion cadence and currently lags edge by ~12 revisions.

## How Juju CI obtains charms (the mechanism)

- **In-tree test charms** are packed from source: `tests/includes/charmcraft.sh`
  `pack_charm()` runs `charmcraft pack -p ./testcharms/charms/<name>`, then suites
  `juju deploy <packed>.charm` by path (e.g. `tests/suites/sidecar/rootless.sh`).
- **External charms** (snappass-test, postgresql-k8s, `juju-qa-*`) are pulled from
  CharmHub: `juju deploy <name> [--channel … --revision …]`
  (e.g. `tests/suites/sidecar/sidecar.sh`, `tests/suites/smoke_k8s/deploy.sh`).

norma-k8s is an **external** charm (separate repo, published to CharmHub), so the
CharmHub path is the natural drop-in for the external targets; the in-tree path is
for the charms Juju CI builds itself.

## Per-target contract

| Charm replaced | Suite(s) | Upstream consumption today | norma-k8s mode | Pin + deploy args |
|---|---|---|---|---|
| `snappass-test` | smoke_k8s, sidecar, secrets_k8s, ck | CharmHub `juju deploy snappass-test` (smoke_k8s pins `--revision 8 --channel stable`) | **CharmHub** | `juju deploy juju-norma-k8s --channel=latest/edge` (or `--revision N`). **Update HTTP checks `:5000` → `:8080/health`** (snappass serves :5000; norma serves :8080). |
| `juju-qa-pebble-notices` | sidecar | CharmHub `juju deploy juju-qa-pebble-notices` | **CharmHub** | `--channel=latest/edge`. Drive notices with the `trigger-notice` action (`via=api`). See the Pebble-notice caveat below. |
| `juju-qa-pebble-checks` | sidecar | CharmHub `juju deploy juju-qa-pebble-checks` | **CharmHub** | `--channel=latest/edge`. Toggle health with the `toggle-health` action → fires `pebble-check-failed`/`-recovered`. |
| `sidecar-non-root` | sidecar (`rootless.sh`) | **In-tree** `pack_charm ./testcharms/charms/sidecar-non-root` | **In-tree pack** (or CharmHub) | `charmcraft pack` → `juju deploy ./juju-norma-k8s_amd64.charm --resource juju-norma-image=<ref>`. Non-root by default. **Rewrite uid assertions** (norma uid **584792**, not the old `170/10000` markers). |
| `juju-qa-credential-get-k8s` | sidecar | **In-tree** `pack_charm ./testcharms/charms/credential-get-k8s` | **In-tree pack** | `juju deploy ./juju-norma-k8s_amd64.charm --trust --resource juju-norma-image=<ref>`, then `juju run …/0 check-security` (FR-039). **Requires `--trust`.** |
| `sidecar-sudoer` | sidecar (`rootless.sh`) | **In-tree** `pack_charm ./testcharms/charms/sidecar-sudoer` (`--resource ubuntu=…`) | **In-tree pack (required)** | Pack the **sudoer overlay**: `cp charmcraft-sudoer.yaml charmcraft.yaml && charmcraft pack` → `charm-user: sudoer`. Not on CharmHub, so in-tree only. |
| `juju-qa-container-resource` | resources | CharmHub + **numbered resource revisions** (`container.sh` refreshes `app-image=3 → 4`) | **CharmHub (required)** | `juju deploy juju-norma-k8s --channel=latest/edge` then `juju refresh --resource juju-norma-image=<N>` across ≥2 numbered revisions. Local packs upload only **one** resource revision, so this case **cannot** use in-tree pack. 11 numbered revisions exist. Requires `--storage data=1G --storage logs=512M`. |
| `postgresql-k8s` → now `dummy-storage-k8s` | storage_k8s | **Already replaced upstream** by in-tree `dummy-storage-k8s` (commit `eae2f427e9`) | **In-tree pack** | `charmcraft pack` → deploy with `--storage data=1G --storage logs=512M`; exercise `check-storage` (FR-030). Note `attach-storage` is IAAS-gated on K8s — PVs must be provisioned out-of-band. |

## Cross-cutting rules

- **Resource name** is `juju-norma-image` (not `ubuntu`/`app-image`/`redis`). Adjust
  every `--resource` flag accordingly.
- **Numbered resource revisions exist only on CharmHub.** A local `charmcraft pack`
  uploads a single resource revision, so any test that *refreshes between resource
  revisions* must use the CharmHub mode.
- **Container uid is `584792` (`_daemon_`).** Suites asserting specific uids/markers
  from the old charms (`170`, `10000`, `0`) must be rewritten.
- **`--trust`** is required for the credential-get path (`check-security`).
- **Sudoer variant** is built from `charmcraft-sudoer.yaml` (`charm-user: sudoer`),
  is CI-only, and is never published to CharmHub → in-tree pack only.
- **Workload port** is `8080` (config `calibration-int`), not snappass's `5000`.
- **Two storages** (`data` 1G + `logs` 512M) are declared in metadata; supply them
  where the suite needs persistence, or accept the defaults.
- **Pebble custom notices:** Juju ≤4.0.12 only dispatches `pebble-custom-notice` for
  notices owned by the **agent uid**. `trigger-notice via=api` (default) creates the
  notice via the charm's Pebble client (agent uid) and **is** delivered;
  `via=workload` reproduces the non-delivery and is an xfail sentinel. See
  `docs/REMEDIATION-PLAN.md` (P1-1) and the juju-brain note.
- **This is a calibration charm.** It deliberately embeds test-only behaviour
  (`bad-behavior-mode` config, a defer test-gate) and intentionally omits some
  production pillars (TLS, profiling). It is a *feature-exercise fixture*, not a
  production application.

## Suites that must NOT use norma-k8s

`smoke_k8s_psql` (real DB writes), `deploy_caas` (multi-app topology),
`controllercharm` (controller metrics), `coslite`/`kubeflow`/`ck` bundle
deployments, `dashboard` (controller relation), `caasadmission` (no charm).
