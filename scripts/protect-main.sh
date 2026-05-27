#!/usr/bin/env bash
# protect-main.sh
#
# Apply minimal branch protection to `main`:
#   - block force-push
#   - block branch deletion
#
# Leaves direct pushes and admin overrides open — appropriate for
# solo-developer or small-team workflows. Tighten later by editing
# the JSON body below (set required_pull_request_reviews / required_
# status_checks to enforce PR + CI gates).
#
# Requires: gh CLI authenticated against an account with admin access
# on the target repository.

set -euo pipefail

REPO="${1:-sinanawad/juju-norma-k8s}"
BRANCH="${2:-main}"

echo "==> Applying branch protection to ${REPO}@${BRANCH}"

echo '{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}' | gh api -X PUT "/repos/${REPO}/branches/${BRANCH}/protection" --input - >/dev/null

echo "==> Verifying"
gh api "/repos/${REPO}/branches/${BRANCH}/protection" \
  --jq '{allow_force_pushes: .allow_force_pushes.enabled, allow_deletions: .allow_deletions.enabled, enforce_admins: .enforce_admins.enabled}'

echo "==> Done. To undo: gh api -X DELETE /repos/${REPO}/branches/${BRANCH}/protection"
