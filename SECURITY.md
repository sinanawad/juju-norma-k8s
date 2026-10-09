# Security Policy

`juju-norma-k8s` is a **sterile Kubernetes-charm calibration harness** for Juju CI —
not a production service. It ships no credentials and stores no user data; its
workload is a throwaway HTTP server. Some workload endpoints are intentionally
unauthenticated, and the charm has deliberate misbehaviour modes for testing
(see `docs/BEHAVIOR-MODES.md`). These test-bed affordances **must not** be copied
into a production charm.

## Reporting a vulnerability

Please report security issues — especially anything that could affect the Juju
engine or CI it calibrates — privately via
[GitHub Security Advisories](https://github.com/sinanawad/juju-norma-k8s/security/advisories/new)
rather than a public issue.

We aim to acknowledge reports within a few working days.

## Supported versions

This charm tracks the `main` branch against Juju 3.6+ and 4.0+. Fixes land on
`main`; there are no long-lived support branches.
