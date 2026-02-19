# K8s Charm Usage Research

Research document cataloging every K8s charm deployed in the Juju integration test suites, what Juju operations are exercised against each charm, and what is actually being verified.

**Scope**: All test suites under `tests/suites/` that deploy charms to a K8s provider.

---

## Summary

| Suite | K8s Charms | Juju Operations | Focus |
|-------|-----------|-----------------|-------|
| smoke_k8s | snappass-test | deploy, wait | Basic K8s smoke |
| smoke_k8s_psql | postgresql-k8s, postgresql-test-app | deploy, integrate, actions | DB relation + writes |
| deploy_caas | discourse-k8s, postgresql-k8s, redis-k8s, nginx-ingress-integrator | deploy, trust, integrate, actions | Multi-app orchestration |
| sidecar | snappass-test, juju-qa-pebble-notices, juju-qa-pebble-checks, juju-qa-credential-get-k8s, sidecar-non-root*, sidecar-sudoer* | deploy, remove, force-remove, ssh, actions, debug-log | Sidecar lifecycle, pebble, rootless |
| storage_k8s | postgresql-k8s | deploy, import-filesystem, attach-storage, add-unit, remove-unit | PV lifecycle, storage attach |
| secrets_k8s | alertmanager-k8s, nginx-ingress-integrator, snappass-test | deploy, scale, exec (secret-*), grant-secret, model-secret-backend | Secret lifecycle, drain, parallel |
| caasadmission | (none - kubectl only) | kubectl apply/patch | Admission controller labels |
| controllercharm | prometheus-k8s | deploy, offer, relate, remove-relation | Metrics endpoint, CMR |
| coslite | cos-lite bundle (alertmanager, grafana, prometheus, traefik) | deploy bundle, config, actions | Bundle deploy, health checks |
| dashboard | juju-dashboard | deploy, expose, relate | Dashboard relation (any provider) |
| ck | charmed-kubernetes bundle, snappass-test | deploy bundle, scp, add-k8s | CK on IAAS, CAAS workload |
| kubeflow | kubeflow bundle | deploy bundle, trust | Bundle deploy, UI access |
| deploy_aks | juju-qa-dummy-sink, juju-qa-dummy-source | deploy, relate, config | AKS cloud (SKIPPED) |
| resources | juju-qa-container-resource | deploy, attach-resource, refresh | OCI container resources |

\* = custom test charm packed locally

---

## 1. smoke_k8s

**Location**: `tests/suites/smoke_k8s/`

### Charms Deployed

| Charm | Channel | Source |
|-------|---------|--------|
| snappass-test | stable (rev 8) | CharmHub |

### Operations

| Operation | Command | Assertion |
|-----------|---------|-----------|
| Deploy | `juju deploy snappass-test --revision 8 --channel stable` | Deployed |
| Wait | `wait_for` idle condition | juju-status==idle, workload-status!=error |
| Destroy | `destroy_model` | Model removed |

### What It Tests
Minimal K8s deployment smoke test. Confirms Juju can deploy a sidecar charm and reach idle state. No relations, no actions, no HTTP verification.

---

## 2. smoke_k8s_psql

**Location**: `tests/suites/smoke_k8s_psql/`

### Charms Deployed

| Charm | Channel | Notes |
|-------|---------|-------|
| postgresql-k8s | 16/edge | `--trust` (cluster scope) |
| postgresql-test-app | latest/edge | base: ubuntu@22.04 |

### Operations

| Operation | Command | Assertion |
|-----------|---------|-----------|
| Deploy postgresql | `juju deploy postgresql-k8s --trust --channel 16/edge` | Deployed |
| Deploy test app | `juju deploy postgresql-test-app --channel latest/edge --base ubuntu@22.04` | Deployed |
| Integrate | `juju integrate postgresql-k8s postgresql-test-app:database` | Relation created |
| Wait | Wait for both active/idle | Both apps active |
| Wait | Check for "received database credentials" | Credentials exchanged |
| Action | `juju run postgresql-test-app/0 start-continuous-writes` | status==completed |
| Action | `juju run postgresql-test-app/0 stop-continuous-writes` | status==completed |
| Validate | Check writes > 3 | Database writes persisted |

### What It Tests
K8s database relation lifecycle. Confirms charm-to-charm integration via database endpoint, credential exchange, and actual data writes through the relation.

---

## 3. deploy_caas

**Location**: `tests/suites/deploy_caas/`

### Charms Deployed

| Charm | Channel | Notes |
|-------|---------|-------|
| discourse-k8s | latest/stable | Central app |
| postgresql-k8s | latest/stable | DB backend |
| redis-k8s | edge | Stable too old |
| nginx-ingress-integrator | latest/stable | `--trust --scope=cluster` |

### Operations

| Operation | Command | Assertion |
|-----------|---------|-----------|
| Deploy (x4) | `juju deploy <charm>` | All 4 deployed |
| Trust | `juju trust nginx-ingress-integrator --scope=cluster` | Cluster access granted |
| Integrate (x3) | discourse-k8s <-> postgresql, redis, nginx | Relations formed |
| Wait | All 4 apps active/idle | Healthy |
| Action | `juju run discourse-k8s/0 create-user admin=true email=user@example.com` | Output contains "user: user@example.com" |

### What It Tests
Multi-application K8s orchestration. Confirms 4-charm integration graph with 3 relations, trust delegation, and charm action execution. Most complex relationship topology in K8s test suites.

---

## 4. sidecar

**Location**: `tests/suites/sidecar/`

### Charms Deployed

| Charm | Source | Notes |
|-------|--------|-------|
| snappass-test | CharmHub | Deploy + HTTP verify |
| juju-qa-pebble-notices | CharmHub | Pebble notice lifecycle |
| juju-qa-pebble-checks | CharmHub | Pebble health checks |
| juju-qa-credential-get-k8s | CharmHub | K8s API credential-get |
| sidecar-non-root | Local testcharm | `--resource ubuntu=public.ecr.aws/ubuntu/ubuntu:22.04` |
| sidecar-sudoer | Local testcharm | `--resource ubuntu=public.ecr.aws/ubuntu/ubuntu:22.04` |

### Operations

**test_deploy_and_remove_application**:
- Deploy snappass-test, wait active, HTTP verify (`curl http://<addr>:5000` contains "Snappass"), `juju remove-application`, wait for 0 apps

**test_deploy_and_force_remove_application**:
- Same as above but uses `juju remove-application snappass-test --force --no-prompt`

**test_pebble_notices**:
- Deploy juju-qa-pebble-notices, wait active
- `juju ssh --container redis juju-qa-pebble-notices/0 /charm/bin/pebble notify foo.com/bar key=val`
- Wait for workload-status=="maintenance" with message "notice type=custom key=foo.com/bar"
- Repeat with second notice key

**test_pebble_checks**:
- Deploy juju-qa-pebble-checks
- Wait for maintenance + "check failed: exec-check" (initial fail state)
- `juju ssh --container ubuntu juju-qa-pebble-checks/0 mkdir /trigger/`
- Wait for active + "check recovered: exec-check"

**test_credential_get_k8s**:
- Deploy juju-qa-credential-get-k8s, `juju trust --scope=cluster`
- `juju run juju-qa-credential-get-k8s/0 hit-k8s-api-default` (in-cluster)
- `juju run juju-qa-credential-get-k8s/0 hit-k8s-api-credential-get` (credential-get)
- Assert both outputs are identical

**test_rootless** (2 sub-tests):
- `juju deploy $(pack_charm ./testcharms/charms/sidecar-non-root) --resource ubuntu=...`
- Wait idle, `juju debug-log --replay` contains "charm=170", "sudo=no", "rootless=10000", "rootful=0"
- Same for sidecar-sudoer: "charm=171", "sudo=yes", "rootless=10000", "rootful=0"

### What It Tests
Comprehensive sidecar charm lifecycle. Covers: normal removal, forced removal, Pebble notice/check event handling, K8s credential-get vs in-cluster credentials, and rootless/sudoer execution modes. This is the deepest sidecar-specific test suite.

---

## 5. storage_k8s

**Location**: `tests/suites/storage_k8s/`

### Charms Deployed

| Charm | Channel | Notes |
|-------|---------|-------|
| postgresql-k8s | 14/stable | `--trust`, scaled to 1 or 3 units |

### Operations

**test_import_filesystem**:
- Deploy postgresql-k8s, wait for pgdata/0 storage
- Capture PV provider-id via `juju storage --format json`
- `juju remove-application`, `juju remove-storage pgdata/0 --no-destroy`
- Patch PV reclaim policy via kubectl, delete PVC, clear claimRef
- `juju import-filesystem kubernetes <PV> pgdata`

**test_force_import_filesystem**:
- Same as above but with `juju import-filesystem kubernetes <PV> pgdata --force`
- Tests label mismatch scenarios

**test_deploy_attach_storage**:
- Import PV in second model, deploy with `--attach-storage pgdata/0`
- Verify PV is Bound, PVC labels correct (`storage.juju.is/name`, `app.kubernetes.io/managed-by`)

**test_add_unit_attach_storage**:
- Deploy with 3 units, capture all 3 PVs
- Import in second model, deploy with `--attach-storage pgdata/0`
- `juju add-unit psql-k8s --attach-storage pgdata/1`
- `juju add-unit psql-k8s --attach-storage pgdata/2`
- Verify all PVs bound with correct labels

**test_add_unit_duplicate_pvc_exists**:
- Tests scaling failure when PVC has incorrect labels
- Patches PVC label to `storage.juju.is/name=not-pgdata`, verifies scaling blocks
- Restores label, verifies scaling succeeds

**test_add_unit_attach_storage_scaling_race_condition**:
- Rapidly add then remove units to test race conditions
- `juju add-unit` x2 then `juju remove-unit --num-units 2` then `--num-units 1`
- Verifies storage detaches correctly

### What It Tests
K8s PersistentVolume lifecycle management. Covers: PV import, reclaim policy handling, storage attachment across models, multi-unit storage, PVC label verification, and scaling race conditions. Heavy kubectl substrate verification.

---

## 6. secrets_k8s

**Location**: `tests/suites/secrets_k8s/`

### Charms Deployed

| Charm | Test | Notes |
|-------|------|-------|
| alertmanager-k8s | run_secrets | App + unit secret ownership |
| nginx-ingress-integrator | run_secrets | Secret consumer (rev 83, `--trust`) |
| snappass-test | run_user_secrets, run_secret_drain, run_user_secret_drain | User secret lifecycle |

### Operations

**run_secrets** (application-owned secrets):
- Create model with `--config secret-backend=auto`
- `juju exec --unit alertmanager-k8s/0 -- secret-add foo=bar` (app-owned)
- `juju exec --unit alertmanager-k8s/0 -- secret-add --owner unit foo=bar2` (unit-owned)
- Verify secrets in K8s: `microk8s kubectl -n <model> get secrets`
- Scale up/down: `juju scale-application alertmanager-k8s 2` then `1` then `0`
- Verify unit secrets deleted when units removed, app secrets persist until app removed
- Grant secret via relation: `secret-grant <uri> -r <relation_id>`
- Verify consumer reads: `juju exec --unit nginx/0 -- secret-get <uri>`
- Revoke: `secret-revoke <uri> --relation <id>` and `--app nginx`
- Verify K8s RBAC role rules for secret access

**run_user_secrets**:
- `juju add-secret mysecret owned-by="<model>-1"`
- `juju show-secret mysecret --revisions --format yaml`
- `juju update-secret <uri> --info info owned-by="<model>-2"`
- `juju grant-secret <uri> snappass-test`
- `juju update-secret <uri> --auto-prune=true` (verify old revisions pruned)
- `juju exec --unit snappass-test/0 -- secret-get <uri> --peek`
- `juju exec --unit snappass-test/0 -- secret-get <uri> --refresh`
- `juju revoke-secret`, `juju remove-secret`

**run_secret_drain** / **run_user_secret_drain**:
- Deploy Vault backend, `juju add-secret-backend myvault vault endpoint=<addr> token=<token>`
- Switch backend: `juju model-secret-backend myvault`
- Verify secrets drained to Vault (K8s backend cleared)
- Switch back: `juju model-secret-backend auto`
- Verify secrets drained back to K8s

**run_test_add_multiple_secrets_parallel**:
- Create 100 secrets in parallel: `seq 1 100 | xargs -P5 -I{} juju add-secret "test{}" "foo=bar{}"`
- Verify all secret IDs exist

### What It Tests
Gold-standard secret lifecycle testing. Covers: app vs unit ownership, scaling behavior, cross-application grants via relations, K8s RBAC verification, secret revisions with auto-prune, backend drain to/from Vault, and parallel creation stress test. One of the two "gold standard" suites (with secrets_iaas).

---

## 7. caasadmission

**Location**: `tests/suites/caasadmission/`

### Charms Deployed
**None** -- this suite operates directly on K8s resources via kubectl.

### Operations

**test_controller_model_admission** / **test_new_model_admission**:
- Create ServiceAccount, Role, RoleBinding in model namespace via kubectl
- Create bearer token: `kubectl create token <name> -n <namespace>`
- Apply ConfigMap using limited-permission kubeconfig
- Verify ConfigMap gets Juju admission label: `app.juju.is/created-by=test-app`

**test_model_chicken_and_egg**:
- Delete modeloperator service: `kubectl delete svc modeloperator -n <namespace>`
- Patch modeloperator deployment with test label
- Verify deployment comes back up (model operator can restart without self-validation)

### What It Tests
K8s admission controller behavior. Confirms that Juju's admission webhook correctly labels resources created by non-Juju ServiceAccounts, and that the model operator can recover from service deletion (chicken-and-egg problem).

---

## 8. controllercharm

**Location**: `tests/suites/controllercharm/`

### Charms Deployed

| Charm | Channel | Notes |
|-------|---------|-------|
| prometheus-k8s | 1/stable | `--trust`, deployed as p1/p2 aliases |

### Operations

**run_prometheus**:
- `juju offer controller.controller:metrics-endpoint`
- `juju deploy prometheus-k8s --channel 1/stable --trust`
- `juju relate prometheus-k8s controller.controller`
- Verify controller in Prometheus targets via HTTP: `curl http://<prom-ip>:9090/api/v1/targets`
- `juju remove-relation prometheus-k8s controller`
- Verify controller removed from targets

**run_prometheus_multiple_units**:
- Deploy two instances (p1, p2) with different aliases
- Relate both to controller, `juju add-unit p1` (scale to 2)
- Verify targets for each unit
- `juju remove-unit p1 --num-units 1`, verify targets update

**run_prometheus_cross_controller**:
- Bootstrap second controller on K8s
- Deploy prometheus-k8s in second controller
- Cross-controller relation: `juju relate prometheus-k8s "${CONTROLLER_NAME}:controller.controller"`
- Verify targets across controllers

### What It Tests
Controller charm metrics integration. Confirms Prometheus can scrape Juju controller metrics via relation, handles multi-unit scaling, and works across controllers (CMR). K8s-only for 2/3 tests.

---

## 9. coslite

**Location**: `tests/suites/coslite/`

### Charms Deployed

| Charm | Channel | Notes |
|-------|---------|-------|
| cos-lite (bundle) | stable | `--trust` |
| ubuntu-lite | default | Used for HTTP verification |

Bundle components: alertmanager, grafana, prometheus, traefik

### Operations

- `juju deploy cos-lite --trust --channel=stable`
- `juju config traefik external_hostname=test-coslite.com`
- Wait for all units idle (30-minute timeout)
- `juju run grafana/0 get-admin-password --wait=2m`
- HTTP health checks via `juju ssh ubuntu-lite/0 curl`:
  - alertmanager: `http://<ip>:9093/-/ready` (200)
  - grafana: `http://<ip>:3000/api/health` (200)
  - prometheus: `http://<ip>:9090/-/ready` (200)

### What It Tests
COS Lite bundle deployment and health. Confirms the full observability stack deploys on K8s, all components reach idle, and HTTP endpoints respond. Uses `KILL_CONTROLLER=true` teardown (K8s model cleanup workaround).

---

## 10. dashboard

**Location**: `tests/suites/dashboard/`

### Charms Deployed

| Charm | Notes |
|-------|-------|
| juju-dashboard (alias: dashboard) | Deployed to controller model |

### Operations

- `juju switch controller`
- `juju deploy juju-dashboard dashboard`
- `juju expose dashboard`
- `juju relate dashboard controller`
- `juju dashboard 2>&1` -- expects "not implemented" error
- Same check from a non-controller model

### What It Tests
Dashboard charm deployment. **Not K8s-specific** -- runs on any provider. Currently only verifies the `juju dashboard` command returns "not implemented" (functionality pending reimplementation in controller charm).

---

## 11. ck (Charmed Kubernetes)

**Location**: `tests/suites/ck/`

### Charms Deployed

| Charm | Provider | Notes |
|-------|----------|-------|
| charmed-kubernetes (bundle) | IAAS (ec2/gce/azure) | `--trust`, with provider overlays |
| Provider integrators (aws-integrator, gcp-integrator, azure-integrator) | IAAS | Via bundle |
| snappass-test | K8s (CAAS workload) | Deployed to CK cluster |

### Operations

**test_deploy_ck**:
- `juju deploy charmed-kubernetes --overlay <provider> --overlay ./overlay.yaml --trust`
- Wait for kubernetes-control-plane, kubernetes-worker, integrators to reach active (1800s)
- `juju scp kubernetes-control-plane/0:config ~/.kube/config`
- `kubectl cluster-info`, `kubectl get ns`
- `juju run "$integrator_app_name/leader" --wait=10m purge-subnet-tags`

**test_deploy_caas_workload**:
- `juju add-k8s <cloud> --storage <provider-storage> --controller <name>`
- `juju add-model <name> <k8s-cloud>`
- `juju deploy snappass-test`
- Wait for idle

### What It Tests
Full Charmed Kubernetes lifecycle on IAAS. Bootstraps CK on cloud providers, extracts kubeconfig, deploys a CAAS workload to the CK cluster. Tests Juju managing K8s *and* deploying to K8s.

---

## 12. kubeflow

**Location**: `tests/suites/kubeflow/`

### Charms Deployed

| Charm | Channel | Notes |
|-------|---------|-------|
| kubeflow (bundle) | 1.9 | `--trust` |

### Operations

- MetalLB setup: `sudo microk8s enable "metallb:10.64.140.43-10.64.140.49"`
- `juju deploy kubeflow --trust --channel 1.9`
- Wait for training-operator active/idle (1800s)
- Extract Jupyter IP: `microk8s kubectl -n kubeflow get svc istio-ingressgateway-workload`
- `curl ${jupyter_ip}` contains "Found" (HTTP 302)
- `KILL_CONTROLLER=true` for teardown

### What It Tests
Kubeflow bundle deployment on K8s. Confirms the ML/AI stack deploys, training-operator activates, and Jupyter UI is accessible via LoadBalancer. K8s-only.

---

## 13. deploy_aks

**Location**: `tests/suites/deploy_aks/`

**STATUS: SKIPPED** (`if [ true ]` guard -- pending K8s tooling in strict snap)

### Charms (if enabled)

| Charm | Notes |
|-------|-------|
| juju-qa-dummy-sink | base: ubuntu@22.04 |
| juju-qa-dummy-source | base: ubuntu@22.04 |

### Operations (if enabled)
- `az aks create`, `juju add-k8s --aks`, bootstrap on AKS
- Deploy + relate dummy-sink/source
- `juju config dummy-source token=yeah-boi`, verify in dummy-sink status

### What It Would Test
AKS cloud integration. Currently disabled.

---

## 14. resources (container subset)

**Location**: `tests/suites/resources/` (specifically `container.sh`)

### Charms Deployed

| Charm | Notes |
|-------|-------|
| juju-qa-container-resource | OCI/container resource support |

### Container Images
- `localhost:5000/resource-1` (built from tests/suites/resources/containers/resource-1/)
- `localhost:5000/resource-2` (built from tests/suites/resources/containers/resource-2/)
- CharmHub app-image revisions 3 and 4

### Operations

- Start local registry: `podman run -d -p 5000:5000 registry:2.7`
- Build + push 2 container images
- `juju deploy juju-qa-container-resource --resource app-image=localhost:5000/resource-1`
- Verify workload status: "I am resource 1"
- `juju attach-resource juju-qa-container-resource app-image=localhost:5000/resource-2`
- Verify: "I am resource 2"
- `juju refresh juju-qa-container-resource --resource app-image=3` (CharmHub rev)
- Verify: "I am the charmhub resource (revision 3)"
- `juju refresh juju-qa-container-resource --resource app-image=4`
- Verify: "I am the charmhub resource (revision 4)"

### What It Tests
OCI container resource lifecycle. Confirms local registry resources, CharmHub resources, resource attachment, and resource refresh all work on K8s. Tests the juju-managed container image pipeline.

---

## Analysis

### Charm Dependency Map

Charms used by multiple suites (risk if charm breaks):

| Charm | Used By | Count |
|-------|---------|-------|
| snappass-test | smoke_k8s, sidecar, secrets_k8s, ck | 4 |
| postgresql-k8s | smoke_k8s_psql, deploy_caas, storage_k8s | 3 |
| nginx-ingress-integrator | deploy_caas, secrets_k8s | 2 |
| prometheus-k8s | controllercharm, coslite (via bundle) | 2 |
| alertmanager-k8s | secrets_k8s, coslite (via bundle) | 2 |

### Juju Operation Coverage

| Juju Operation | Suites That Exercise It |
|----------------|------------------------|
| deploy | All (except caasadmission) |
| integrate/relate | smoke_k8s_psql, deploy_caas, secrets_k8s, controllercharm, coslite, dashboard, ck, deploy_aks |
| remove-application | sidecar, storage_k8s, controllercharm, dashboard |
| remove-application --force | sidecar, controllercharm |
| scale-application | secrets_k8s |
| add-unit / remove-unit | storage_k8s, controllercharm |
| trust | smoke_k8s_psql, deploy_caas, sidecar, secrets_k8s, controllercharm, coslite, ck, kubeflow |
| actions (juju run) | smoke_k8s_psql, deploy_caas, sidecar, secrets_k8s, controllercharm, coslite |
| exec (juju exec) | secrets_k8s |
| ssh (juju ssh) | sidecar, coslite |
| config | coslite, deploy_aks |
| expose | dashboard |
| import-filesystem | storage_k8s |
| attach-storage | storage_k8s |
| attach-resource | resources |
| refresh (with resources) | resources |
| add-secret / grant-secret | secrets_k8s |
| model-secret-backend | secrets_k8s |
| offer (CMR) | controllercharm |
| add-k8s | ck |
| debug-log | sidecar |

### Key Observations

1. **snappass-test is the most reused charm** (4 suites) -- breakage would cascade widely
2. **No suite uses the calibration charm (norma-k8s)** -- all depend on real-world charms from CharmHub
3. **Substrate verification varies widely**: storage_k8s and secrets_k8s verify K8s resources directly; most others only check Juju status
4. **Forced teardown is common**: coslite, secrets_k8s, and kubeflow all set `KILL_CONTROLLER=true`, indicating K8s model cleanup issues
5. **deploy_aks is dead code** -- permanently skipped
6. **dashboard is not K8s-specific** -- runs on any provider
7. **Pebble operations are sidecar-exclusive** -- only tested in the sidecar suite
8. **Secret drain (Vault) is only tested in secrets_k8s** -- no other suite touches secret backends
9. **Bundle deployments have extreme timeouts** -- kubeflow and coslite use 1800s (30 min) waits

---

## Replacement Analysis: norma-k8s as Calibration Charm

### Current norma-k8s Capabilities

The calibration charm already supports these Juju primitives:

| Capability | Implementation | Verified By |
|-----------|---------------|-------------|
| Deploy + wait idle | Sidecar with OCI resource, reaches active in ~60s | All integration tests |
| Remove (normal + forced) | Standard lifecycle, clean shutdown handler | test_lifecycle |
| Relations (peer) | `norma-peers` for cluster state | test_scaling, test_relations |
| Relations (custom interface) | `calibration-provider`/`calibration-requirer` for self-relation pattern | test_relations, test_cmr |
| Relations (COS) | `metrics-endpoint`, `grafana-dashboard`, `log-proxy` | test_observability |
| Relations (juju-info) | `juju-info` provides endpoint (standard) | — |
| Config (all types) | string, int, float, boolean, secret | test_config |
| Scaling (add/remove units) | Peer relation tracks cluster, leader election | test_scaling |
| Actions (18 total) | introspect, get-event-log, set-status, toggle-health, test-pebble-ops, trigger-notice, check-storage, get-version, test-defer, etc. | test_introspect, test_pebble_ops, test_health_checks |
| Secrets (charm-owned) | Create, rotate, grant/revoke via relation, secret config type | test_secrets |
| Storage (PV) | `data` (required) + `logs` (optional), marker write, attachment verification | test_storage |
| Pebble layers | Full layer management, service start/stop/restart | test_pebble_ops |
| Pebble health checks | HTTP + exec + TCP checks, fail/recover events | test_health_checks |
| Pebble notices | Custom notice via `pebble notify`, event capture | test_notices |
| Pebble exec/push/pull | 14-op suite: push, pull, mkdir, list, exec, remove, exists | test_pebble_ops |
| OCI resource | `juju-norma-image`, deploy with `--resource` | test_oci_resource |
| Multi-container | `norma` (primary) + `norma-secondary` (port 8081) | test_multi_container |
| Non-root | UID/GID 584792, `charm-user: non-root` | test_security |
| Event deferral | Arm/disarm via action, captures deferred re-emission | test_defer |
| Event ledger | Full event history with metadata, filterable | test_lifecycle, all tests |
| Debug-log / introspect | Comprehensive 9-section JSON report | test_introspect |
| HTTP workload | Go binary with `/health`, `/version`, `/ready`, `/metrics`, `/toggle-health` | test_health_checks |
| CMR-compatible | calibration-provider can be offered cross-model | test_cmr |

### Per-Suite Replacement Verdict

#### 1. smoke_k8s -- REPLACE

| Current | Replacement | Notes |
|---------|-------------|-------|
| snappass-test deploy + wait | norma-k8s deploy + wait | norma-k8s reaches active faster (single binary vs Redis+Flask) |
| HTTP check (`curl :5000` for "Snappass") | HTTP check (`curl :8080/health` for "OK") | norma has dedicated health endpoint |

**No modifications needed.** norma-k8s is a strict superset. Deploy, wait for active, curl health endpoint, destroy model.

#### 2. sidecar -- REPLACE (mostly)

| Test | Current Charm | norma-k8s? | Notes |
|------|---------------|------------|-------|
| deploy + remove | snappass-test | YES | Deploy, HTTP verify `/health`, remove-application |
| deploy + force-remove | snappass-test | YES | Same but `--force --no-prompt` |
| pebble_notices | juju-qa-pebble-notices | YES | `trigger-notice` action or `juju ssh --container norma ... pebble notify` |
| pebble_checks | juju-qa-pebble-checks | YES | `toggle-health` action flips health, Pebble check-failed/recovered events fire |
| credential_get | juju-qa-credential-get-k8s | **NO -- see below** | Requires K8s API access, `credential-get` hook tool |
| rootless | sidecar-non-root | PARTIAL | norma runs non-root (UID 584792), but test checks specific UID values in debug-log |
| sudoer | sidecar-sudoer | **NO -- see below** | Requires sudo-capable variant |

**Modifications needed:**
- **credential_get**: Would need a `hit-k8s-api` action that calls `credential-get` hook tool and then hits the K8s API. Low complexity (~20 lines), but requires `--trust --scope=cluster` at deploy time. Alternatively, the `check-security` action already detects trust availability -- extend it to actually call the K8s API.
- **sudoer variant**: Would need a second charmcraft overlay that runs with `charm-user: root` and sudo capabilities. Different security posture from the principal variant.

**Charms this replaces:** snappass-test (2 tests), juju-qa-pebble-notices (1 test), juju-qa-pebble-checks (1 test), sidecar-non-root (1 test) = 5 of 7 tests.

#### 3. resources -- REPLACE

| Current | Replacement | Notes |
|---------|-------------|-------|
| juju-qa-container-resource + 2 local images | norma-k8s + ROCK variants | Deploy with `--resource juju-norma-image=localhost:32000/juju-norma:0.1.0` |
| `attach-resource app-image=resource-2` | `attach-resource juju-norma-image=...` | Same attach semantics |
| Verify workload status message changes | Verify via `get-version` action (workload version from OCI env) | norma's VERSION env var in Pebble layer tracks the image |
| `juju refresh --resource app-image=3` | `juju refresh --resource juju-norma-image=<rev>` | Requires norma-k8s published to CharmHub for rev-based refresh |

**Modifications needed:**
- **Workload status message**: The current test verifies the charm's workload status message changes to reflect which image is running ("I am resource 1" vs "I am resource 2"). norma-k8s doesn't set workload status messages (uses `ActiveStatus()` with no message per constitution). Alternative: use `get-version` action to verify the workload version changed, or `introspect` to check container image details.
- **CharmHub publishing**: The `juju refresh --resource app-image=3` test uses CharmHub revision numbers. Requires norma-k8s published to CharmHub with multiple resource revisions. This is a CI/release concern, not a code change.

#### 4. secrets_k8s -- PARTIAL REPLACE

| Test | Current Charm | norma-k8s? | Notes |
|------|---------------|------------|-------|
| run_secrets (app/unit ownership) | alertmanager-k8s | PARTIAL | norma creates app-owned secrets, but test uses `juju exec --unit ... secret-add` which bypasses the charm entirely |
| secret grant via relation | alertmanager-k8s + nginx | YES | norma grants secrets to calibration-provider relations. Deploy two instances, integrate, verify grant/revoke |
| run_user_secrets | snappass-test | YES (as target) | User secrets are Juju-managed, charm is just a target for grant/revoke. Any charm works |
| K8s RBAC verification | alertmanager-k8s | YES (as target) | kubectl verification of K8s secrets. Charm-independent |
| run_secret_drain (Vault) | alertmanager-k8s | YES (as target) | Vault backend drain is Juju-level. Any charm works |
| parallel creation stress | (no charm) | N/A | Pure `juju add-secret` CLI test |

**Key insight:** Most secrets_k8s tests use `juju exec --unit <charm>/0 -- secret-add` to create secrets *inside* the unit. This tests Juju's secret infrastructure, not the charm's secret handling. Any sidecar charm with a shell-accessible container works. norma-k8s's bare-base ROCK has **no shell** (`base: bare`), so `juju exec` would fail.

**Modifications needed:**
- **Shell access**: Either (a) add `/bin/sh` to the ROCK via a `busybox` slice, or (b) provide a `create-secret` action that wraps the `secret-add` hook tool. Option (b) is cleaner and avoids bloating the image.
- **Secret consumer role**: For grant verification, deploy a second norma-k8s instance as `calibration-requirer`. The existing self-relation pattern already supports this.

#### 5. smoke_k8s_psql -- MUST NOT REPLACE

This suite tests **actual database write operations** through the `postgresql` relation interface. norma-k8s does not implement `postgresql` (nor should it -- it's a calibration charm, not a database client).

**Verdict:** Keep postgresql-k8s + postgresql-test-app. This tests a real-world relation interface that a calibration charm cannot meaningfully simulate.

#### 6. deploy_caas -- MUST NOT REPLACE

This suite tests **multi-application orchestration** with 4 real-world charms (discourse, postgresql, redis, nginx-ingress) forming a complex relation graph. The value is testing Juju's ability to manage a realistic application topology.

**Verdict:** Keep as-is. A calibration charm deployed 4 times with synthetic relations would not test the same integration complexity.

#### 7. caasadmission -- MUST NOT REPLACE (no charm involved)

Pure kubectl operations testing Juju's admission webhook. No charm is deployed.

**Verdict:** N/A -- no charm to replace.

#### 8. controllercharm -- MUST NOT REPLACE

Tests the **Juju controller's built-in metrics endpoint** (`controller:metrics-endpoint`). Prometheus scrapes the controller, not a workload charm.

**Verdict:** Keep prometheus-k8s. Although norma-k8s has a `metrics-endpoint` provides, this suite tests the *controller charm*, not workload scraping. However, norma-k8s could augment this suite as an additional metrics *consumer* to test cross-model relation with the controller.

**Speculation:** A `metrics-consumer` requires endpoint on norma-k8s (consuming Prometheus remote-write or similar) could let it replace prometheus-k8s for the basic "scrape and verify" pattern. But this adds significant complexity for low value -- prometheus-k8s is the canonical consumer.

#### 9. coslite -- MUST NOT REPLACE

Tests the **COS Lite bundle** (alertmanager, grafana, prometheus, traefik) as a deployment unit. The value is testing Juju's bundle deployment and multi-charm health.

**Verdict:** Keep as-is. norma-k8s could be added as a *workload being observed* to test COS integration from the workload side (metrics, dashboards, log forwarding). This is complementary, not a replacement.

#### 10. dashboard -- MUST NOT REPLACE

Tests the **juju-dashboard** charm and its relation to the controller. Provider-agnostic (not K8s-specific).

**Verdict:** Keep as-is. Not related to workload charming.

#### 11. ck (Charmed Kubernetes) -- MUST NOT REPLACE

Tests **full Charmed Kubernetes deployment on IAAS** and then deploying a CAAS workload. snappass-test is used as the CAAS workload.

**Verdict:** Keep the CK bundle. **norma-k8s could replace snappass-test** as the CAAS workload deployed into the CK cluster -- it's a better test because it exercises storage, Pebble, and OCI resources in addition to basic deploy.

#### 12. kubeflow -- MUST NOT REPLACE

Tests the **kubeflow bundle** deployment. Domain-specific ML/AI stack.

**Verdict:** Keep as-is.

#### 13. deploy_aks -- SKIPPED (dead code)

Currently disabled. If re-enabled, norma-k8s could replace juju-qa-dummy-sink/source for the basic deploy + config verification.

#### 14. storage_k8s -- PARTIAL REPLACE

| Test | Current (postgresql-k8s) | norma-k8s? | Notes |
|------|--------------------------|------------|-------|
| import-filesystem | PV import with pgdata | YES | norma has `data` storage on PV, same import semantics |
| force import (label mismatch) | Same | YES | Storage name changes (`pgdata` -> `data`), but same Juju operation |
| deploy --attach-storage | Deploy with pre-existing PV | YES | `--attach-storage data/0` |
| add-unit --attach-storage | Scale with PV reattach | YES | Same pattern works |
| duplicate PVC label check | PVC label validation | YES | Labels use `storage.juju.is/name=data` |
| scaling race condition | Rapid add/remove units | YES | norma-k8s already tested with scaling |

**Modifications needed:**
- None for the charm itself. The tests need to be rewritten to use `data` storage name instead of `pgdata`, and `juju-norma-image` resource instead of postgresql-k8s's built-in image. All Juju-level operations are identical.
- **One caveat:** postgresql-k8s writes real data to its PV that survives import. norma-k8s writes a calibration marker (`calibration-marker.json`). This is actually *better* for testing -- the marker file is a simple, verifiable proof that storage persisted across import, without needing to understand PostgreSQL internals.

### Replacement Summary

| Suite | Verdict | Charms Replaced | Charms Kept | Modifications |
|-------|---------|----------------|-------------|---------------|
| **smoke_k8s** | REPLACE | snappass-test | -- | None |
| **sidecar** | REPLACE (5/7 tests) | snappass-test, juju-qa-pebble-notices, juju-qa-pebble-checks, sidecar-non-root | juju-qa-credential-get-k8s, sidecar-sudoer | credential-get action (optional) |
| **resources** | REPLACE | juju-qa-container-resource | -- | Version-based status verification, CharmHub publishing |
| **secrets_k8s** | PARTIAL REPLACE | snappass-test (user secrets target) | alertmanager-k8s (app/unit ownership via exec) | Shell in ROCK or create-secret action |
| **storage_k8s** | REPLACE | postgresql-k8s | -- | Test rewrite (storage names), but no charm changes |
| **ck** | PARTIAL (workload only) | snappass-test (CAAS workload) | CK bundle | None |
| **deploy_aks** | REPLACE (if re-enabled) | juju-qa-dummy-sink, juju-qa-dummy-source | -- | Need `calibration-requirer` as sink/source pair |
| **smoke_k8s_psql** | MUST NOT | -- | postgresql-k8s, postgresql-test-app | -- |
| **deploy_caas** | MUST NOT | -- | All 4 charms | -- |
| **caasadmission** | N/A | -- | (no charm) | -- |
| **controllercharm** | MUST NOT | -- | prometheus-k8s | -- |
| **coslite** | MUST NOT | -- | cos-lite bundle | -- |
| **dashboard** | MUST NOT | -- | juju-dashboard | -- |
| **kubeflow** | MUST NOT | -- | kubeflow bundle | -- |

### Charms Eliminated by norma-k8s

If norma-k8s replaces the above, these CharmHub/test charms are no longer needed:

| Charm | Suites Replaced In | Replacement Mechanism |
|-------|-------------------|----------------------|
| **snappass-test** | smoke_k8s, sidecar (2 tests), secrets_k8s (user secrets), ck | Deploy norma-k8s, `curl :8080/health` for HTTP verify |
| **juju-qa-pebble-notices** | sidecar | `trigger-notice` action or `juju ssh --container norma ... pebble notify` |
| **juju-qa-pebble-checks** | sidecar | `toggle-health` action, observe Pebble check-failed/recovered |
| **sidecar-non-root** (local) | sidecar | norma-k8s runs non-root by default (UID 584792) |
| **juju-qa-container-resource** | resources | Deploy with `--resource juju-norma-image=...`, `attach-resource`, `refresh` |
| **postgresql-k8s** | storage_k8s | norma-k8s `data` storage has same PV lifecycle |

**Total: 6 charms eliminated, covering 8+ test files across 6 suites.**

### Required Modifications for Full Coverage

| Modification | Effort | Enables | Priority |
|-------------|--------|---------|----------|
| **`credential-get` action** | Low (~30 LOC) | sidecar credential_get test | P3 -- niche test, can keep juju-qa-credential-get-k8s |
| **Sudoer variant overlay** | Low (new charmcraft-sudoer.yaml) | sidecar sudoer test | P3 -- security edge case |
| **Shell in ROCK** (busybox slice) or **`create-secret` action** | Low-Medium | secrets_k8s `juju exec` tests | P2 -- enables full secrets suite replacement |
| **CharmHub publishing** | CI/CD (no code) | resources `juju refresh --resource rev` test | P2 -- needed for production anyway |
| **`metrics-consumer` requires endpoint** | Medium (~100 LOC) | controllercharm Prometheus scrape replacement | P3 -- prometheus-k8s is canonical |
| **Config-driven status message** | Low (~10 LOC) | deploy_aks config verification (if re-enabled) | P4 -- dead code suite |

### Scenarios That MUST NOT Use norma-k8s

These scenarios test functionality that is inherently tied to specific applications, bundles, or Juju internals. Using a calibration charm would defeat the purpose of the test.

| Scenario | Reason |
|----------|--------|
| **Database relation writes** (smoke_k8s_psql) | Tests real data flow through `postgresql` interface. A calibration charm cannot simulate database operations -- the value is testing that actual SQL writes survive relation lifecycle. |
| **Multi-app orchestration** (deploy_caas) | Tests a 4-charm topology with 3 real-world relation interfaces (postgresql, redis, nginx-ingress). Replacing all 4 with norma-k8s instances would test self-relation, not real integration complexity. |
| **Controller metrics endpoint** (controllercharm) | Tests the Juju controller's built-in `metrics-endpoint` offer. The subject under test is the controller, not the workload charm. prometheus-k8s is the canonical consumer. |
| **Bundle deployment** (coslite, kubeflow, ck) | Tests Juju's ability to deploy and orchestrate complex bundles. The value is the bundle topology, not individual charm behavior. |
| **Dashboard relation** (dashboard) | Tests juju-dashboard's specific controller relation. Provider-agnostic, not K8s sidecar-related. |
| **Admission webhook** (caasadmission) | No charm involved. Pure K8s admission controller verification via kubectl. |
| **Vault secret drain** (secrets_k8s: drain tests) | Tests Juju's secret backend infrastructure with a real Vault instance. The charm is incidental -- `juju exec --unit` creates secrets inside any container. norma-k8s *can* serve as the target charm, but cannot replace the Vault backend. |
| **K8s API credential-get** (sidecar) | Tests `credential-get` hook tool which requires `--trust --scope=cluster`. While we *could* add this to norma-k8s, the test is specifically about K8s RBAC, not charm logic. The dedicated juju-qa-credential-get-k8s charm is cleaner. |

### Strategic Value

Replacing 6 charms across 6 suites with a single calibration charm provides:

1. **Reduced CharmHub dependency**: No breakage cascade when snappass-test, alertmanager-k8s, or other external charms change their interface or behavior. The calibration charm is pinned and controlled.
2. **Faster CI**: norma-k8s (single static Go binary) starts in ~5s vs snappass-test (Redis + Flask stack) in ~30s+. Per-test savings multiply across suites.
3. **Deeper verification**: Instead of just "did it deploy?", norma-k8s's introspect action lets tests verify internal state: event ledger, relation data, storage markers, container connectivity, secret grants -- all from a single `juju run` call.
4. **Unified test vocabulary**: All replaced suites use the same actions, config options, and status patterns. Test scripts become simpler and more consistent.
5. **Regression detection**: The event ledger captures every Juju event with metadata. When a Juju upgrade changes event ordering or drops events, the ledger exposes it immediately.
