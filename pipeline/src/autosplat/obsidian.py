# SPDX-License-Identifier: AGPL-3.0-or-later

"""Obsidian capture-note generator (Phase 4 — spec §11.4 + §13).

Produces a Markdown file in the user's Obsidian vault with:
  - YAML frontmatter (Bases-compatible) covering every numeric stat we have
  - A body split into an *auto-generated* region (regenerated on every pipeline
    run) and a *user-editable* tail (preserved across re-runs).

Re-run behaviour:
  - If the target file already exists with our markers, everything before/after
    the END marker is treated as user content and preserved.
  - If it exists without markers, we back it up to `<file>.bak` and write fresh
    (we'd rather lose nothing than silently overwrite hand-typed prose).
  - If it doesn't exist, write the template fresh.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from .config import ObsidianConfig
from .logging import get_logger

logger = get_logger(__name__)

# Markers framing the auto-generated body region. Anything OUTSIDE these markers
# is treated as user-editable and preserved on re-run.
AUTO_BLOCK_START = (
    "<!-- AUTO-GENERATED:START — managed by autosplat, do not edit between markers -->"
)
AUTO_BLOCK_END = "<!-- AUTO-GENERATED:END -->"
_AUTO_RE = re.compile(
    re.escape(AUTO_BLOCK_START) + r".*?" + re.escape(AUTO_BLOCK_END),
    re.DOTALL,
)

# Phase 8 B6: keys we (Cowork) own and re-write on every run. Anything else
# in the existing frontmatter is treated as user-added and preserved.
_COWORK_MANAGED_KEYS = frozenset(
    {
        "type",
        "captured",
        "source",
        "frames_extracted",
        "frames_kept",
        "cameras_registered",
        "points3d",
        "gaussians",
        "sh_degree",
        "training_duration_s",
        "total_duration_s",
        "output_ply",
        "output_ply_size_bytes",
        "tags",
    }
)

# Keys we generate but won't overwrite an existing non-null user value.
# This is the "user filled in embed_url after Cowork wrote null" case.
_COWORK_GENERATED_BUT_USER_OVERRIDABLE = frozenset({"embed_url"})


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _parse_existing_frontmatter(content: str) -> dict[str, Any]:
    """Pull the YAML-frontmatter dict out of a note's text. Returns {} if absent or broken."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}
    try:
        loaded = yaml.safe_load(match.group(1))
        return loaded if isinstance(loaded, dict) else {}
    except yaml.YAMLError as e:
        logger.warning("obsidian.frontmatter_unparseable", error=str(e))
        return {}


def _merge_frontmatter(new_fm: dict[str, Any], existing_fm: dict[str, Any]) -> dict[str, Any]:
    """Phase 8 B6 merge policy.

    Rules:
      1. Cowork-managed keys (stats, source, etc.): new value wins.
      2. User-added keys (anything else in existing): preserved unchanged.
      3. embed_url etc. (in _COWORK_GENERATED_BUT_USER_OVERRIDABLE): if existing
         has a non-null user value and new value is null/empty → keep user value.
    """
    merged = dict(new_fm)

    # Preserve user-added keys.
    for key, value in existing_fm.items():
        if key in _COWORK_MANAGED_KEYS:
            continue
        if key in _COWORK_GENERATED_BUT_USER_OVERRIDABLE:
            new_val = merged.get(key)
            # Only let existing win if existing has a real value AND new is empty.
            if value not in (None, "") and new_val in (None, ""):
                merged[key] = value
            continue
        # Plain user-added key not in either set: preserve.
        if key not in merged:
            merged[key] = value

    return merged


class CaptureNoteData(BaseModel):
    """Schema for the data that gets templated into a capture note.

    All numeric stats are required; `embed_url` is optional (filled in manually
    by the user after SuperSplat publish).
    """

    capture_date: str  # ISO date `YYYY-MM-DD`
    capture_name: str  # `{date}_{stem}` from pipeline
    source_video: str
    video_stem: str
    frame_count_extracted: int
    frame_count_kept: int
    cameras_registered: int
    points3d: int
    gaussians: int
    sh_degree: int
    training_duration_s: float
    total_duration_s: float
    output_ply: str
    output_ply_size_bytes: int
    embed_url: str | None = None
    tags: list[str] = Field(default_factory=lambda: ["3d-memory", "gaussian-splat", "auto-splat"])
    frontmatter_type: str = "capture"

    @field_validator("capture_date")
    @classmethod
    def _date_iso(cls, v: str) -> str:
        # Validate but keep as string — Obsidian expects YYYY-MM-DD.
        datetime.strptime(v, "%Y-%m-%d")
        return v


def read_ply_header(ply: Path) -> dict:
    """Pull `vertex count` + `SH degree` out of a Brush-exported PLY header.

    Falls back to inferring SH degree from the `f_rest_*` property count if the
    `comment SH degree: K` line is missing.
    """
    if not ply.exists():
        return {"gaussians": 0, "sh_degree": 0}

    vertex_count = 0
    sh_from_comment: int | None = None
    f_rest_count = 0

    with ply.open("rb") as f:
        for raw in f:
            try:
                line = raw.decode("ascii", errors="strict").rstrip()
            except UnicodeDecodeError:
                # Past the header into binary payload
                break
            if line.startswith("element vertex "):
                vertex_count = int(line.split()[-1])
            elif line.startswith("comment SH degree:"):
                sh_from_comment = int(line.split(":")[-1].strip())
            elif line.startswith("property") and "f_rest_" in line:
                f_rest_count += 1
            elif line == "end_header":
                break

    if sh_from_comment is not None:
        sh_degree = sh_from_comment
    elif f_rest_count > 0:
        # f_rest_count = 3 * ((sh + 1)^2 - 1)  =>  sh = sqrt((count/3) + 1) - 1
        sh_degree = round(math.sqrt(f_rest_count / 3 + 1) - 1)
    else:
        sh_degree = 0

    return {"gaussians": vertex_count, "sh_degree": sh_degree}


def _build_frontmatter_dict(data: CaptureNoteData) -> dict[str, Any]:
    """Frontmatter as a Python dict — base shape, before user-merge."""
    return {
        "type": data.frontmatter_type,
        "captured": data.capture_date,
        "source": data.source_video,
        "frames_extracted": data.frame_count_extracted,
        "frames_kept": data.frame_count_kept,
        "cameras_registered": data.cameras_registered,
        "points3d": data.points3d,
        "gaussians": data.gaussians,
        "sh_degree": data.sh_degree,
        "training_duration_s": round(data.training_duration_s, 1),
        "total_duration_s": round(data.total_duration_s, 1),
        "output_ply": data.output_ply,
        "output_ply_size_bytes": data.output_ply_size_bytes,
        "embed_url": data.embed_url if data.embed_url else None,
        "tags": list(data.tags),
    }


def _render_frontmatter(fm: dict[str, Any]) -> str:
    """Dump a frontmatter dict back to YAML, with a tags inline-list."""
    # Use safe_dump with sort_keys=False to preserve insertion order.
    yaml_str = yaml.safe_dump(
        fm,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return f"---\n{yaml_str}---\n"


def render_note(data: CaptureNoteData, existing_frontmatter: dict[str, Any] | None = None) -> str:
    """Render the full Markdown file (frontmatter + auto-block + empty Notes section).

    `existing_frontmatter` (Phase 8 B6): if provided, user-added keys are
    preserved per `_merge_frontmatter`.
    """
    new_fm = _build_frontmatter_dict(data)
    if existing_frontmatter:
        new_fm = _merge_frontmatter(new_fm, existing_frontmatter)

    body_auto = _render_auto_block(data)
    return (
        _render_frontmatter(new_fm)
        + "\n"
        + f"# {data.capture_name}\n"
        + "\n"
        + f"{AUTO_BLOCK_START}\n"
        + f"{body_auto}\n"
        + f"{AUTO_BLOCK_END}\n"
        + "\n"
        + "## Notes\n"
        + "<!-- Free-form notes here are preserved on re-run -->\n"
    )


def _render_auto_block(data: CaptureNoteData) -> str:
    embed = ""
    if data.embed_url:
        embed = (
            "\n## Embed\n\n"
            f'<iframe src="{data.embed_url}" width="100%" height="600" '
            'style="border:0;" allowfullscreen></iframe>\n'
            f"\n[Open in browser]({data.embed_url})\n"
        )
    return (
        "> [!info] Auto-generated by autosplat pipeline\n"
        "\n"
        "## Source\n"
        f"- Video: `{data.source_video}`\n"
        f"- Captured: {data.capture_date}\n"
        "\n"
        "## Pipeline Stats\n"
        "| Metric | Value |\n"
        "|---|---|\n"
        f"| Frames extracted | {data.frame_count_extracted} |\n"
        f"| Frames kept (after blur filter) | {data.frame_count_kept} |\n"
        f"| COLMAP cameras registered | {data.cameras_registered} |\n"
        f"| COLMAP sparse points | {data.points3d} |\n"
        f"| Gaussians | {data.gaussians:,} |\n"
        f"| SH degree | {data.sh_degree} |\n"
        f"| Training duration | {data.training_duration_s:.1f}s |\n"
        f"| Total pipeline duration | {data.total_duration_s:.1f}s |\n"
        "\n"
        "## Output\n"
        f"- PLY: `{data.output_ply}` ({data.output_ply_size_bytes / 1_048_576:.1f} MB)\n"
        f"{embed}"
    )


def _extract_user_tail(existing: str) -> str | None:
    """Return everything after the AUTO_BLOCK_END marker, or None if no markers.

    The preserved tail is rendered verbatim at the same position in the new file.
    """
    idx = existing.find(AUTO_BLOCK_END)
    if idx == -1:
        return None
    tail = existing[idx + len(AUTO_BLOCK_END) :]
    return tail.lstrip("\n")


def _format_filename(pattern: str, data: CaptureNoteData) -> str:
    """Render the file name from `[obsidian].filename_pattern`.

    Supported placeholders: {capture_date}, {video_stem}, {capture_name}.
    """
    return pattern.format(
        capture_date=data.capture_date,
        video_stem=data.video_stem,
        capture_name=data.capture_name,
    )


@dataclass
class WriteResult:
    note_path: Path
    backed_up_to: Path | None
    preserved_user_tail: bool


def write_capture_note(
    cfg: ObsidianConfig,
    data: CaptureNoteData,
) -> WriteResult | None:
    """Create or update the capture note in the configured Obsidian vault.

    Returns:
        WriteResult — path + whether we preserved a user-tail / backed up
        None      — if Obsidian integration is disabled or the vault is missing
    """
    if not cfg.enabled:
        logger.debug("obsidian.disabled")
        return None

    # Phase 8 B1: vault-agnostic default is empty string. Warn loudly when
    # enabled but vault_path is unset — user needs to set it per their vault.
    if str(cfg.vault_path) in ("", "."):
        logger.warning(
            "obsidian.vault_unset",
            hint="[obsidian].enabled=true but vault_path is empty. Set vault_path in your config.",
        )
        return None

    if not cfg.vault_path.exists():
        logger.warning("obsidian.vault_missing", path=str(cfg.vault_path))
        return None

    target_dir = cfg.vault_path / cfg.captures_subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = _format_filename(cfg.filename_pattern, data)
    note_path = target_dir / filename

    preserved_tail: str | None = None
    backed_up_to: Path | None = None
    existing_frontmatter: dict[str, Any] = {}

    if note_path.exists():
        existing = note_path.read_text(encoding="utf-8")
        existing_frontmatter = _parse_existing_frontmatter(existing)
        if AUTO_BLOCK_END in existing:
            preserved_tail = _extract_user_tail(existing)
        else:
            # No markers → conservative: back up the existing file, write fresh.
            backed_up_to = note_path.with_suffix(note_path.suffix + ".bak")
            backed_up_to.write_text(existing, encoding="utf-8")
            logger.warning(
                "obsidian.unmarked_overwrite_backed_up",
                original=str(note_path),
                backup=str(backed_up_to),
            )

    new_content = render_note(data, existing_frontmatter=existing_frontmatter)
    if preserved_tail is not None and preserved_tail.strip():
        # Replace the auto-block-trailing default Notes section with the user tail.
        new_content = _AUTO_RE.sub(
            f"{AUTO_BLOCK_START}\n{_render_auto_block(data)}\n{AUTO_BLOCK_END}",
            new_content,
            count=1,
        )
        # The default tail (the `## Notes …` section we write) becomes the user tail.
        # Trim everything after END in new_content and replace with preserved tail.
        cutoff = new_content.find(AUTO_BLOCK_END)
        new_content = new_content[: cutoff + len(AUTO_BLOCK_END)] + "\n\n" + preserved_tail.lstrip()

    note_path.write_text(new_content, encoding="utf-8")
    logger.info(
        "obsidian.note_written",
        path=str(note_path),
        preserved_user_tail=bool(preserved_tail and preserved_tail.strip()),
        backup=str(backed_up_to) if backed_up_to else None,
    )
    return WriteResult(
        note_path=note_path,
        backed_up_to=backed_up_to,
        preserved_user_tail=bool(preserved_tail and preserved_tail.strip()),
    )
