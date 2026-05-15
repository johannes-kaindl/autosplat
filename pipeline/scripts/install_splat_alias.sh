#!/usr/bin/env bash
# DEPRECATED — use scripts/install_splat.sh instead.
# Installs a zsh shell function, which is not execvp/nohup/caffeinate-compatible.
# Kept for reference; will be removed in a future release.
# install_splat_alias.sh — adds a `splat` shell function to ~/.zshrc
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZSHRC="${HOME}/.zshrc"

BLOCK="
# autosplat — added by scripts/install_splat_alias.sh
splat() { (cd \"${REPO_DIR}\" && uv run autosplat \"\$@\"); }
"

if grep -q "splat() {" "${ZSHRC}" 2>/dev/null; then
    echo "splat function already present in ${ZSHRC} — skipping"
else
    echo "${BLOCK}" >> "${ZSHRC}"
    echo "Added splat() function to ${ZSHRC}"
    echo "Run: source ${ZSHRC}   (or open a new shell)"
fi
