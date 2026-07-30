#!/usr/bin/env bash
# Deploy the viewer/ subtree to pages.jkaindl.de.
#
# Takes a clean snapshot of viewer/ from committed HEAD (git archive — the
# working tree is deliberately NOT deployed) and rsyncs it to the pages server
# (/srv/pages/autosplat/, served at https://pages.jkaindl.de/autosplat/).
# Replaces the old Codeberg Pages flow (subtree split + pages-branch push).
#
# Repo meta files (AGENTS.md, docs/, tests/, .gitea/, …) are excluded — they
# were part of the old pages branch but have no business on the public site.
# The service worker precaches only html/css/js/assets/icons, so the excludes
# cannot break the PWA shell.
#
# Auth is via the dedicated deploy key behind the `pages-deploy` SSH host alias
# (~/.ssh/config) — restricted server-side to rsync into /srv/pages only.
#
# Requires real rsync 3.x — macOS ships openrsync, which is incompatible with
# the server-side rrsync wrapper: brew install rsync
#
# Usage: scripts/deploy-pages.sh

set -euo pipefail

RSYNC="${RSYNC:-/opt/homebrew/bin/rsync}"
# No pipe here: grep -q + pipefail would turn rsync's SIGPIPE into a failure.
case "$("$RSYNC" --version 2>/dev/null || true)" in
  *"version 3."*) ;;
  *)
    echo "ERROR: $RSYNC is not rsync 3.x (macOS openrsync won't work): brew install rsync" >&2
    exit 1
    ;;
esac

DEST="pages-deploy:autosplat/"

cd "$(git rev-parse --show-toplevel)"

if [[ -n "$(git status --porcelain -- viewer/)" ]]; then
  echo "NOTE: viewer/ has uncommitted changes — deploying committed HEAD, not the working tree." >&2
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "→ snapshot viewer/ from HEAD"
git archive HEAD viewer/ | tar -x -C "$STAGE"

echo "→ rsync to $DEST"
"$RSYNC" -az --delete --chmod=D755,F644 \
  --exclude 'AGENTS.md' --exclude 'CHANGELOG.md' --exclude 'CITATION.cff' \
  --exclude 'CLA.md' --exclude 'CONTRIBUTING.md' --exclude 'LICENSING.md' \
  --exclude 'README.md' --exclude 'SECURITY.md' \
  --exclude 'docs/' --exclude 'tests/' --exclude '.gitea/' \
  --exclude 'serve.sh' --exclude 'package.json' \
  "$STAGE/viewer/" "$DEST"

echo "✓ deployed. Live: https://pages.jkaindl.de/autosplat/"
