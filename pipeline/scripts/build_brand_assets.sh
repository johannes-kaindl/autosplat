#!/usr/bin/env bash
# Regenerate static brand assets (favicon/app-icon/OG) from the generative
# brand system. Run after editing docs/brand/render_marks.mjs or marks.js.
#
#   ./scripts/build_brand_assets.sh
#
# Needs: node, rsvg-convert (brew install librsvg), iconutil + sips (macOS).

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly BRAND="${REPO_ROOT}/src/autosplat/webui/static/brand"

log() { printf '\033[1;36m[brand]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[brand]\033[0m %s\n' "$*" >&2; exit 1; }

command -v rsvg-convert >/dev/null 2>&1 || fail "rsvg-convert missing — brew install librsvg"
command -v iconutil >/dev/null 2>&1 || fail "iconutil missing (macOS only)"

log "Rendering SVG marks…"
node "${REPO_ROOT}/docs/brand/render_marks.mjs"

log "Rasterizing favicon + web icons…"
rsvg-convert -w 32 -h 32 "${BRAND}/mark.svg" -o "${BRAND}/favicon-32.png"
rsvg-convert -w 180 -h 180 "${BRAND}/mark.svg" -o "${BRAND}/apple-touch-icon.png"
rsvg-convert -w 512 -h 512 "${BRAND}/mark.svg" -o "${BRAND}/icon-512.png"

log "Rasterizing OG image (1200×630)…"
rsvg-convert -w 1200 -h 630 "${BRAND}/og.svg" -o "${BRAND}/og.png"

log "Building macOS .icns for the app bundle…"
ICONSET="$(mktemp -d)/AutoSplat.iconset"
mkdir -p "${ICONSET}"
for sz in 16 32 64 128 256 512 1024; do
  rsvg-convert -w "${sz}" -h "${sz}" "${BRAND}/mark.svg" -o "${ICONSET}/icon_${sz}x${sz}.png"
done
# Retina @2x names Apple expects (reuse the larger renders)
cp "${ICONSET}/icon_32x32.png"   "${ICONSET}/icon_16x16@2x.png"
cp "${ICONSET}/icon_64x64.png"   "${ICONSET}/icon_32x32@2x.png"
cp "${ICONSET}/icon_256x256.png" "${ICONSET}/icon_128x128@2x.png"
cp "${ICONSET}/icon_512x512.png" "${ICONSET}/icon_256x256@2x.png"
cp "${ICONSET}/icon_1024x1024.png" "${ICONSET}/icon_512x512@2x.png"
rm -f "${ICONSET}/icon_64x64.png"  # not a standard iconset slot
iconutil -c icns "${ICONSET}" -o "${REPO_ROOT}/packaging/AutoSplat.icns"

log "Done. Assets in ${BRAND} + packaging/AutoSplat.icns"
