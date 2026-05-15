#!/usr/bin/env bash
set -euo pipefail

# Determine repo root (directory containing this script's parent)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEST="$REPO_ROOT/target/supersplat"
SUPERSPLAT_REPO="https://github.com/playcanvas/supersplat"
SUPERSPLAT_REF="main"

echo "==> Checking prerequisites..."
command -v node >/dev/null 2>&1 || { echo "ERROR: node not found. Install: brew install node"; exit 1; }
command -v npm  >/dev/null 2>&1 || { echo "ERROR: npm not found. Install: brew install node"; exit 1; }
echo "    node $(node --version), npm $(npm --version)"

echo "==> Setting up SuperSplat at $DEST..."
if [ -d "$DEST/.git" ]; then
    echo "    Repo exists — updating..."
    git -C "$DEST" fetch --quiet origin
    git -C "$DEST" checkout "$SUPERSPLAT_REF" --quiet
    git -C "$DEST" pull --quiet origin "$SUPERSPLAT_REF"
else
    echo "    Cloning..."
    mkdir -p "$(dirname "$DEST")"
    git clone --depth 1 "$SUPERSPLAT_REPO" "$DEST" --quiet
fi

echo "==> Installing npm dependencies..."
cd "$DEST"
npm ci --prefer-offline --loglevel=warn

echo "==> Building SuperSplat..."
npm run build

echo "==> Verifying build..."
[ -f "$DEST/dist/index.html" ] || { echo "ERROR: dist/index.html missing after build — check npm run build output"; exit 1; }

echo ""
echo "SuperSplat built successfully."
echo "dist: $DEST/dist/"
echo ""
echo "Start viewing with:"
echo "  autosplat serve <capture_dir> --with-supersplat"
