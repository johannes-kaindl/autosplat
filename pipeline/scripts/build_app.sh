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
# A previously-mounted AutoSplat.dmg volume holds dist/ busy → detach it first.
if [[ -d "/Volumes/AutoSplat" ]]; then
  hdiutil detach "/Volumes/AutoSplat" >/dev/null 2>&1 || true
fi
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
# create-dmg intermittently fails to eject its temp volume (Spotlight race:
# "volume in use"). Retry a couple of times, detaching any stragglers first.
make_dmg() {
  rm -f "${DMG}"
  create-dmg \
    --volname "AutoSplat" \
    --window-size 540 360 \
    --icon-size 100 \
    --icon "AutoSplat.app" 140 180 \
    --app-drop-link 400 180 \
    --no-internet-enable \
    "${DMG}" "${APP}"
}
dmg_ok=""
for attempt in 1 2 3; do
  if make_dmg; then dmg_ok=1; break; fi
  log "create-dmg attempt ${attempt} failed — detaching stray volume and retrying…"
  hdiutil detach "/Volumes/AutoSplat" -force >/dev/null 2>&1 || true
  sleep 2
done
[[ -n "${dmg_ok}" ]] || fail "create-dmg failed after 3 attempts"

if [[ -n "${CODESIGN_IDENTITY:-}" && -n "${AC_NOTARY_PROFILE:-}" ]]; then
  log "Notarizing DMG (profile: ${AC_NOTARY_PROFILE})…"
  xcrun notarytool submit "${DMG}" --keychain-profile "${AC_NOTARY_PROFILE}" --wait
  xcrun stapler staple "${DMG}"
else
  log "Skipping notarization (need CODESIGN_IDENTITY + AC_NOTARY_PROFILE)."
  log "Recipients clear quarantine once: xattr -dr com.apple.quarantine /Applications/AutoSplat.app"
fi

log "Done → ${DMG}"
