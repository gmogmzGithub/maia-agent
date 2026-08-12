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
  --description "$DESCRIPTION" \
  --visibility public

echo "==> Protecting main"
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "/repos/$REPO/branches/main/protection" \
  -f required_pull_request_reviews='{"required_approving_review_count":1,"dismiss_stale_reviews":true,"require_code_owner_reviews":false}' \
  -f required_status_checks='{"strict":true,"contexts":["tests"]}' \
  -f enforce_admins=true \
  -f restrictions=null \
  -f required_linear_history=true \
  -f allow_force_pushes=false \
  -f allow_deletions=false \
  -f block_creations=false \
  -f required_conversation_resolution=true \
  -f lock_branch=false \
  -f allow_fork_syncing=true

echo "GitHub repository configuration complete for $REPO."
