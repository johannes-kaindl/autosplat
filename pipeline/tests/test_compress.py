"""Phase-5 compress tests.

Two layers:
  1. Pure unit tests — quality-profile mapping, command-builder, backend
     probe with mocked PATH. No real splat-transform invocation.
  2. Opt-in E2E test against a real PLY, gated by AUTOSPLAT_COMPRESS_E2E=1
     and the presence of `npx` or `splat-transform`. Skipped on dev machines
     without Node.js so the default suite stays fast.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from autosplat.compress import (
    _QUALITY_PROFILES,
    SPLAT_TRANSFORM_PKG,
    CompressBackend,
    CompressorNotAvailable,
    available_backends,
    build_compress_command,
    compress_ply,
    install_hint_for,
)

# ─── Quality-profile mapping ────────────────────────────────────────────────


def test_quality_profiles_all_three_levels_present() -> None:
    assert set(_QUALITY_PROFILES.keys()) == {"low", "medium", "high"}


def test_high_quality_uses_more_iterations_than_medium() -> None:
    assert _QUALITY_PROFILES["high"].iterations > _QUALITY_PROFILES["medium"].iterations


def test_low_quality_aggressively_filters_harmonics() -> None:
    assert _QUALITY_PROFILES["low"].filter_harmonics is not None
    assert _QUALITY_PROFILES["medium"].filter_harmonics is None
    assert _QUALITY_PROFILES["high"].filter_harmonics is None


# ─── Command-builder ────────────────────────────────────────────────────────


def _fake_backend(via: str = "npx") -> CompressBackend:
    if via == "npx":
        return CompressBackend(
            invocation=["/usr/bin/npx", "-y", SPLAT_TRANSFORM_PKG],
            via="npx",
            formats=["sog", "spz", "ksplat"],
        )
    return CompressBackend(
        invocation=["/usr/local/bin/splat-transform"],
        via="global",
        formats=["sog", "spz", "ksplat"],
    )


def test_command_builder_input_then_output(tmp_path: Path) -> None:
    cmd = build_compress_command(
        _fake_backend(), tmp_path / "in.ply", tmp_path / "out.sog", "medium"
    )
    # First non-invocation token must be the input path.
    assert str(tmp_path / "in.ply") in cmd
    # Output is the last token.
    assert cmd[-1] == str(tmp_path / "out.sog")


def test_command_builder_includes_iterations(tmp_path: Path) -> None:
    cmd = build_compress_command(
        _fake_backend(), tmp_path / "in.ply", tmp_path / "out.sog", "high"
    )
    idx = cmd.index("-i")
    assert cmd[idx + 1] == "30"  # high profile


def test_command_builder_includes_overwrite_flag(tmp_path: Path) -> None:
    cmd = build_compress_command(
        _fake_backend(), tmp_path / "in.ply", tmp_path / "out.sog", "medium"
    )
    assert "-w" in cmd  # idempotent re-runs


def test_command_builder_filters_harmonics_for_low_quality(tmp_path: Path) -> None:
    cmd = build_compress_command(
        _fake_backend(), tmp_path / "in.ply", tmp_path / "out.sog", "low"
    )
    idx = cmd.index("-H")
    assert cmd[idx + 1] == "1"


def test_command_builder_omits_harmonics_filter_for_high(tmp_path: Path) -> None:
    cmd = build_compress_command(
        _fake_backend(), tmp_path / "in.ply", tmp_path / "out.sog", "high"
    )
    assert "-H" not in cmd  # SH=3 preserved


def test_command_builder_uses_global_when_available(tmp_path: Path) -> None:
    cmd = build_compress_command(
        _fake_backend("global"), tmp_path / "in.ply", tmp_path / "out.sog", "medium"
    )
    assert cmd[0] == "/usr/local/bin/splat-transform"
    assert "-y" not in cmd  # global doesn't need npx scaffolding


# ─── Backend detection ──────────────────────────────────────────────────────


def test_available_backends_returns_singleton_or_empty(monkeypatch) -> None:
    """We exposed either zero or exactly one backend — never multiple."""
    result = available_backends()
    assert isinstance(result, list)
    assert len(result) <= 1


def test_available_backends_finds_global(monkeypatch) -> None:
    monkeypatch.setattr(
        "autosplat.compress.shutil.which",
        lambda name: "/fake/splat-transform" if name == "splat-transform" else None,
    )
    backends = available_backends()
    assert len(backends) == 1
    assert backends[0].via == "global"


def test_available_backends_falls_back_to_npx(monkeypatch) -> None:
    monkeypatch.setattr(
        "autosplat.compress.shutil.which",
        lambda name: "/fake/npx" if name == "npx" else None,
    )
    backends = available_backends()
    assert len(backends) == 1
    assert backends[0].via == "npx"
    assert SPLAT_TRANSFORM_PKG in backends[0].invocation


def test_available_backends_empty_when_neither_present(monkeypatch) -> None:
    monkeypatch.setattr("autosplat.compress.shutil.which", lambda name: None)
    assert available_backends() == []


# ─── install_hint_for + error paths ─────────────────────────────────────────


def test_install_hint_per_format() -> None:
    for fmt in ("sog", "spz"):
        hint = install_hint_for(fmt)
        assert "splat-transform" in hint
        assert "node" in hint.lower()
    # KSPLAT has its own hint because splat-transform doesn't produce it
    ksplat_hint = install_hint_for("ksplat")
    assert "GaussianSplats3D" in ksplat_hint or "mkkellogg" in ksplat_hint


def test_compress_ply_raises_on_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compress_ply(tmp_path / "nope.ply", tmp_path, fmt="sog")


def test_compress_ply_raises_when_no_backend(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("autosplat.compress._detect_backend", lambda: None)
    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"ply\n")
    with pytest.raises(CompressorNotAvailable):
        compress_ply(ply, tmp_path / "out", fmt="sog")


# ─── Opt-in E2E ─────────────────────────────────────────────────────────────


def _e2e_enabled() -> bool:
    return os.environ.get("AUTOSPLAT_COMPRESS_E2E", "").lower() in ("1", "true", "yes")


@pytest.mark.slow
@pytest.mark.skipif(not _e2e_enabled(), reason="set AUTOSPLAT_COMPRESS_E2E=1 to run")
def test_real_compress_smoke(tmp_path: Path) -> None:
    """Compress the bundled tiny_video-derived PLY if a real backend exists.

    Uses the bench_chill PLY if present (it's the smallest real splat output
    in the fixture tree). Otherwise skips.
    """
    fixture_ply = Path.home() / "AutoSplat/outputs/2026-05-14_dji_fly_bench_chill/scene.ply"
    if not fixture_ply.exists():
        pytest.skip(f"No PLY fixture available at {fixture_ply}")

    backends = available_backends()
    if not backends:
        pytest.skip("No compress backend installed")

    result = compress_ply(fixture_ply, tmp_path, fmt="sog", quality="medium")
    assert result.output_bytes > 0
    # Reasonable compression ratio: a Brush PLY should compress to <30 % as SOG.
    assert result.ratio < 0.3, f"Compression ratio suspiciously high: {result.ratio}"
