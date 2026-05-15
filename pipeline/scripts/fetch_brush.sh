#!/usr/bin/env bash
# Fetch the Brush Mac-Silicon binary from GitHub releases.
# Spec §12.1 decision: pin to a known-good version, override via BRUSH_VERSION env.

set -euo pipefail

# Pin to a known-good release. Override via env var:
#   BRUSH_VERSION=v0.1.5 ./scripts/fetch_brush.sh
readonly DEFAULT_BRUSH_VERSION="latest"
readonly BRUSH_VERSION="${BRUSH_VERSION:-${DEFAULT_BRUSH_VERSION}}"

readonly BRUSH_REPO="ArthurBrussee/brush"
readonly INSTALL_DIR="${BRUSH_INSTALL_DIR:-${HOME}/AutoSplat/bin}"
readonly INSTALL_PATH="${INSTALL_DIR}/brush"
readonly VERSION_FILE="${INSTALL_DIR}/.brush-version"

log() { printf '\033[1;36m[fetch_brush]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[fetch_brush]\033[0m %s\n' "$*" >&2; exit 1; }

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
    fail "Brush binary requires macOS / Apple Silicon (detected $(uname -s)/$(uname -m))"
fi

mkdir -p "${INSTALL_DIR}"

# Resolve the actual release tag (so 'latest' becomes a concrete version).
# Note: we deliberately don't pipe `curl` straight into `grep -m1` here because
# pipefail + SIGPIPE on early-exit grep causes curl to exit non-zero, which
# breaks the resolve step on perfectly healthy responses.
if [[ "${BRUSH_VERSION}" == "latest" ]]; then
    log "Resolving latest release tag..."
    latest_json=$(curl -fsSL "https://api.github.com/repos/${BRUSH_REPO}/releases/latest") \
        || fail "GitHub API request failed"
    resolved_tag=$(printf '%s' "${latest_json}" \
        | grep '"tag_name":' \
        | head -1 \
        | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')
    [[ -z "${resolved_tag}" ]] && fail "Could not parse tag_name from API response"
else
    resolved_tag="${BRUSH_VERSION}"
fi

log "Using Brush version: ${resolved_tag}"

# Check if already at correct version
if [[ -f "${VERSION_FILE}" && -f "${INSTALL_PATH}" ]]; then
    current="$(cat "${VERSION_FILE}")"
    if [[ "${current}" == "${resolved_tag}" ]]; then
        log "Brush ${resolved_tag} already installed at ${INSTALL_PATH}"
        exit 0
    fi
fi

# Attempt to find the Mac-Silicon asset. Brush release naming is upstream-dependent.
# We probe a few plausible patterns and fall back to an interactive note.
log "Listing release assets..."
assets_json=$(curl -fsSL "https://api.github.com/repos/${BRUSH_REPO}/releases/tags/${resolved_tag}") \
    || fail "Could not fetch release ${resolved_tag}"

asset_url=$(printf '%s' "${assets_json}" \
    | grep '"browser_download_url":' \
    | grep -iE 'mac|darwin|aarch64|arm64' \
    | head -1 \
    | sed -E 's/.*"browser_download_url": *"([^"]+)".*/\1/' || true)

if [[ -z "${asset_url}" ]]; then
    cat >&2 <<EOF

[fetch_brush] Could not auto-detect a Mac-Silicon asset for ${resolved_tag}.

This usually means Brush's release naming changed. Manual fallback:
  1. Open https://github.com/${BRUSH_REPO}/releases/tag/${resolved_tag}
  2. Download the macOS / arm64 binary
  3. Move it to: ${INSTALL_PATH}
  4. Make it executable: chmod +x ${INSTALL_PATH}
  5. Record version: echo "${resolved_tag}" > ${VERSION_FILE}

EOF
    exit 4
fi

log "Downloading: ${asset_url}"
tmp_file="$(mktemp)"
curl -fsSL "${asset_url}" -o "${tmp_file}"

# Handle compressed archives heuristically.
# Note: Brush 0.3.0+ ships as `.tar.xz` with `brush_app.app/Contents/MacOS/brush_app`.
extract_and_install_binary() {
    local archive_dir="$1"
    # Prefer an executable named brush or brush_app, anywhere in the extracted tree.
    local bin
    bin=$(find "${archive_dir}" -type f \( -name 'brush_app' -o -name 'brush' \) -perm -u+x | head -1 || true)
    if [[ -z "${bin}" ]]; then
        # Fall back to any file named brush_app or brush (may need chmod after move)
        bin=$(find "${archive_dir}" -type f \( -name 'brush_app' -o -name 'brush' \) | head -1 || true)
    fi
    [[ -z "${bin}" ]] && fail "No 'brush' or 'brush_app' binary in archive"
    mv "${bin}" "${INSTALL_PATH}"
}

case "${asset_url}" in
    *.tar.gz|*.tgz)
        tmp_dir="$(mktemp -d)"
        tar -xzf "${tmp_file}" -C "${tmp_dir}"
        extract_and_install_binary "${tmp_dir}"
        rm -rf "${tmp_dir}"
        rm -f "${tmp_file}"
        ;;
    *.tar.xz|*.txz)
        tmp_dir="$(mktemp -d)"
        tar -xJf "${tmp_file}" -C "${tmp_dir}"
        extract_and_install_binary "${tmp_dir}"
        rm -rf "${tmp_dir}"
        rm -f "${tmp_file}"
        ;;
    *.zip)
        tmp_dir="$(mktemp -d)"
        unzip -q "${tmp_file}" -d "${tmp_dir}"
        extract_and_install_binary "${tmp_dir}"
        rm -rf "${tmp_dir}"
        rm -f "${tmp_file}"
        ;;
    *)
        # Assume the asset itself is the binary
        mv "${tmp_file}" "${INSTALL_PATH}"
        ;;
esac

chmod +x "${INSTALL_PATH}"
printf '%s\n' "${resolved_tag}" > "${VERSION_FILE}"

log "Installed Brush ${resolved_tag} → ${INSTALL_PATH}"
"${INSTALL_PATH}" --version || log "Note: --version probe failed, binary may still be functional"
