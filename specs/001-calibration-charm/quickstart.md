# Quickstart: norma-k8s Calibration Charm

## Prerequisites

- Juju 3.6+ with a K8s cloud (MicroK8s recommended)
- Go 1.22+ (for building the workload binary)
- `charmcraft` (snap)
- `rockcraft` (snap)
- `uv` (for Python dependency management)
- `docker` or `skopeo` (for OCI image management)

## Build the Workload

```bash
# Build the Go binary
cd workload/
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o norma .
cd ..

# Build the ROCK image
rockcraft pack
# Upload to local registry or ghcr.io
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
juju deploy ./norma-k8s_ubuntu-24.04-amd64.charm \
    --resource norma-image=ghcr.io/canonical/norma:latest \
    --trust

# Watch status
juju status --watch 2s
```

## Verify Basic Operation

```bash
# Check lifecycle events fired correctly
juju run norma-k8s/0 get-event-log

# Check config
juju run norma-k8s/0 get-config

# Check version
juju run norma-k8s/0 get-version

# Check security posture
juju run norma-k8s/0 check-security
```

## Test Individual Features

Each user story is independently testable:

```bash
# US1: Lifecycle events
juju run norma-k8s/0 get-event-log

# US2: Pebble workload
juju run norma-k8s/0 run-check check=pebble

# US3: Configuration
juju config norma-k8s calibration-string="test"
juju config norma-k8s calibration-int=9090
juju run norma-k8s/0 get-config

# US4: Status reporting
juju run norma-k8s/0 set-status status=blocked message="test block"
juju status

# US5: Actions
juju run norma-k8s/0 fail-action message="expected failure"

# US6: Peer relations (scale first)
juju scale-application norma-k8s 3
juju run norma-k8s/0 get-peer-data

# US7: Provides/requires relations (self-relation)
juju integrate norma-k8s:calibration-provider norma-k8s:calibration-requirer
juju run norma-k8s/0 get-relation-data endpoint=calibration-provider

# US8: Scaling
juju run norma-k8s/0 get-cluster-info

# US9: Secrets
juju run norma-k8s/0 get-secret-info

# US10: Storage
juju run norma-k8s/0 check-storage

# US11: Health checks
juju run norma-k8s/0 toggle-health
# Wait for pebble-check-failed, then:
juju run norma-k8s/0 toggle-health
# Wait for pebble-check-recovered

# US12: Pebble file/exec ops
juju run norma-k8s/0 test-pebble-ops

# US13: Custom notices
juju run norma-k8s/0 trigger-notice

# US14: Networking
juju run norma-k8s/0 test-networking

# US15: Upgrade
# Build a new revision, then:
juju refresh norma-k8s --path=./norma-k8s_ubuntu-24.04-amd64.charm
juju run norma-k8s/0 get-version

# US16: Multiple containers
juju run norma-k8s/0 test-pebble-ops container=norma-secondary

# US17: Security
juju run norma-k8s/0 check-security

# US18: COS (requires COS charms deployed)
juju integrate norma-k8s:metrics-endpoint prometheus-k8s:metrics-endpoint

# US19: Cross-model relations (requires second model)
juju offer norma-k8s:calibration-provider

# US20: Event deferral
juju run norma-k8s/0 test-defer arm=true
juju config norma-k8s calibration-string="trigger-defer"
juju run norma-k8s/0 get-event-log event-filter=defer

# US21: OCI Resource Lifecycle
# Build a new ROCK image version, then:
juju attach-resource norma-k8s norma-image=ghcr.io/canonical/norma:v2
juju run norma-k8s/0 get-version
juju run norma-k8s/0 get-event-log event-filter=pebble-ready
```

## Run Integration Tests

```bash
charmcraft pack
CHARM_PATH=./norma-k8s_ubuntu-24.04-amd64.charm make integration
```

## Clean Up

```bash
juju remove-application norma-k8s --force
make clean
```
