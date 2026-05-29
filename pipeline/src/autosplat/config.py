# SPDX-License-Identifier: AGPL-3.0-or-later

"""TOML-Config Loading + Pydantic-Validation.

Layering:
  1. config/default.toml (packaged with the repo)
  2. ~/.config/autosplat/config.toml (XDG-style user override)
  3. --config <path> CLI override
  4. Per-key CLI overrides

Each later layer wins.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _packaged_default_config() -> Path:
    """Locate the packaged default.toml — frozen-aware.

    In a PyInstaller bundle the repo layout is gone, so resolve against
    `sys._MEIPASS` (where build_app.sh stages `config/`); otherwise use the
    repo-relative path (config.py → autosplat → src → repo root).
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "config" / "default.toml"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2] / "config" / "default.toml"


# Default-config path (repo-relative, or bundle-relative when frozen)
PACKAGED_DEFAULT_CONFIG = _packaged_default_config()

XDG_CONFIG_PATH = Path("~/.config/autosplat/config.toml").expanduser()


class PathsConfig(BaseModel):
    """Filesystem roots for the pipeline's runtime artefacts."""

    captures_dir: Path = Field(description="Per-capture working dirs (frames, sparse, training).")
    watch_folder: Path = Field(
        description="Default inbox for `autosplat watch`. Files dropped here are auto-processed."
    )
    brush_binary: Path = Field(
        description="Absolute path to the Brush binary. Set by scripts/fetch_brush.sh."
    )

    @field_validator("captures_dir", "watch_folder", "brush_binary", mode="before")
    @classmethod
    def _expand(cls, v: Any) -> Path:
        return Path(os.path.expanduser(str(v)))


class PreprocessConfig(BaseModel):
    """ffmpeg keyframe extraction + Laplacian blur filter."""

    target_frames: int = Field(
        ge=10,
        le=10_000,
        description="Keyframe count target. Clamped by min_frame_distance_sec.",
    )
    blur_threshold: float = Field(
        ge=0.0,
        description="Laplacian-variance floor. Frames below are dropped. "
        "100 = strict (calibrated for slow passes); 25-50 for fast orbits.",
    )
    min_frame_distance_sec: float = Field(
        ge=0.0,
        description="Minimum seconds between extracted frames. 0.2 = max 5 fps.",
    )


class ColmapConfig(BaseModel):
    """COLMAP Structure-from-Motion stage."""

    matcher: Literal["sequential", "exhaustive", "spatial", "vocab_tree"] = Field(
        description="Frame-pair matching strategy. sequential is fastest for video; "
        "exhaustive is the Phase-3 retry fallback.",
    )
    quality: Literal["low", "medium", "high"] = Field(
        description="Preset for SIFT feature count + max image size.",
    )
    single_camera: bool = Field(
        description="True if all frames come from one physical camera (true for drone)."
    )


class BrushConfig(BaseModel):
    """Brush Gaussian-Splat training stage."""

    max_steps: int = Field(
        ge=100,
        description="Total training iterations. Mapped to brush --total-steps.",
    )
    resolution_cap: int = Field(
        ge=256,
        description="Max image dimension Brush trains on. Mapped to --max-resolution.",
    )
    sh_degree: int = Field(
        ge=0,
        le=4,
        description="Spherical-harmonic degree. 0=ambient only, 3=full view-dependent.",
    )
    densify_until_iter: int = Field(
        ge=0,
        description="Stop adding new Gaussians after this iter. Mapped to --growth-stop-iter.",
    )
    extra_args: list[str] = Field(
        default_factory=list,
        description="Passthrough flags appended to the Brush command.",
    )
    # v1.5.0 — Train-till-Plateau (opt-in)
    plateau_enabled: bool = Field(
        default=False,
        description="v1.5.0 — when true, hold out 1/N frames as eval set, compute PSNR "
        "against rendered eval images every plateau_eval_every steps, and SIGTERM Brush "
        "when the PSNR curve flattens (Δ < plateau_min_delta_psnr over plateau_patience "
        "consecutive evals, after plateau_min_steps).",
    )
    plateau_eval_split_every: int = Field(
        default=10,
        ge=2,
        le=50,
        description="Hold out every Nth frame as the eval set. 10 ≈ 10 % holdout.",
    )
    plateau_eval_every: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Brush --eval-every. Also drives --export-every so every eval "
        "checkpoint has a fresh PLY in case SIGTERM fires mid-iteration.",
    )
    plateau_min_steps: int = Field(
        default=5000,
        ge=100,
        description="Don't trigger plateau-stop before this many steps — densification "
        "needs time before the PSNR curve is meaningful.",
    )
    plateau_patience: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Number of consecutive evals with Δ < plateau_min_delta_psnr "
        "required to declare a plateau.",
    )
    plateau_min_delta_psnr: float = Field(
        default=0.05,
        gt=0.0,
        le=5.0,
        description="ε in dB — PSNR improvement below this counts as 'flat'.",
    )

    @field_validator("plateau_min_steps")
    @classmethod
    def _plateau_min_steps_below_max(cls, v: int, info: object) -> int:
        # Only enforce the cross-field constraint when the feature is enabled
        # — otherwise a user lowering max_steps for a quick CI run gets
        # rejected for no reason. info.data carries already-validated fields;
        # `plateau_enabled` and `max_steps` are declared before this field.
        data = info.data if hasattr(info, "data") else {}  # type: ignore[attr-defined]
        if data.get("plateau_enabled") and v > data.get("max_steps", v):
            raise ValueError(
                f"plateau_min_steps ({v}) must be ≤ max_steps ({data['max_steps']}) "
                "when plateau_enabled=true — otherwise the plateau-check never engages."
            )
        return v


class ExportConfig(BaseModel):
    """PLY validation + outputs-dir copy stage."""

    formats: list[Literal["ply", "splat", "spz"]] = Field(
        description="Always includes 'ply'. Other formats handled by [compress] stage.",
    )
    copy_to_outputs: bool = Field(
        description="If true, also copies final PLY to outputs_dir/<capture>/."
    )
    outputs_dir: Path = Field(description="User-facing output root, distinct from captures_dir.")

    @field_validator("outputs_dir", mode="before")
    @classmethod
    def _expand(cls, v: Any) -> Path:
        return Path(os.path.expanduser(str(v)))


class ViewerConfig(BaseModel):
    """Auto-open the splat in a browser after a successful run."""

    auto_open: bool = Field(description="Skip the auto-open if false.")
    local_http_port: int = Field(
        ge=1024,
        le=65535,
        description="Local server port serving the PLY to the viewer.",
    )
    target: Literal["supersplat", "supersplat-local", "playcanvas", "none"] = Field(
        description="Which viewer URL pattern to open."
    )
    supersplat_local_port: int = Field(
        default=3000,
        ge=1024,
        le=65535,
        description="Port for locally-built SuperSplat server.",
    )
    supersplat_dist_path: Path = Field(
        default=Path("target/supersplat/dist"),
        description="Path to built SuperSplat dist/ directory.",
    )
    notify_on_complete: bool = Field(
        default=False,
        description="Send a macOS Notification Center alert after training completes. Opt-in.",
    )


class ObsidianConfig(BaseModel):
    """Phase-4 capture-note generator. Opt-in."""

    enabled: bool = Field(
        description="Master switch. False by default — no notes written.",
    )
    vault_path: Path = Field(description="Absolute path to your Obsidian vault root.")
    captures_subdir: str = Field(
        description="Subdir inside vault for auto-generated capture notes.",
    )
    attach_ply: bool = Field(
        description="Copy the PLY into the vault. Big files — opt-in.",
    )
    # Phase 4 additions — backwards-compat: missing fields default to sensible values
    filename_pattern: str = Field(
        default="{capture_date} {video_stem}.md",
        description="Filename template. Placeholders: {capture_date}, {video_stem}, {capture_name}.",
    )
    default_tags: list[str] = Field(
        default_factory=lambda: ["3d-memory", "gaussian-splat", "auto-splat"],
        description="Frontmatter `tags:` list.",
    )
    frontmatter_type: str = Field(
        default="capture",
        description="Frontmatter `type:` field — used by Obsidian Bases.",
    )

    @field_validator("vault_path", mode="before")
    @classmethod
    def _expand(cls, v: Any) -> Path:
        return Path(os.path.expanduser(str(v)))


class LoggingConfig(BaseModel):
    """structlog + Rich console + per-capture pipeline.log."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        description="Min severity to log. INFO is recommended.",
    )
    console: Literal["rich", "plain"] = Field(
        description="Console renderer. `plain` for CI / log capture.",
    )
    log_to_file: bool = Field(
        description="If true, write `pipeline.log` (JSON) into each capture-dir.",
    )


class QualityGateConfig(BaseModel):
    """Phase-3 validation stage between SfM and Brush. Skips garbage runs."""

    enabled: bool = Field(
        default=True,
        description="Disable to let Brush run on any SfM output (wastes compute on bad ones).",
    )
    min_camera_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum cameras_registered / frames_kept ratio.",
    )
    min_points: int = Field(
        default=5000,
        ge=0,
        description="Minimum sparse-cloud point count.",
    )


class RetryConfig(BaseModel):
    """Adaptive-retry policy for the watch-folder daemon."""

    enabled: bool = Field(
        default=True,
        description="Disable to fail-fast on every error (no retries).",
    )
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum total attempts per capture, including the first try.",
    )
    # v1.4 — Auto-Bisection-Rescue
    bisect_enabled: bool = Field(
        default=True,
        description="After sequential→exhaustive exhausts itself, attempt binary "
        "subdivision of the source video. Disable for fast-fail in CI.",
    )
    bisect_min_clip_s: float = Field(
        default=60.0,
        ge=10.0,
        le=600.0,
        description="Sub-clips shorter than this are not probed during bisection.",
    )
    bisect_max_depth: int = Field(
        default=3,
        ge=1,
        le=6,
        description="Max recursion depth for bisection — 3 means up to 8 leaves.",
    )
    bisect_probe_target_frames: int = Field(
        default=120,
        ge=30,
        le=1000,
        description="preprocess.target_frames override for bisection probes. "
        "Lower than the pipeline default (250) because exhaustive matcher cost "
        "scales as n²/2 — 120 frames keeps a single probe under ~7000 matches.",
    )
    bisect_smart_split: bool = Field(
        default=False,
        description="v1.4.1 — when true, use OpenCV optical-flow analysis to pick "
        "the cut point at the moment of strongest motion change (typically a "
        "rotation event), instead of splitting at midpoint. Falls back to "
        "midpoint cleanly if analysis fails. Opt-in because smart-split adds "
        "~5-15 s per cut and isn't strictly better than midpoint on all footage.",
    )


class StatusConfig(BaseModel):
    """state.json pruning to keep file size bounded."""

    max_history: int = Field(
        default=50,
        ge=1,
        description="FIFO cap for completed + failed entries.",
    )


class CompressConfig(BaseModel):
    """Phase-5 optional compress stage. Runs after Export when enabled."""

    enabled: bool = Field(
        default=False,
        description="Opt-in. Produces web-optimal splats next to the PLY.",
    )
    formats: list[Literal["sog", "spz", "ksplat"]] = Field(
        default_factory=lambda: ["sog"],
        description="Output formats. sog = SuperSplat-native; spz = smallest.",
    )
    quality: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Quality preset (low filters SH bands; medium is recommended).",
    )


class Config(BaseModel):
    paths: PathsConfig
    preprocess: PreprocessConfig
    colmap: ColmapConfig
    brush: BrushConfig
    export: ExportConfig
    viewer: ViewerConfig
    obsidian: ObsidianConfig
    logging: LoggingConfig
    # Phase-3 additions (defaults populated even if missing from user TOML)
    quality_gate: QualityGateConfig = Field(default_factory=QualityGateConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    status: StatusConfig = Field(default_factory=StatusConfig)
    # Phase-5 — opt-in compress stage after Export
    compress: CompressConfig = Field(default_factory=CompressConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, val in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(
    user_config_path: Path | None = None,
    *,
    include_xdg: bool = True,
) -> Config:
    """Load and merge config from defaults → XDG → explicit user path."""
    if not PACKAGED_DEFAULT_CONFIG.exists():
        raise FileNotFoundError(f"Packaged default config missing at {PACKAGED_DEFAULT_CONFIG}")

    merged = _load_toml(PACKAGED_DEFAULT_CONFIG)

    if include_xdg and XDG_CONFIG_PATH.exists():
        merged = _deep_merge(merged, _load_toml(XDG_CONFIG_PATH))

    if user_config_path is not None:
        if not user_config_path.exists():
            raise FileNotFoundError(f"Config file not found: {user_config_path}")
        merged = _deep_merge(merged, _load_toml(user_config_path))

    return Config.model_validate(merged)


def dump_default_config(target: Path) -> None:
    """Copy packaged default config to `target`. Used by `autosplat config init`."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PACKAGED_DEFAULT_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")


def apply_override(cfg: Config, override: dict[str, Any]) -> Config:
    """Deep-merge `override` into `cfg` and re-validate.

    `override` is a nested dict matching the TOML/Pydantic structure, e.g.:
        {"colmap": {"matcher": "exhaustive"}}

    Used by Phase-3 adaptive retry — when a quality-gate failure says
    `retry_hint={"colmap": {"matcher": "exhaustive"}}`, the watcher applies
    that hint via this helper before calling run_pipeline again.
    """
    if not override:
        return cfg
    merged = _deep_merge(cfg.model_dump(mode="python"), override)
    return Config.model_validate(merged)
