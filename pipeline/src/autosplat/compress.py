# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compress stage — shrink a Brush PLY into a web-optimal splat format.

Phase-5: single backend (`splat-transform` from PlayCanvas, run via `npx` so
nothing has to be installed globally) handles all three target formats:

  - `.sog`    — PlayCanvas Self-Organizing-Gaussians (smallest, SuperSplat-native)
  - `.spz`    — Niantic SPZ
  - `.ksplat` — Three.js GaussianSplats3D

Quality knobs (from the splat-transform CLI):

  - `-i, --iterations <n>` — SOG compression iterations (default 10).
    Higher = better quality, slower. We map quality profiles → iteration counts.
  - `-H, --filter-harmonics <0..3>` — Drop spherical-harmonic bands > N.
    Aggressive size reduction for `low` quality.
  - `-w, --overwrite` — Always set so re-runs are idempotent.

Real compression backend is intentionally a thin wrapper around the upstream
tool. We don't try to do format conversion in pure Python — splat-transform
is the canonical PlayCanvas converter and gets format quirks right.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .logging import get_logger

logger = get_logger(__name__)


CompressFormat = Literal["sog", "spz", "ksplat"]
CompressQuality = Literal["low", "medium", "high"]

# Pin the splat-transform major version we've validated against. npx will
# resolve to the latest matching release on first run and cache it after that.
SPLAT_TRANSFORM_PKG = "@playcanvas/splat-transform@^2.1.1"


@dataclass
class QualityProfile:
    """splat-transform CLI args that realise a named quality level."""

    iterations: int  # SOG compression iterations (more = better, slower)
    filter_harmonics: int | None  # Drop SH bands > N; None = keep all (SH=3)


_QUALITY_PROFILES: dict[CompressQuality, QualityProfile] = {
    "high": QualityProfile(iterations=30, filter_harmonics=None),
    "medium": QualityProfile(iterations=10, filter_harmonics=None),
    "low": QualityProfile(iterations=5, filter_harmonics=1),
}


@dataclass
class CompressBackend:
    """Where we found the compress tool and how to invoke it."""

    invocation: list[str]  # full command prefix, e.g. ["npx", "-y", "@playcanvas/..."]
    via: str  # human-readable origin: "npx" | "global" | "user-install"
    formats: list[CompressFormat]


@dataclass
class CompressResult:
    output_path: Path
    backend_used: str
    quality: CompressQuality
    duration_s: float
    input_bytes: int
    output_bytes: int

    @property
    def ratio(self) -> float:
        """output / input as a fraction (e.g. 0.05 = 95 % reduction)."""
        return self.output_bytes / self.input_bytes if self.input_bytes else 0.0


class CompressorNotAvailable(RuntimeError):
    """Raised when no installed backend can produce the requested format."""


def _detect_backend() -> CompressBackend | None:
    """Find a working splat-transform invocation.

    Preference order:
      1. globally-installed `splat-transform` binary in PATH (instant)
      2. `npx` available — we trust it can fetch the package on first call

    Returns None if neither works.
    """
    # splat-transform v2.1+ supports SOG + SPZ as outputs (KSPLAT only as input).
    # KSPLAT output requires the mkkellogg/gaussian-splats-3d tooling and isn't
    # wired into a single CLI we can call here.
    SPLAT_TRANSFORM_FORMATS: list[CompressFormat] = ["sog", "spz"]

    direct = shutil.which("splat-transform")
    if direct is not None:
        return CompressBackend(
            invocation=[direct],
            via="global",
            formats=SPLAT_TRANSFORM_FORMATS,
        )

    npx = shutil.which("npx")
    if npx is not None:
        return CompressBackend(
            invocation=[npx, "-y", SPLAT_TRANSFORM_PKG],
            via="npx",
            formats=SPLAT_TRANSFORM_FORMATS,
        )

    return None


def available_backends() -> list[CompressBackend]:
    """Return [backend] if compress works, [] otherwise.

    Singleton interface for backwards compat with the Phase-5-skeleton tests.
    """
    backend = _detect_backend()
    return [backend] if backend is not None else []


def install_hint_for(fmt: CompressFormat) -> str:
    """Human-readable hint when no backend is available."""
    if fmt == "ksplat":
        return (
            "KSPLAT output is not supported by splat-transform. You need the "
            "mkkellogg/GaussianSplats3D toolchain — see "
            "https://github.com/mkkellogg/GaussianSplats3D for the converter. "
            "For web embedding, prefer SOG (smaller, SuperSplat-native)."
        )
    return (
        f"To produce {fmt!r} you need `splat-transform`. Easiest path is to "
        "install Node.js (Homebrew: `brew install node`), then autosplat will "
        "use `npx -y @playcanvas/splat-transform` on demand. "
        "Or install globally: `npm install -g @playcanvas/splat-transform`."
    )


def build_compress_command(
    backend: CompressBackend,
    ply: Path,
    output: Path,
    quality: CompressQuality,
) -> list[str]:
    """Construct the full splat-transform invocation.

    `splat-transform <input> [ACTIONS] <output>` — actions go between input
    and output and apply in order.
    """
    profile = _QUALITY_PROFILES[quality]
    cmd: list[str] = [*backend.invocation, str(ply)]

    # ACTIONS in order. Filter harmonics first (reduces data) so the SOG
    # iterations work on the simpler representation.
    if profile.filter_harmonics is not None:
        cmd += ["-H", str(profile.filter_harmonics)]

    cmd += ["-i", str(profile.iterations)]
    cmd += ["-w"]  # overwrite — idempotent re-runs
    cmd += [str(output)]
    return cmd


def compress_ply(
    ply: Path,
    output_dir: Path,
    *,
    fmt: CompressFormat = "sog",
    quality: CompressQuality = "medium",
) -> CompressResult:
    """Compress `ply` into `output_dir/<stem>.<fmt>`.

    Raises:
        FileNotFoundError if the input PLY is missing.
        CompressorNotAvailable if neither global `splat-transform` nor `npx`
            is present.
        RuntimeError if the backend ran but didn't produce the expected output.
        subprocess.CalledProcessError if the backend itself failed.
    """
    t0 = time.monotonic()
    if not ply.exists():
        raise FileNotFoundError(f"PLY not found: {ply}")

    backend = _detect_backend()
    if backend is None:
        raise CompressorNotAvailable(
            f"No installed backend can produce {fmt}. {install_hint_for(fmt)}"
        )
    if fmt not in backend.formats:
        raise CompressorNotAvailable(
            f"Backend ({backend.via}) does not support {fmt!r}."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{ply.stem}.{fmt}"

    cmd = build_compress_command(backend, ply, output, quality)
    logger.info(
        "compress.start",
        backend_via=backend.via,
        fmt=fmt,
        quality=quality,
        input=str(ply),
        output=str(output),
    )

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        logger.error(
            "compress.subprocess_failed",
            returncode=proc.returncode,
            stderr=(proc.stderr or "")[-2000:],
            stdout=(proc.stdout or "")[-2000:],
        )
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr
        )

    # splat-transform may emit a `meta.json` sidecar for SOG; we accept either
    # the named output existing OR a directory named after the stem.
    if not output.exists() and not (output_dir / output.stem).exists():
        raise RuntimeError(f"Backend ran but didn't produce {output}")

    duration = time.monotonic() - t0
    out_size = output.stat().st_size if output.exists() else 0
    result = CompressResult(
        output_path=output,
        backend_used=f"splat-transform ({backend.via})",
        quality=quality,
        duration_s=duration,
        input_bytes=ply.stat().st_size,
        output_bytes=out_size,
    )
    logger.info(
        "compress.done",
        backend_via=backend.via,
        fmt=fmt,
        output=str(output),
        input_bytes=result.input_bytes,
        output_bytes=result.output_bytes,
        ratio=round(result.ratio, 4),
        duration_s=round(duration, 2),
    )
    return result
