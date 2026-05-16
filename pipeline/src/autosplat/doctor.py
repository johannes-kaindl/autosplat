# SPDX-License-Identifier: AGPL-3.0-or-later

"""Preflight checks for system dependencies.

Run via `autosplat doctor`. Returns non-zero exit if any required dep is missing.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Config


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    required: bool = True

    @property
    def status_emoji(self) -> str:
        if self.ok:
            return "OK"
        return "MISSING" if self.required else "WARN"


_VERSION_PROBE_FLAGS: dict[str, list[str]] = {
    # COLMAP's `--version` opens its options menu and blocks. `help` returns
    # promptly with a banner that contains the version.
    "colmap": ["help"],
}


def _check_binary(name: str, *, required: bool = True) -> CheckResult:
    path = shutil.which(name)
    if path is None:
        return CheckResult(name=name, ok=False, detail="not in PATH", required=required)
    probe = _VERSION_PROBE_FLAGS.get(name, ["--version"])
    try:
        version = subprocess.run(
            [path, *probe],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        version_line = (version.stdout or version.stderr).splitlines()[0] if (version.stdout or version.stderr) else "version unknown"
    except (subprocess.SubprocessError, OSError) as e:
        version_line = f"version check failed: {e}"
    return CheckResult(name=name, ok=True, detail=f"{path} ({version_line})", required=required)


def _check_brush(binary_path: Path) -> CheckResult:
    if not binary_path.exists():
        return CheckResult(
            name="brush",
            ok=False,
            detail=f"missing at {binary_path} — run scripts/fetch_brush.sh",
        )
    if not os.access(binary_path, os.X_OK):
        return CheckResult(
            name="brush",
            ok=False,
            detail=f"not executable: {binary_path} — chmod +x",
        )
    return CheckResult(name="brush", ok=True, detail=str(binary_path))


def _check_platform() -> CheckResult:
    system = platform.system()
    machine = platform.machine()
    is_mac_silicon = system == "Darwin" and machine == "arm64"
    return CheckResult(
        name="platform",
        ok=is_mac_silicon,
        detail=f"{system}/{machine} — auto-splat-pipeline is Mac-Silicon-only",
        required=is_mac_silicon is False,  # warn rather than block on x86 Mac
    )


def _check_python() -> CheckResult:
    import sys

    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 11)
    return CheckResult(
        name="python",
        ok=ok,
        detail=f"{major}.{minor}.{sys.version_info.micro}",
    )


def run_doctor(config: Config) -> list[CheckResult]:
    """Run all preflight checks. Returns list of results in display order."""
    results = [
        _check_platform(),
        _check_python(),
        _check_binary("ffmpeg"),
        _check_binary("colmap"),
        _check_brush(config.paths.brush_binary),
        _check_binary("uv", required=False),
        _check_compress_backends(),
        _check_obsidian_config(config),
    ]
    supersplat = _check_supersplat(config)
    if supersplat is not None:
        results.append(supersplat)
    return results


def _check_obsidian_config(config: Config) -> CheckResult:
    """Phase 8 B1: if obsidian.enabled but vault_path empty → WARN."""
    if not config.obsidian.enabled:
        return CheckResult(
            name="obsidian",
            ok=True,
            detail="disabled (opt-in via [obsidian].enabled = true)",
            required=False,
        )
    vault = config.obsidian.vault_path
    if str(vault) in ("", "."):
        return CheckResult(
            name="obsidian",
            ok=False,
            detail="enabled but [obsidian].vault_path is empty — set it in your config",
            required=False,
        )
    if not vault.exists():
        return CheckResult(
            name="obsidian",
            ok=False,
            detail=f"enabled but vault_path missing on disk: {vault}",
            required=False,
        )
    return CheckResult(
        name="obsidian",
        ok=True,
        detail=f"{vault} → {config.obsidian.captures_subdir}/",
        required=False,
    )


def _check_supersplat(config: Config) -> CheckResult | None:
    """Phase 9.2: WARN if supersplat-local target is set but dist is missing."""
    if config.viewer.target != "supersplat-local":
        return None  # Not relevant for remote-only setup
    dist_index = config.viewer.supersplat_dist_path / "index.html"
    if dist_index.exists():
        return CheckResult(
            name="supersplat",
            ok=True,
            detail=f"dist at {dist_index.parent}",
            required=False,
        )
    return CheckResult(
        name="supersplat",
        ok=False,
        required=False,
        detail=f"dist missing at {dist_index.parent} — run scripts/setup_supersplat.sh",
    )


def _check_compress_backends() -> CheckResult:
    """Phase-5 optional check — `splat-transform` reachable (directly or via npx)."""
    from .compress import available_backends

    backends = available_backends()
    if not backends:
        return CheckResult(
            name="compress",
            ok=False,
            detail=(
                "no `splat-transform` and no `npx` in PATH "
                "(Phase 5 — optional; install Node.js to enable)"
            ),
            required=False,
        )
    backend = backends[0]
    detail = f"splat-transform via {backend.via} → {','.join(backend.formats)}"
    return CheckResult(name="compress", ok=True, detail=detail, required=False)


def all_required_passed(results: list[CheckResult]) -> bool:
    return all(r.ok for r in results if r.required)
