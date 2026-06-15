#!/usr/bin/env bash
# Deploy the viewer/ subtree to the Codeberg Pages branch of the monorepo.
#
# Codeberg Pages publishes from the `pages` branch. We split the viewer/ subtree
# out of the current commit and force-push it there (the pages branch is a pure
# deploy artifact — force-push is fine).
#
# Usage: scripts/deploy-pages.sh [remote]    (default remote: origin)

set -euo pipefail

REMOTE="${1:-origin}"
SUBDIR="viewer"
PAGES_BRANCH="pages"

cd "$(git rev-parse --show-toplevel)"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "✗ working tree not clean — commit or stash before deploying." >&2
  exit 1
fi

echo "→ git subtree split --prefix $SUBDIR HEAD"
SPLIT_SHA="$(git subtree split --prefix "$SUBDIR" HEAD)"
echo "  split commit: $SPLIT_SHA"

echo "→ force-push $SPLIT_SHA → $REMOTE/$PAGES_BRANCH"
git push --force "$REMOTE" "${SPLIT_SHA}:refs/heads/${PAGES_BRANCH}"

echo "✓ deployed. Live: https://jkaindl.codeberg.page/autosplat/"
