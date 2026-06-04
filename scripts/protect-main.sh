#!/usr/bin/env bash
# protect-main.sh
#
# Apply branch protection to `main`:
#   - block force-push + branch deletion
#   - REQUIRE the fast, deterministic CI checks to pass before merge
#     (Lint, Unit Tests, Pack Charm, Build ROCK) — this is what makes
#     `gh pr merge --auto` actually gate on green.
#
# Notes:
#   - The slow self-hosted integration job is intentionally NOT required
#     (runner availability would block merges); verify it out-of-band.
#   - `enforce_admins:false` lets an admin override in emergencies, but
#     auto-merge still waits for the required checks.
#   - `required_pull_request_reviews:null` keeps solo self-merge working.
#   - `strict:false` avoids forcing every branch up-to-date before merge.
#
# Requires: gh CLI authenticated against an account with admin access
# on the target repository.

set -euo pipefail

REPO="${1:-sinanawad/juju-norma-k8s}"
BRANCH="${2:-main}"

echo "==> Applying branch protection to ${REPO}@${BRANCH}"

echo '{
  "required_status_checks": {
    "strict": false,
    "contexts": ["Lint", "Unit Tests", "Check Libraries", "Pack Charm", "Build ROCK"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}' | gh api -X PUT "/repos/${REPO}/branches/${BRANCH}/protection" --input - >/dev/null

echo "==> Verifying"
gh api "/repos/${REPO}/branches/${BRANCH}/protection" \
  --jq '{required_checks: .required_status_checks.contexts, allow_force_pushes: .allow_force_pushes.enabled, allow_deletions: .allow_deletions.enabled, enforce_admins: .enforce_admins.enabled}'

echo "==> Done. To undo: gh api -X DELETE /repos/${REPO}/branches/${BRANCH}/protection"
