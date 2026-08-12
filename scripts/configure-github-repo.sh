#!/usr/bin/env bash
# Configure the public GitHub repository after authenticating `gh`.
#
# Usage:
#   gh auth login
#   scripts/configure-github-repo.sh
set -euo pipefail

REPO="${1:-gmogmzGithub/maia-agent}"
DESCRIPTION="Hermes-backed real estate lead agent for WhatsApp qualification, appointment scheduling, and auditable follow-up workflows."

echo "==> Setting repository description"
gh repo edit "$REPO" \
  --description "$DESCRIPTION"

echo "==> Protecting main"
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "/repos/$REPO/branches/main/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["tests"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": true
}
JSON

echo "GitHub repository configuration complete for $REPO."
