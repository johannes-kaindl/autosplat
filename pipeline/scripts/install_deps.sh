#!/usr/bin/env bash
# Install all system dependencies for auto-splat-pipeline.
# macOS / Apple Silicon only.

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { printf '\033[1;36m[install_deps]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[install_deps]\033[0m %s\n' "$*" >&2; exit 1; }

# Platform check
if [[ "$(uname -s)" != "Darwin" ]]; then
    fail "auto-splat-pipeline is Mac-only. Detected: $(uname -s)"
fi
if [[ "$(uname -m)" != "arm64" ]]; then
    log "Warning: not running on Apple Silicon (uname -m=$(uname -m)). Brush requires Mac-Silicon."
fi

# Homebrew check
if ! command -v brew >/dev/null 2>&1; then
    fail "Homebrew not installed. See https://brew.sh"
fi

log "Installing system dependencies via Homebrew..."
brew install ffmpeg colmap python@3.11 uv

log "Fetching Brush binary..."
"${SCRIPT_DIR}/fetch_brush.sh"

log "Syncing Python dependencies via uv..."
cd "${REPO_ROOT}"
uv sync

log "Running doctor..."
uv run autosplat doctor || {
    log "Doctor reported missing deps — review the table above."
    exit 3
}

log "Done. Try: uv run autosplat process <video>"
