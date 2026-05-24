# SPDX-License-Identifier: AGPL-3.0-or-later

"""Phase-4 obsidian capture-note generator tests.

Coverage:
  - PLY header parser pulls gaussian count + SH degree (with comment + by inference)
  - CaptureNoteData schema validation (date format)
  - render_note shape + frontmatter content
  - write_capture_note: enabled vs disabled, missing vault, fresh write,
    re-write with marker preservation, .bak fallback when markers absent
  - filename_pattern templating
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autosplat.config import ObsidianConfig
from autosplat.obsidian import (
    AUTO_BLOCK_END,
    AUTO_BLOCK_START,
    CaptureNoteData,
    _format_filename,
    read_ply_header,
    render_note,
    write_capture_note,
)

# ─── Fixture helpers ────────────────────────────────────────────────────────


def _vault(tmp_path: Path) -> Path:
    v = tmp_path / "vault"
    v.mkdir()
    return v


def _cfg(vault: Path, *, enabled: bool = True, **overrides) -> ObsidianConfig:
    base = {
        "enabled": enabled,
        "vault_path": vault,
        "captures_subdir": "3D Memories",
        "attach_ply": False,
        "filename_pattern": "{capture_date} {video_stem}.md",
        "default_tags": ["3d-memory", "gaussian-splat", "auto-splat"],
        "frontmatter_type": "capture",
    }
    base.update(overrides)
    return ObsidianConfig(**base)


def _data(**overrides) -> CaptureNoteData:
    base = {
        "capture_date": "2026-05-14",
        "capture_name": "2026-05-14_bench_chill",
        "source_video": "/import/bench_chill.MP4",
        "video_stem": "bench_chill",
        "frame_count_extracted": 107,
        "frame_count_kept": 107,
        "cameras_registered": 107,
        "points3d": 53222,
        "gaussians": 82172,
        "sh_degree": 3,
        "training_duration_s": 281.6,
        "total_duration_s": 435.6,
        "output_ply": "/outputs/2026-05-14_bench_chill/scene.ply",
        "output_ply_size_bytes": 19394142,
    }
    base.update(overrides)
    return CaptureNoteData(**base)


def _make_ply(path: Path, *, vertex_count: int, sh_comment: int | None, f_rest_count: int) -> None:
    """Write a tiny PLY with the header lines we care about. No payload."""
    header_lines = ["ply", "format binary_little_endian 1.0", "comment Exported from Brush"]
    if sh_comment is not None:
        header_lines.append(f"comment SH degree: {sh_comment}")
    header_lines.append(f"element vertex {vertex_count}")
    for i in range(f_rest_count):
        header_lines.append(f"property float f_rest_{i}")
    header_lines.append("property float x")
    header_lines.append("end_header")
    payload = b"\x00" * 16  # arbitrary binary tail
    path.write_bytes("\n".join(header_lines).encode("ascii") + b"\n" + payload)


# ─── PLY header parser ──────────────────────────────────────────────────────


def test_read_ply_header_uses_comment_when_available(tmp_path: Path) -> None:
    p = tmp_path / "scene.ply"
    _make_ply(p, vertex_count=82172, sh_comment=3, f_rest_count=0)
    assert read_ply_header(p) == {"gaussians": 82172, "sh_degree": 3}


def test_read_ply_header_infers_sh_from_f_rest_count(tmp_path: Path) -> None:
    """f_rest_count=45 means SH degree 3 (3*((3+1)^2 - 1) = 45)."""
    p = tmp_path / "scene.ply"
    _make_ply(p, vertex_count=1000, sh_comment=None, f_rest_count=45)
    assert read_ply_header(p)["sh_degree"] == 3


def test_read_ply_header_infers_sh_degree_2(tmp_path: Path) -> None:
    """f_rest_count=24 means SH degree 2 (3*((2+1)^2 - 1) = 24)."""
    p = tmp_path / "scene.ply"
    _make_ply(p, vertex_count=1000, sh_comment=None, f_rest_count=24)
    assert read_ply_header(p)["sh_degree"] == 2


def test_read_ply_header_missing_file(tmp_path: Path) -> None:
    assert read_ply_header(tmp_path / "nope.ply") == {"gaussians": 0, "sh_degree": 0}


# ─── CaptureNoteData schema ─────────────────────────────────────────────────


def test_capture_note_data_rejects_bad_date() -> None:
    with pytest.raises(Exception):
        _data(capture_date="14.05.2026")  # Not ISO


def test_capture_note_data_default_tags_when_unset() -> None:
    data = CaptureNoteData(
        capture_date="2026-05-14",
        capture_name="cn",
        source_video="/v.mp4",
        video_stem="v",
        frame_count_extracted=10,
        frame_count_kept=10,
        cameras_registered=10,
        points3d=100,
        gaussians=1000,
        sh_degree=3,
        training_duration_s=1.0,
        total_duration_s=2.0,
        output_ply="/o.ply",
        output_ply_size_bytes=1024,
    )
    assert "gaussian-splat" in data.tags


# ─── render_note ────────────────────────────────────────────────────────────


def test_render_note_includes_frontmatter_and_markers() -> None:
    text = render_note(_data())
    assert text.startswith("---\n")
    assert "type: capture" in text
    # PyYAML quotes date-like strings; both '2026-05-14' and "2026-05-14" are
    # valid YAML and parse to the same string. Just check the date is present.
    assert "2026-05-14" in text
    assert "gaussians: 82172" in text
    assert "sh_degree: 3" in text
    # PyYAML defaults to block-style for lists — also valid for Obsidian.
    for tag in ("3d-memory", "gaussian-splat", "auto-splat"):
        assert tag in text
    assert AUTO_BLOCK_START in text
    assert AUTO_BLOCK_END in text
    assert "## Notes" in text  # default user-tail
    assert "embed_url: null" in text


def test_render_note_includes_iframe_when_embed_url_set() -> None:
    text = render_note(_data(embed_url="https://playcanvas.com/x/abc"))
    assert "<iframe" in text
    assert "https://playcanvas.com/x/abc" in text


def test_render_note_formats_ply_size_in_mb() -> None:
    text = render_note(_data(output_ply_size_bytes=20 * 1024 * 1024))
    assert "20.0 MB" in text


# ─── write_capture_note — disabled + missing vault ─────────────────────────


def test_write_returns_none_when_disabled(tmp_path: Path) -> None:
    cfg = _cfg(_vault(tmp_path), enabled=False)
    assert write_capture_note(cfg, _data()) is None


def test_write_returns_none_when_vault_missing(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "doesnt-exist", enabled=True)
    assert write_capture_note(cfg, _data()) is None


# ─── write_capture_note — fresh write ──────────────────────────────────────


def test_write_creates_subdir_and_file(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    cfg = _cfg(vault)
    result = write_capture_note(cfg, _data())
    assert result is not None
    expected = vault / "3D Memories" / "2026-05-14 bench_chill.md"
    assert result.note_path == expected
    assert expected.exists()
    assert result.preserved_user_tail is False
    assert result.backed_up_to is None


def test_filename_pattern_supports_capture_name(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    cfg = _cfg(vault, filename_pattern="{capture_name}.md")
    result = write_capture_note(cfg, _data())
    assert result.note_path.name == "2026-05-14_bench_chill.md"


def test_format_filename_helper_accepts_known_placeholders() -> None:
    name = _format_filename("{capture_date}_{video_stem}_{capture_name}.md", _data())
    assert name == "2026-05-14_bench_chill_2026-05-14_bench_chill.md"


# ─── write_capture_note — re-run preserves user tail ───────────────────────


def test_rewrite_preserves_user_tail(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    cfg = _cfg(vault)

    # First write — pristine.
    write_capture_note(cfg, _data())

    # Simulate user edit: append free-form notes after the auto-block.
    existing = (vault / "3D Memories" / "2026-05-14 bench_chill.md").read_text()
    user_addition = (
        existing + "\n## My field notes\nGreat shot of the bench in low-angle sunlight.\n"
    )
    (vault / "3D Memories" / "2026-05-14 bench_chill.md").write_text(user_addition)

    # Second write — stats changed (more gaussians after a re-train).
    new_data = _data(gaussians=99000)
    result = write_capture_note(cfg, new_data)
    assert result.preserved_user_tail is True
    assert result.backed_up_to is None

    final = (vault / "3D Memories" / "2026-05-14 bench_chill.md").read_text()
    # New stat present
    assert "gaussians: 99000" in final
    # User content preserved
    assert "My field notes" in final
    assert "low-angle sunlight" in final


def test_rewrite_without_markers_creates_backup(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    cfg = _cfg(vault)
    target = vault / "3D Memories" / "2026-05-14 bench_chill.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Hand-typed note\nNo markers here, all user content.\n")

    result = write_capture_note(cfg, _data())
    assert result.backed_up_to is not None
    assert result.backed_up_to.exists()
    assert "Hand-typed note" in result.backed_up_to.read_text()
    # Fresh content was written to the original path
    assert AUTO_BLOCK_START in target.read_text()


# ─── frontmatter_type can be customised ────────────────────────────────────


def test_frontmatter_type_uses_config_value(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    cfg = _cfg(vault, frontmatter_type="3d-capture")
    data = _data()
    data.frontmatter_type = "3d-capture"
    result = write_capture_note(cfg, data)
    text = result.note_path.read_text()
    assert "type: 3d-capture" in text


# ─── Phase 8 B6 — Frontmatter user-key-preservation ─────────────────────────


def test_rewrite_preserves_user_added_frontmatter_keys(tmp_path: Path) -> None:
    """Keys the user added (location, weather, etc.) survive a re-write."""
    vault = _vault(tmp_path)
    cfg = _cfg(vault)

    # First write — pristine
    write_capture_note(cfg, _data())

    # Simulate user editing the frontmatter — adds a `location` key
    note_path = vault / "3D Memories" / "2026-05-14 bench_chill.md"
    text = note_path.read_text()
    user_edit = text.replace(
        "tags:",
        "location: Kissing, Burgstall\nflight_notes: low evening sun\ntags:",
        1,
    )
    note_path.write_text(user_edit)

    # Re-run with updated stats
    write_capture_note(cfg, _data(gaussians=99000))

    final = note_path.read_text()
    assert "gaussians: 99000" in final  # stats overwritten
    assert "location: Kissing, Burgstall" in final  # user key preserved
    assert "flight_notes: low evening sun" in final  # user key preserved


def test_rewrite_preserves_user_set_embed_url(tmp_path: Path) -> None:
    """If user filled `embed_url:` and our new data has it None, keep the user's."""
    vault = _vault(tmp_path)
    cfg = _cfg(vault)

    # First write — no embed_url yet
    write_capture_note(cfg, _data())
    note_path = vault / "3D Memories" / "2026-05-14 bench_chill.md"

    # User fills it in (manually editing the frontmatter — common smoke-test path)
    text = note_path.read_text()
    user_edit = text.replace("embed_url: null", "embed_url: https://superspl.at/scene/abc123")
    note_path.write_text(user_edit)

    # Re-run — data still has embed_url=None
    write_capture_note(cfg, _data(gaussians=99000))

    final = note_path.read_text()
    assert "https://superspl.at/scene/abc123" in final
    assert "gaussians: 99000" in final


def test_rewrite_lets_new_embed_url_win_over_old(tmp_path: Path) -> None:
    """If a NEW run carries an embed_url, it wins over the old one (truth-source flow)."""
    vault = _vault(tmp_path)
    cfg = _cfg(vault)

    write_capture_note(cfg, _data(embed_url="https://old/scene/x"))
    write_capture_note(cfg, _data(embed_url="https://new/scene/y"))

    note_path = vault / "3D Memories" / "2026-05-14 bench_chill.md"
    final = note_path.read_text()
    assert "https://new/scene/y" in final
    assert "https://old/scene/x" not in final


def test_rewrite_overwrites_cowork_managed_keys(tmp_path: Path) -> None:
    """Stats are Cowork-managed — they always get updated, even if user edited them."""
    vault = _vault(tmp_path)
    cfg = _cfg(vault)

    write_capture_note(cfg, _data(gaussians=1000))
    note_path = vault / "3D Memories" / "2026-05-14 bench_chill.md"

    # User stupidly edits a Cowork-managed key — should get overwritten
    text = note_path.read_text()
    text = text.replace("gaussians: 1000", "gaussians: 99999")
    note_path.write_text(text)

    write_capture_note(cfg, _data(gaussians=2000))
    final = note_path.read_text()
    assert "gaussians: 2000" in final
    assert "gaussians: 99999" not in final
