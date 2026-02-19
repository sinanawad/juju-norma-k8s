# CI/CD and Tooling Reference

## Complete charmcraft.yaml Reference

```yaml
type: charm
name: norma-k8s
title: Norma
summary: A short one-line summary (max 78 chars)
description: |
  Extended description for Charmhub.

base: ubuntu@24.04
platforms:
  amd64:

parts:
  norma-charm:
    plugin: uv
    source: .
    build-packages: [git]
    build-snaps: [astral-uv]
    override-build: |
      craftctl default
      git describe --always > $CRAFT_PART_INSTALL/version

assumes:
  - juju >= 3.6
  - k8s-api

containers:
  norma:
    resource: norma-image
    uid: 10000
    gid: 10000
    mounts:
      - storage: data
        location: /var/lib/norma

resources:
  norma-image:
    type: oci-image
    upstream-source: ghcr.io/myorg/juju-norma:latest
    description: OCI image for the Norma application

storage:
  data:
    type: filesystem
    minimum-size: 1G

config:
  options:
    log-level:
      type: string
      default: "info"
      description: "Logging level (debug, info, warning, error)"
    port:
      type: int
      default: 8080
      description: "Port the application listens on"

actions:
  backup:
    description: "Trigger a backup"
    params:
      target:
        type: string
        description: "Backup target path"

peers:
  norma-peers:
    interface: norma_peers

provides:
  metrics-endpoint:
    interface: prometheus_scrape
  grafana-dashboard:
    interface: grafana_dashboard
  profiling-endpoint:
    interface: parca_scrape

requires:
  database:
    interface: postgresql_client
    optional: false
    limit: 1
  ingress:
    interface: ingress
    optional: true
    limit: 1
  log-proxy:
    interface: loki_push_api
    optional: true
    limit: 1
  certificates:
    interface: tls-certificates
    optional: true
    limit: 1

charm-libs:
  - lib: charms.data_platform_libs.v0.data_interfaces
    version: "0"
  - lib: charms.traefik_k8s.v2.ingress
    version: "2"
  - lib: charms.prometheus_k8s.v0.prometheus_scrape
    version: "0"
  - lib: charms.grafana_k8s.v0.grafana_dashboard
    version: "0"
  - lib: charms.loki_k8s.v0.loki_push_api
    version: "0"
  - lib: charms.parca_k8s.v0.parca_scrape
    version: "0"

charm-user: non-root

links:
  documentation: https://discourse.charmhub.io/t/norma-docs
  source:
    - https://github.com/myorg/norma-k8s-operator
  issues:
    - https://github.com/myorg/norma-k8s-operator/issues
```

## pyproject.toml Reference

```toml
[project]
name = "norma-k8s"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["ops", "pydantic"]

[project.optional-dependencies]
dev = [
    "ops[testing]",
    "coverage[toml]",
    "pytest",
    "ruff",
    "jubilant",
]

[tool.ruff]
line-length = 99
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B", "S"]

[tool.coverage.run]
source = ["src"]

[tool.coverage.report]
show_missing = true
```

## Makefile Reference (replaces tox.ini)

```makefile
.PHONY: lint unit integration pack clean

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

format:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

unit:
	PYTHONPATH=src:lib uv run coverage run \
		--source=src -m pytest tests/unit -v
	uv run coverage report

integration:
	uv run pytest tests/integration -v \
		--log-cli-level=INFO -s $(ARGS)

pack:
	charmcraft pack

fetch-libs:
	charmcraft fetch-libs

clean:
	rm -rf *.charm __pycache__ .coverage .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

generate-requirements:
	uv pip compile pyproject.toml -o requirements.txt
```

## GitHub Actions Workflows

### PR Workflow (build-and-test.yaml)

Key jobs:
1. **lint**: `make lint`
2. **unit-test**: `make unit`
3. **lib-check**: `canonical/charming-actions/check-libraries`
4. **pack**: `charmcraft pack`
5. **integration**: `make integration` (against MicroK8s)

### Release Workflow (release.yaml)

Trigger: push to main
1. Run full build-and-test
2. `canonical/charming-actions/release-libraries`
3. `canonical/charming-actions/channel` (determine channel)
4. `canonical/charming-actions/upload-charm`

### OCI Workflow (publish-oci.yaml)

Trigger: rockcraft.yaml changes
1. Build ROCK with rockcraft
2. Push to ghcr.io
3. Create PR to update charmcraft.yaml resource ref

### Auto-Update Workflows

- **update-libs.yaml**: Weekly Monday, `charmcraft fetch-lib`, auto-PR
- **update-oci.yaml**: Weekly Monday, check upstream releases, auto-PR

### Dependabot Config

```yaml
# .github/dependabot.yaml
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
  - package-ecosystem: uv
    directory: /
    schedule:
      interval: weekly
```

## rockcraft.yaml (Chiselled ROCK)

Key patterns from zinc-k8s:
```yaml
name: norma
version: "0.1.0"
base: bare                    # Distroless
build-base: ubuntu@24.04
run_user: _daemon_            # Non-root execution

# Multi-stage build:
# 1. Build application from source
# 2. Install go-runner for log forwarding (if needed)
# 3. Minimal runtime: libc6_libs + ca-certificates_data only
```

## charmcraft Commands Reference

| Command | Purpose |
|---|---|
| `charmcraft init --profile kubernetes` | Scaffold new K8s charm |
| `charmcraft pack` | Build .charm file |
| `charmcraft upload charm.charm` | Upload to Charmhub |
| `charmcraft release name --revision=N --channel=edge` | Release |
| `charmcraft create-lib mylib` | Create new library |
| `charmcraft publish-lib charms.name.v0.mylib` | Publish library |
| `charmcraft fetch-libs` | Download/update all declared libs |
| `charmcraft list-lib name` | List published libraries |
| `charmcraft analyse` | Run linters on charm |

## Development Workflow

```bash
# 1. Initialize
charmcraft init --profile kubernetes --name norma-k8s

# 2. Fetch libraries
charmcraft fetch-libs

# 3. Develop and test
make lint
make unit

# 4. Build and integration test
charmcraft pack
CHARM_PATH=./norma-k8s_ubuntu-24.04-amd64.charm make integration

# 5. Deploy
juju deploy ./norma-k8s_ubuntu-24.04-amd64.charm \
    --resource norma-image=ghcr.io/myorg/juju-norma:latest

# 6. Monitor
juju status --watch 2s
```
