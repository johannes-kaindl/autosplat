#!/usr/bin/env bash
# Build AutoSplat.app and AutoSplat.dmg.
#
# Signing/notarization are OPTIONAL and env-gated:
#   CODESIGN_IDENTITY   — "Developer ID Application: …"; if set, the .app is signed.
#   AC_NOTARY_PROFILE   — notarytool keychain profile; if set (and signed), notarize+staple.
# Unset → an ad-hoc signature is applied so the bundle launches locally, and the
# DMG ships unsigned (open via right-click → Open on other Macs).
#
# Usage:  ./scripts/build_app.sh

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly APP="${REPO_ROOT}/dist/AutoSplat.app"
readonly DMG="${REPO_ROOT}/dist/AutoSplat.dmg"

log() { printf '\033[1;36m[build_app]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[build_app]\033[0m %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || fail "AutoSplat.app builds on macOS only."

command -v create-dmg >/dev/null 2>&1 || fail "create-dmg missing — 'brew install create-dmg'"
uv run --group build python -c "import PyInstaller" 2>/dev/null \
  || fail "PyInstaller missing — 'uv sync --group build'"

cd "${REPO_ROOT}"

log "Cleaning previous build…"
rm -rf build dist

log "Freezing app with PyInstaller…"
uv run --group build pyinstaller --noconfirm --clean packaging/AutoSplat.spec

[[ -d "${APP}" ]] || fail "PyInstaller did not produce ${APP}"

if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  log "Signing with Developer ID: ${CODESIGN_IDENTITY}"
  codesign --force --deep --options runtime --sign "${CODESIGN_IDENTITY}" "${APP}"
else
  log "No CODESIGN_IDENTITY — applying ad-hoc signature (local-launch only)."
  codesign --force --deep --sign - "${APP}"
fi

log "Building DMG…"
rm -f "${DMG}"
create-dmg \
  --volname "AutoSplat" \
  --window-size 540 360 \
  --icon-size 100 \
  --icon "AutoSplat.app" 140 180 \
  --app-drop-link 400 180 \
  --no-internet-enable \
  "${DMG}" "${APP}" \
  || fail "create-dmg failed"

if [[ -n "${CODESIGN_IDENTITY:-}" && -n "${AC_NOTARY_PROFILE:-}" ]]; then
  log "Notarizing DMG (profile: ${AC_NOTARY_PROFILE})…"
  xcrun notarytool submit "${DMG}" --keychain-profile "${AC_NOTARY_PROFILE}" --wait
  xcrun stapler staple "${DMG}"
else
  log "Skipping notarization (need CODESIGN_IDENTITY + AC_NOTARY_PROFILE)."
  log "Recipients open the unsigned app via right-click → Open (once)."
fi

log "Done → ${DMG}"
