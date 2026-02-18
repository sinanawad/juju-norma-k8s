# Quickstart: juju-norma-k8s Calibration Charm

## Prerequisites

- Juju 3.6+ with a K8s cloud (MicroK8s recommended)
- Go 1.22+ (for building the workload binary)
- `charmcraft` (snap)
- `rockcraft` (snap)
- `uv` (for Python dependency management)
- `podman` or `skopeo` (for OCI image management)

## Build the Workload

```bash
# Build the Go binary
cd workload/
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o norma .
cd ..

# Build the ROCK image
rockcraft pack
# Upload to local registry
rockcraft.skopeo --insecure-policy copy \
    oci-archive:norma_0.1.0_amd64.rock \
    docker://localhost:32000/norma:0.1.0 \
    --dest-tls-verify=false
```

## Build the Charm

```bash
# Install Python dependencies
uv sync

# Fetch charm libraries
charmcraft fetch-libs

# Lint
make lint

# Run unit tests
make unit

# Pack the charm
charmcraft pack
```

## Deploy

```bash
# Deploy with the OCI resource
juju deploy ./juju-norma-k8s_ubuntu-24.04-amd64.charm \
    --resource juju-norma-image=localhost:32000/norma:0.1.0 \
    --trust

# Watch status
juju status --watch 2s
```

## Verify Basic Operation

```bash
# Check lifecycle events fired correctly
juju run juju-norma-k8s/0 get-event-log

# Check config
juju run juju-norma-k8s/0 get-config

# Check version
juju run juju-norma-k8s/0 get-version

# Check security posture
juju run juju-norma-k8s/0 check-security

# Full introspection
juju run juju-norma-k8s/0 introspect
```

## Test Individual Features

Each user story is independently testable:

```bash
# US1: Lifecycle events
juju run juju-norma-k8s/0 get-event-log

# US2: Pebble workload
juju run juju-norma-k8s/0 run-check check=pebble

# US3: Configuration
juju config juju-norma-k8s calibration-string="test"
juju config juju-norma-k8s calibration-int=9090
juju run juju-norma-k8s/0 get-config

# US4: Status reporting
juju run juju-norma-k8s/0 set-status status=blocked message="test block"
juju status

# US5: Actions
juju run juju-norma-k8s/0 fail-action message="expected failure"

# US6: Peer relations (scale first)
juju scale-application juju-norma-k8s 3
juju run juju-norma-k8s/0 get-peer-data

# US7: Provides/requires relations (two-instance pattern)
juju deploy ./juju-norma-k8s_ubuntu-24.04-amd64.charm norma-peer \
    --resource juju-norma-image=localhost:32000/norma:0.1.0
juju integrate juju-norma-k8s:calibration-provider norma-peer:calibration-requirer
juju run juju-norma-k8s/0 get-relation-data endpoint=calibration-provider

# US8: Scaling
juju run juju-norma-k8s/0 get-cluster-info

# US9: Secrets
juju run juju-norma-k8s/0 get-secret-info

# US10: Storage
juju run juju-norma-k8s/0 check-storage
juju run juju-norma-k8s/0 check-storage name=logs

# US11: Health checks
juju run juju-norma-k8s/0 toggle-health
# Wait for pebble-check-failed, then:
juju run juju-norma-k8s/0 toggle-health
# Wait for pebble-check-recovered

# US12: Pebble file/exec ops
juju run juju-norma-k8s/0 test-pebble-ops

# US13: Custom notices
juju run juju-norma-k8s/0 trigger-notice

# US14: Networking & Expose
juju run juju-norma-k8s/0 test-networking
juju expose juju-norma-k8s
juju run juju-norma-k8s/0 test-networking  # should show exposed=true
juju unexpose juju-norma-k8s

# US15: Upgrade
# Build a new revision, then:
juju refresh juju-norma-k8s --path=./juju-norma-k8s_ubuntu-24.04-amd64.charm
juju run juju-norma-k8s/0 get-version

# US16: Multiple containers
juju run juju-norma-k8s/0 test-pebble-ops container=norma-secondary

# US17: Security
juju run juju-norma-k8s/0 check-security

# US18: COS (requires COS charms deployed)
juju integrate juju-norma-k8s:metrics-endpoint prometheus-k8s:metrics-endpoint

# US19: Cross-model relations (requires second model)
juju offer juju-norma-k8s:calibration-provider

# US20: Event deferral
juju run juju-norma-k8s/0 test-defer arm=true
juju config juju-norma-k8s calibration-string="trigger-defer"
juju run juju-norma-k8s/0 get-event-log event-filter=defer

# US21: OCI Resource Lifecycle
juju attach-resource juju-norma-k8s juju-norma-image=localhost:32000/norma:v2
juju run juju-norma-k8s/0 get-version

# US22: Introspection (includes goal-state)
juju run juju-norma-k8s/0 introspect
juju run juju-norma-k8s/0 introspect sections=config,relations,goal-state

# US24: Multiple storage
juju add-storage juju-norma-k8s/0 logs=1
juju run juju-norma-k8s/0 check-storage name=logs

# US25: Subordinate charm integration
# Pack the subordinate variant:
charmcraft pack --project-dir . -c charmcraft-subordinate.yaml
juju deploy ./juju-norma-k8s-subordinate_ubuntu-24.04-amd64.charm norma-sub
juju integrate juju-norma-k8s:juju-info norma-sub:juju-info
juju run juju-norma-k8s/0 introspect sections=relations

# Juju operations on K8s charms:
# SSH into pod
juju ssh juju-norma-k8s/0 -- ls /bin/norma

# Update-status interval
juju model-config update-status-hook-interval=30s
# Wait 90s, then:
juju run juju-norma-k8s/0 get-event-log event-filter=update-status

# Deploy with constraints
juju deploy ./juju-norma-k8s_ubuntu-24.04-amd64.charm norma-constrained \
    --resource juju-norma-image=localhost:32000/norma:0.1.0 \
    --constraints "mem=512M cores=1"

# Model migration (requires second controller)
# juju migrate <model> <target-controller>
```

## Run Integration Tests

```bash
charmcraft pack
CHARM_PATH=./juju-norma-k8s_ubuntu-24.04-amd64.charm make integration
```

## Run Integration Tests (Self-Contained)

```bash
# On a fresh Ubuntu 24.04 machine — installs microk8s, juju, bootstraps controller
SETUP_ENVIRONMENT=1 make integration
```

## Clean Up

```bash
juju remove-application juju-norma-k8s --force
make clean
```
