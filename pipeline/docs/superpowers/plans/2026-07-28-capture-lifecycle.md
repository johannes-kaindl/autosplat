# Capture Lifecycle & Storage Retention — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a capture an explicit, filesystem-derived lifecycle and hang storage retention off it, so intermediates are reclaimed once a human signs off — and reclaim the existing ~9,6 GB backlog through an explicit, previewable command.

**Architecture:** A new pure module `lifecycle.py` becomes the single source of truth for "what state is this capture in and what may be reclaimed". `cleanup.py` degrades to the executor, `webui/state.py` delegates instead of re-deriving, and the v1.15.0 review routes become the reclaim trigger. Nothing about the lifecycle is persisted — it is derived from files and mtimes, exactly like the existing review marker.

**Tech Stack:** Python 3.11+, uv, Pydantic v2 (config), FastAPI + Jinja2 (WebUI), Typer (CLI), pytest.

**Spec:** `docs/superpowers/specs/2026-07-28-capture-lifecycle-design.md`

## Global Constraints

- All paths in this plan are relative to `pipeline/` (the repo is a monorepo; `cd pipeline` first).
- Every source file starts with `# SPDX-License-Identifier: AGPL-3.0-or-later`.
- `from __future__ import annotations` at the top of every module.
- mypy runs in **strict** mode — every new function is fully typed.
- Ruff: line-length 100, target py311. Do not hand-format; run `uv run ruff format src/ tests/`.
- TDD, red first. Before every commit: `uv run pytest -q` (506 tests must stay green), `uv run ruff check src/ tests/`, `uv run mypy src/`.
- Commit messages: conventional commits, and every commit ends with the trailer
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- No persistent lifecycle state may be written. Deriving from the filesystem is a hard design constraint, not a preference.
- Never reclaim a directory that holds a capture's only PLY.

## File Structure

| File | Responsibility |
|---|---|
| `src/autosplat/lifecycle.py` **(new)** | Derives lifecycle state + reclaimable targets. Pure, read-only. |
| `src/autosplat/cleanup.py` | Executes reclaims. Targets come from `lifecycle`. Gains the grace sweep. |
| `src/autosplat/config.py` | New `LifecycleConfig`; `ExportConfig.copy_to_outputs` deprecated. |
| `config/default.toml` | New `[lifecycle]` section; `copy_to_outputs = false`. |
| `src/autosplat/export.py` | Stops writing to `outputs_dir`. |
| `src/autosplat/doctor.py` | Warns when `copy_to_outputs` is still true. |
| `src/autosplat/webui/state.py` | Delegates review/lifecycle derivation; carries new display fields. |
| `src/autosplat/webui/templates/partials/captures_list_inner.html` | Grace warning per row. |
| `src/autosplat/webui/templates/capture/detail.html` | Shows what the review will reclaim. |
| `src/autosplat/webui/routes/captures.py` | Review routes trigger the reclaim (guarded against live jobs); passes the grace period to `list_captures`. |
| `tests/webui/conftest.py` | `app` fixture redirected to a temp captures dir (safety). |
| `src/autosplat/webui/share_runner.py` | Writes the SOG to `output/scene.sog` and reuses it. |
| `src/autosplat/webui/app.py` | Starts the grace sweep in the lifespan hook. |
| `src/autosplat/cli.py` | New `migrate-storage` command. |
| `tests/test_lifecycle.py` **(new)** | State table, grace boundaries, recursive discovery. |
| `tests/test_cli_migrate_storage.py` **(new)** | Dry-run purity, `--apply`, PLY safety rule. |

---

### Task 1: `lifecycle.py` — state model and config

**Files:**
- Create: `src/autosplat/lifecycle.py`
- Modify: `src/autosplat/config.py` (add `LifecycleConfig`, register on `Config`)
- Modify: `config/default.toml` (add `[lifecycle]`)
- Test: `tests/test_lifecycle.py` (new)

**Interfaces:**
- Consumes: nothing — this is the foundation task.
- Produces:
  - `LifecycleState = Literal["failed", "done", "reviewed", "archived"]`
  - `Lifecycle` dataclass: `.state`, `.reclaimable: list[Path]`, `.reclaimable_bytes: int`, `.grace_days_left: int | None`
  - `inspect(capture_dir: Path, *, now: datetime, grace_days: int) -> Lifecycle`
  - `review_status(capture_dir: Path) -> ReviewStatus` where `ReviewStatus = Literal["unreviewed", "reviewed"]`
  - `review_marker_path(capture_dir: Path) -> Path`
  - `resolve_publish_ply(capture_dir: Path, status: ReviewStatus) -> Path | None`
  - `find_capture_dirs(root: Path) -> list[Path]`
  - `RECLAIMABLE_SUBDIRS: tuple[str, ...]`
  - `cfg.lifecycle.unreviewed_grace_days: int`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lifecycle.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autosplat import lifecycle


def _make_capture(root: Path, name: str, *, with_ply: bool = True) -> Path:
    capture = root / name
    (capture / "output").mkdir(parents=True)
    if with_ply:
        (capture / "output" / "scene.ply").write_bytes(b"ply\nend_header\n")
    return capture


def _mark_reviewed(capture: Path) -> None:
    ply = capture / "output" / "scene.ply"
    marker = capture / "output" / ".review.json"
    marker.write_text(
        json.dumps({"source_ply_mtime": ply.stat().st_mtime}), encoding="utf-8"
    )


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def test_failed_when_no_ply(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x", with_ply=False)
    (capture / "colmap").mkdir()

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.state == "failed"
    assert result.reclaimable == []  # failed keeps everything for diagnosis


def test_done_when_ply_but_no_marker(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.state == "done"
    assert result.reclaimable == []  # not reclaimable until reviewed or grace expires


def test_reviewed_exposes_reclaimable_targets(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    (capture / "rescue").mkdir()
    (capture / "brush_dataset").mkdir()
    (capture / "colmap" / "db.bin").write_bytes(b"x" * 100)
    _mark_reviewed(capture)

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.state == "reviewed"
    assert {p.name for p in result.reclaimable} == {"colmap", "rescue", "brush_dataset"}
    assert result.reclaimable_bytes == 100


def test_archived_when_reviewed_and_nothing_left(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    _mark_reviewed(capture)

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.state == "archived"
    assert result.reclaimable_bytes == 0


def test_share_tmp_is_reclaimable(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "share" / "_tmp").mkdir(parents=True)
    (capture / "share" / "_tmp" / "scene.sog").write_bytes(b"y" * 50)
    (capture / "share" / "tok").mkdir()  # a real bundle — must NOT be reclaimed
    _mark_reviewed(capture)

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert [p.name for p in result.reclaimable] == ["_tmp"]
    assert result.reclaimable_bytes == 50


def test_marker_invalidated_by_rebuilt_ply(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    _mark_reviewed(capture)
    ply = capture / "output" / "scene.ply"
    import os

    os.utime(ply, (1_000_000, 1_000_000))  # simulate a rebuild

    assert lifecycle.review_status(capture) == "unreviewed"
    assert lifecycle.inspect(capture, now=NOW, grace_days=30).state == "done"


def test_reviewed_ply_preferred_when_reviewed(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "output" / "scene_reviewed.ply").write_bytes(b"ply\n")
    _mark_reviewed(capture)

    resolved = lifecycle.resolve_publish_ply(capture, "reviewed")

    assert resolved is not None
    assert resolved.name == "scene_reviewed.ply"


@pytest.mark.parametrize(
    ("age_days", "expected_left"),
    [(0, 30), (23, 7), (30, 0), (45, 0)],
)
def test_grace_days_left_counts_down(tmp_path: Path, age_days: int, expected_left: int) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    import os

    mtime = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(capture / "output" / "scene.ply", (mtime, mtime))

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.state == "done"
    assert result.grace_days_left == expected_left


def test_grace_expiry_makes_targets_reclaimable(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    (capture / "colmap" / "db.bin").write_bytes(b"z" * 10)
    import os

    mtime = (NOW - timedelta(days=31)).timestamp()
    os.utime(capture / "output" / "scene.ply", (mtime, mtime))

    result = lifecycle.inspect(capture, now=NOW, grace_days=30)

    assert result.grace_days_left == 0
    assert [p.name for p in result.reclaimable] == ["colmap"]


def test_grace_disabled_never_expires(tmp_path: Path) -> None:
    capture = _make_capture(tmp_path, "2026-07-01_x")
    (capture / "colmap").mkdir()
    import os

    mtime = (NOW - timedelta(days=999)).timestamp()
    os.utime(capture / "output" / "scene.ply", (mtime, mtime))

    result = lifecycle.inspect(capture, now=NOW, grace_days=0)

    assert result.grace_days_left is None
    assert result.reclaimable == []


def test_find_capture_dirs_finds_nested_legacy_layout(tmp_path: Path) -> None:
    # Reproduces 2026-05-25_max_strasse_rescue/2026-05-25_A_vor1 (8,1 GB on disk)
    outer = tmp_path / "2026-05-25_max_strasse_rescue"
    inner = outer / "2026-05-25_A_vor1"
    (inner / "output").mkdir(parents=True)
    (inner / "output" / "scene.ply").write_bytes(b"ply\n")
    (inner / "frames").mkdir()
    (inner / "colmap").mkdir()

    found = lifecycle.find_capture_dirs(tmp_path)

    assert inner in found
    assert outer not in found  # the shell holds no PLY and no frames+colmap of its own


def test_find_capture_dirs_finds_unfinished_capture(tmp_path: Path) -> None:
    capture = tmp_path / "2026-07-01_x"
    (capture / "frames").mkdir(parents=True)
    (capture / "colmap").mkdir()

    assert lifecycle.find_capture_dirs(tmp_path) == [capture]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd pipeline && uv run pytest tests/test_lifecycle.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'autosplat.lifecycle'`

- [ ] **Step 3: Write `src/autosplat/lifecycle.py`**

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Derives a capture's lifecycle state and what may be reclaimed from it.

Single source of truth for retention. Pure and read-only: state is DERIVED
from files and mtimes, never stored. That is what makes the v1.15.0 review
gate correct — a rebuilt scene.ply invalidates everything downstream by mtime
alone, with no bookkeeping to keep in sync — and this module preserves it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

LifecycleState = Literal["failed", "done", "reviewed", "archived"]
ReviewStatus = Literal["unreviewed", "reviewed"]

# Working dirs that hold nothing worth keeping once the scene is signed off.
# `training` predates the current pipeline but still exists in legacy captures.
# `source` is deliberately absent — see the design doc: sub-project 4 decides
# whether the source video belongs in a capture at all.
RECLAIMABLE_SUBDIRS: tuple[str, ...] = (
    "frames",
    "colmap",
    "training",
    "brush_dataset",
    "rescue",
)

# Reclaimable paths that are not top-level subdirs of the same shape.
_EXTRA_RECLAIMABLE: tuple[tuple[str, ...], ...] = (("share", "_tmp"),)


@dataclass(frozen=True)
class Lifecycle:
    state: LifecycleState
    reclaimable: list[Path]
    reclaimable_bytes: int
    grace_days_left: int | None


def review_marker_path(capture_dir: Path) -> Path:
    """Where the publish-quality-gate review marker lives for a capture."""
    return capture_dir / "output" / ".review.json"


def review_status(capture_dir: Path) -> ReviewStatus:
    """Compute review status from the marker file vs. output/scene.ply's mtime.

    Purely mtime-based invalidation: a rebuilt scene.ply (different mtime)
    silently reverts the capture to unreviewed, so callers that regenerate
    scene.ply (add-video, resume) need no awareness of review state at all.
    """
    marker = review_marker_path(capture_dir)
    if not marker.exists():
        return "unreviewed"
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreviewed"
    if not isinstance(data, dict):
        return "unreviewed"
    recorded_mtime = data.get("source_ply_mtime")
    scene_ply = capture_dir / "output" / "scene.ply"
    try:
        current_mtime = scene_ply.stat().st_mtime
    except OSError:
        return "unreviewed"
    if recorded_mtime != current_mtime:
        return "unreviewed"
    return "reviewed"


def find_ply(capture_dir: Path) -> Path | None:
    """The capture's canonical PLY, newest layout first."""
    for candidate in [
        capture_dir / "output" / "scene.ply",
        capture_dir / "scene.ply",
    ]:
        if candidate.exists():
            return candidate
    plys = sorted(capture_dir.glob("*.ply"))
    return plys[0] if plys else None


def resolve_publish_ply(capture_dir: Path, status: ReviewStatus) -> Path | None:
    """Which PLY represents this capture for viewing/sharing.

    Prefers the manually-cleaned output/scene_reviewed.ply once the capture
    is reviewed and that file exists; otherwise falls back to find_ply. A
    stale scene_reviewed.ply left over from before a rebuild is automatically
    skipped once `status` recomputes to unreviewed.
    """
    if status == "reviewed":
        reviewed_ply = capture_dir / "output" / "scene_reviewed.ply"
        if reviewed_ply.exists():
            return reviewed_ply
    return find_ply(capture_dir)


def reclaimable_targets(capture_dir: Path) -> list[Path]:
    """Existing working dirs of `capture_dir`, regardless of lifecycle state."""
    targets = [capture_dir / sub for sub in RECLAIMABLE_SUBDIRS]
    targets += [capture_dir.joinpath(*parts) for parts in _EXTRA_RECLAIMABLE]
    return [t for t in targets if t.is_dir()]


def bytes_in(targets: list[Path]) -> int:
    total = 0
    for target in targets:
        for p in target.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    return total


def _days_since(path: Path, now: datetime) -> int:
    age = now.timestamp() - path.stat().st_mtime
    return max(0, int(age // 86400))


def inspect(capture_dir: Path, *, now: datetime, grace_days: int) -> Lifecycle:
    """Derive lifecycle state and reclaimable targets for one capture.

    `grace_days` of 0 disables the unreviewed grace sweep entirely: an
    unreviewed capture then stays untouched forever.
    """
    ply = find_ply(capture_dir)
    if ply is None:
        # No PLY means the run never finished. Diagnosis needs colmap/ and
        # rescue/, so a failed capture keeps everything.
        return Lifecycle(state="failed", reclaimable=[], reclaimable_bytes=0, grace_days_left=None)

    targets = reclaimable_targets(capture_dir)

    if review_status(capture_dir) == "reviewed":
        state: LifecycleState = "archived" if not targets else "reviewed"
        return Lifecycle(
            state=state,
            reclaimable=targets,
            reclaimable_bytes=bytes_in(targets),
            grace_days_left=None,
        )

    if grace_days <= 0:
        return Lifecycle(state="done", reclaimable=[], reclaimable_bytes=0, grace_days_left=None)

    days_left = max(0, grace_days - _days_since(ply, now))
    if days_left > 0:
        # Still within the grace window — quality is unconfirmed, keep everything.
        return Lifecycle(
            state="done", reclaimable=[], reclaimable_bytes=0, grace_days_left=days_left
        )
    return Lifecycle(
        state="done",
        reclaimable=targets,
        reclaimable_bytes=bytes_in(targets),
        grace_days_left=0,
    )


def _looks_like_capture(path: Path) -> bool:
    if (path / "output" / "scene.ply").exists() or (path / "scene.ply").exists():
        return True
    return (path / "frames").is_dir() and (path / "colmap").is_dir()


def find_capture_dirs(root: Path) -> list[Path]:
    """All capture directories under `root`, including nested legacy layouts.

    Pre-Phase-9 rescue runs nested a whole capture inside another directory
    (2026-05-25_max_strasse_rescue/2026-05-25_A_vor1). A non-recursive scan
    misses those entirely — which is how 8,1 GB stayed invisible to cleanup.
    Recursion stops at a directory that is itself a capture: its `rescue/`
    subtree is reclaimable as a whole, not a set of separate captures.
    """
    found: list[Path] = []
    if not root.is_dir():
        return found
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            continue
        if entry.name in RECLAIMABLE_SUBDIRS or entry.name == "output":
            continue
        if _looks_like_capture(entry):
            found.append(entry)
        else:
            found.extend(find_capture_dirs(entry))
    return found
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/test_lifecycle.py -q`
Expected: PASS (13 tests)

- [ ] **Step 5: Add the config section — failing test first**

Append to `tests/test_config.py`:

```python
def test_lifecycle_defaults_to_30_day_grace() -> None:
    cfg = load_config(include_xdg=False)

    assert cfg.lifecycle.unreviewed_grace_days == 30


def test_copy_to_outputs_defaults_to_false() -> None:
    cfg = load_config(include_xdg=False)

    assert cfg.export.copy_to_outputs is False
```

Note: `load_config` is already imported at the top of `tests/test_config.py`; do not add a second import.

- [ ] **Step 6: Run to verify it fails**

Run: `cd pipeline && uv run pytest tests/test_config.py -q -k "lifecycle or copy_to_outputs"`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'lifecycle'`

- [ ] **Step 7: Add `LifecycleConfig` to `config.py`**

Insert directly above `class Config(BaseModel):` (currently `config.py:413`):

```python
class LifecycleConfig(BaseModel):
    """Retention policy for capture working dirs (see lifecycle.py)."""

    unreviewed_grace_days: int = Field(
        default=30,
        ge=0,
        description=(
            "Days after which an unreviewed capture's intermediates are reclaimed "
            "anyway. 0 disables the grace sweep entirely."
        ),
    )
```

Then register it on `Config` (after the `share` line at `config.py:429`):

```python
    lifecycle: LifecycleConfig = Field(default_factory=LifecycleConfig)
```

- [ ] **Step 8: Add `[lifecycle]` to `config/default.toml`**

Append at the end of the file:

```toml
[lifecycle]
# Retention policy. Intermediates (frames/, colmap/, training/, brush_dataset/,
# rescue/, share/_tmp/) are reclaimed once a capture is reviewed via the publish
# quality gate. A capture that is never reviewed is reclaimed anyway after this
# many days, announced in the captures list beforehand. 0 disables that fallback.
unreviewed_grace_days = 30
```

And change the existing `copy_to_outputs = true` in the `[export]` section to:

```toml
copy_to_outputs = false         # DEPRECATED — outputs_dir is no longer written; see docs/CONFIGURATION.md
```

- [ ] **Step 9: Run the full suite**

Run: `cd pipeline && uv run pytest -q && uv run ruff check src/ tests/ && uv run mypy src/`
Expected: all green. `tests/test_export.py` may now fail on the `copy_to_outputs` default — if so, leave it failing and fix it in Task 5, but note it in the commit message.

- [ ] **Step 10: Commit**

```bash
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/lifecycle.py pipeline/src/autosplat/config.py pipeline/config/default.toml pipeline/tests/test_lifecycle.py pipeline/tests/test_config.py
git commit -m "$(cat <<'EOF'
feat(pipeline): derive capture lifecycle state from the filesystem

New lifecycle.py is the single source of truth for retention: it derives
failed/done/reviewed/archived from files and mtimes and reports what may be
reclaimed. Nothing is persisted, preserving the v1.15.0 property that a
rebuilt PLY invalidates review state by mtime alone.

find_capture_dirs() recurses into nested pre-Phase-9 layouts, where a whole
capture sits inside another directory — the reason 8,1 GB stayed invisible
to cleanup.

Adds [lifecycle] unreviewed_grace_days (default 30).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `cleanup.py` reclaims what lifecycle reports

**Files:**
- Modify: `src/autosplat/cleanup.py` (whole file — it is 61 lines)
- Test: `tests/test_cleanup.py`

**Interfaces:**
- Consumes: `lifecycle.inspect`, `lifecycle.reclaimable_targets`, `lifecycle.bytes_in`, `lifecycle.find_ply`
- Produces:
  - `prune_intermediates(capture_dir: Path, *, dry_run: bool = False) -> PruneResult` (unchanged signature)
  - `PruneResult` gains `.failed: list[Path]`
  - `sweep_expired(captures_dir: Path, *, grace_days: int, now: datetime) -> list[PruneResult]`
  - `INTERMEDIATE_SUBDIRS` stays exported as an alias of `lifecycle.RECLAIMABLE_SUBDIRS` for backwards compatibility

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cleanup.py`:

```python
def test_prune_removes_rescue_and_brush_dataset(tmp_path: Path) -> None:
    # Regression: INTERMEDIATE_SUBDIRS listed only frames/colmap/training, so
    # 11,2 GB of bisection-rescue leftovers were never reclaimed.
    capture = tmp_path / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n")
    for sub in ("frames", "colmap", "rescue", "brush_dataset"):
        (capture / sub).mkdir()
        (capture / sub / "blob").write_bytes(b"x" * 10)

    result = cleanup.prune_intermediates(capture)

    assert {p.name for p in result.removed} == {"frames", "colmap", "rescue", "brush_dataset"}
    assert result.bytes_reclaimed == 40
    assert not (capture / "rescue").exists()
    assert not (capture / "brush_dataset").exists()
    assert (capture / "output" / "scene.ply").exists()


def test_prune_removes_share_tmp_but_keeps_bundles(tmp_path: Path) -> None:
    capture = tmp_path / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n")
    (capture / "share" / "_tmp").mkdir(parents=True)
    (capture / "share" / "tok").mkdir()

    cleanup.prune_intermediates(capture)

    assert not (capture / "share" / "_tmp").exists()
    assert (capture / "share" / "tok").exists()


def test_prune_is_idempotent(tmp_path: Path) -> None:
    capture = tmp_path / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n")
    (capture / "colmap").mkdir()

    cleanup.prune_intermediates(capture)
    second = cleanup.prune_intermediates(capture)

    assert second.removed == []
    assert second.bytes_reclaimed == 0


def test_sweep_expired_reclaims_only_past_grace(tmp_path: Path) -> None:
    import os
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    for name, age in (("2026-07-01_fresh", 2), ("2026-06-01_old", 40)):
        capture = tmp_path / name
        (capture / "output").mkdir(parents=True)
        (capture / "output" / "scene.ply").write_bytes(b"ply\n")
        (capture / "colmap").mkdir()
        (capture / "colmap" / "blob").write_bytes(b"x" * 5)
        mtime = (now - timedelta(days=age)).timestamp()
        os.utime(capture / "output" / "scene.ply", (mtime, mtime))

    results = cleanup.sweep_expired(tmp_path, grace_days=30, now=now)

    assert len(results) == 1
    assert (tmp_path / "2026-07-01_fresh" / "colmap").exists()
    assert not (tmp_path / "2026-06-01_old" / "colmap").exists()
```

Add to the imports at the top of `tests/test_cleanup.py` if not already present:

```python
from pathlib import Path

from autosplat import cleanup
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd pipeline && uv run pytest tests/test_cleanup.py -q`
Expected: FAIL — `rescue` missing from removed set; `AttributeError: module 'autosplat.cleanup' has no attribute 'sweep_expired'`

- [ ] **Step 3: Rewrite `src/autosplat/cleanup.py`**

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Reclaim disk space held by a finished capture's working dirs.

Executor only — WHAT may be reclaimed is decided by `lifecycle`, so the CLI,
the WebUI and the grace sweep cannot hold three different opinions.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from autosplat import lifecycle
from autosplat.logging import get_logger

logger = get_logger(__name__)

# Backwards-compatible alias — lifecycle owns the list now.
INTERMEDIATE_SUBDIRS = lifecycle.RECLAIMABLE_SUBDIRS


class NotExported(Exception):
    """Raised when a capture hasn't finished exporting yet."""


@dataclass
class PruneResult:
    removed: list[Path]
    bytes_reclaimed: int
    failed: list[Path] = field(default_factory=list)


def is_exported(capture_dir: Path) -> bool:
    return lifecycle.find_ply(capture_dir) is not None


def prunable_targets(capture_dir: Path) -> list[Path]:
    return lifecycle.reclaimable_targets(capture_dir)


def prune_intermediates(capture_dir: Path, *, dry_run: bool = False) -> PruneResult:
    """Delete the working dirs of a capture that finished exporting.

    Raises `NotExported` if no PLY exists — an unfinished capture still needs
    these for `autosplat resume`, and a failed one needs them for diagnosis.

    Partial failures are reported rather than raised: unreclaimed space is
    cosmetic, and because targets are derived from the filesystem the next
    call simply retries whatever is still there.
    """
    if not is_exported(capture_dir):
        raise NotExported(capture_dir)

    targets = prunable_targets(capture_dir)
    removed: list[Path] = []
    failed: list[Path] = []
    total_bytes = 0

    for target in targets:
        size = lifecycle.bytes_in([target])
        if dry_run:
            removed.append(target)
            total_bytes += size
            continue
        try:
            shutil.rmtree(target)
        except OSError as e:
            logger.error("cleanup.prune_failed", target=str(target), error=str(e))
            failed.append(target)
            continue
        removed.append(target)
        total_bytes += size

    return PruneResult(removed=removed, bytes_reclaimed=total_bytes, failed=failed)


def sweep_expired(
    captures_dir: Path,
    *,
    grace_days: int,
    now: datetime,
) -> list[PruneResult]:
    """Reclaim captures whose unreviewed grace period has run out.

    Never raises: a failure on one capture must not stop the sweep, and the
    sweep must never prevent the WebUI/app from starting.
    """
    results: list[PruneResult] = []
    if grace_days <= 0:
        return results

    for capture_dir in lifecycle.find_capture_dirs(captures_dir):
        try:
            state = lifecycle.inspect(capture_dir, now=now, grace_days=grace_days)
            if not state.reclaimable:
                continue
            result = prune_intermediates(capture_dir)
        except Exception as e:  # noqa: BLE001 — a sweep must never break startup
            logger.error("cleanup.sweep_failed", capture=str(capture_dir), error=str(e))
            continue
        logger.info(
            "cleanup.sweep_reclaimed",
            capture=capture_dir.name,
            bytes_reclaimed=result.bytes_reclaimed,
        )
        results.append(result)
    return results
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/test_cleanup.py tests/test_cli_cleanup_intermediates.py -q`
Expected: PASS. If `test_cli_cleanup_intermediates.py` asserts on the old three-item `INTERMEDIATE_SUBDIRS`, update that assertion to the new five — the CLI behaviour is intentionally wider now.

- [ ] **Step 5: Commit**

```bash
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/cleanup.py pipeline/tests/test_cleanup.py pipeline/tests/test_cli_cleanup_intermediates.py
git commit -m "$(cat <<'EOF'
fix(pipeline): reclaim rescue/ and brush_dataset/, not just frames/colmap

INTERMEDIATE_SUBDIRS listed frames, colmap and training only, so bisection
rescue leftovers were never reclaimed — 11,2 of 19 GB on the maintainer's
machine. Targets now come from lifecycle, share/_tmp is included, and
partial failures are reported instead of aborting the run.

Adds sweep_expired() for the grace fallback (wired up in a later task).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `webui/state.py` delegates to lifecycle

**Files:**
- Modify: `src/autosplat/webui/state.py:20-102` (delete the local derivation, import from lifecycle) and the `CaptureInfo` dataclass at `:29-44`
- Modify: `src/autosplat/webui/state.py:109-141` (`list_captures` signature + per-entry lifecycle)
- Test: `tests/webui/test_captures.py`

**Interfaces:**
- Consumes: `lifecycle.inspect`, `lifecycle.review_status`, `lifecycle.resolve_publish_ply`
- Produces: `CaptureInfo.reclaimable_bytes: int`, `CaptureInfo.grace_days_left: int | None`; `list_captures(captures_dir, job_runner=None, *, grace_days=30, now=None)`

- [ ] **Step 1: Write the failing test**

Append to `tests/webui/test_captures.py`:

```python
def test_capture_info_carries_reclaimable_bytes(tmp_path: Path) -> None:
    from autosplat.webui import state as state_mod

    capture = tmp_path / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    ply = capture / "output" / "scene.ply"
    ply.write_bytes(b"ply\n")
    (capture / "colmap").mkdir()
    (capture / "colmap" / "blob").write_bytes(b"x" * 64)
    (capture / "output" / ".review.json").write_text(
        json.dumps({"source_ply_mtime": ply.stat().st_mtime}), encoding="utf-8"
    )

    captures = state_mod.list_captures(tmp_path)

    assert len(captures) == 1
    assert captures[0].review_status == "reviewed"
    assert captures[0].reclaimable_bytes == 64
    assert captures[0].grace_days_left is None
```

Ensure `import json` and `from pathlib import Path` are present at the top of the test file.

- [ ] **Step 2: Run to verify it fails**

Run: `cd pipeline && uv run pytest tests/webui/test_captures.py -q -k reclaimable`
Expected: FAIL — `AttributeError: 'CaptureInfo' object has no attribute 'reclaimable_bytes'`

- [ ] **Step 3: Replace the local derivation in `state.py`**

Delete `_review_status` (`:63-87`), `resolve_publish_ply` (`:90-102`), `_find_ply` (`:47-55`) and `review_marker_path` (`:58-60`), and re-export from lifecycle instead. Replace the `ReviewStatus` definition at `:21` too. At the top of the module, after the existing `from autosplat.watcher import WatcherState`:

```python
from autosplat import lifecycle
from autosplat.lifecycle import (
    ReviewStatus,
    resolve_publish_ply,
    review_marker_path,
)

_find_ply = lifecycle.find_ply
_review_status = lifecycle.review_status
```

Keeping the two private aliases means the rest of the module — and `share_runner.py`, which imports `_review_status` and `resolve_publish_ply` from here — needs no further change.

Then extend the dataclass at `:29`:

```python
    review_status: ReviewStatus = "unreviewed"  # v1.15.0: publish quality gate
    reclaimable_bytes: int = 0  # v1.16.0: lifecycle retention
    grace_days_left: int | None = None
```

- [ ] **Step 4: Feed lifecycle into `list_captures`**

Change the signature at `:109`:

```python
def list_captures(
    captures_dir: Path,
    job_runner: JobRunner | None = None,
    *,
    grace_days: int = 30,
    now: datetime | None = None,
) -> list[CaptureInfo]:
```

Add `from datetime import UTC, datetime` to the module imports. Inside the per-entry loop, replace line `:140-141`

```python
        review_status = _review_status(entry)
        ply = resolve_publish_ply(entry, review_status)
```

with

```python
        life = lifecycle.inspect(entry, now=now or datetime.now(UTC), grace_days=grace_days)
        review_status = _review_status(entry)
        ply = resolve_publish_ply(entry, review_status)
```

and add the two new fields to the `CaptureInfo(...)` construction at `:250`:

```python
                reclaimable_bytes=life.reclaimable_bytes,
                grace_days_left=life.grace_days_left,
```

- [ ] **Step 5: Write the failing test for the grace warning**

The spec requires the captures list to announce the reclaim before it happens. Append to
`tests/webui/test_captures.py`:

```python
def test_list_warns_before_grace_expiry(app: FastAPI, tmp_path: Path) -> None:
    import os
    from datetime import UTC, datetime, timedelta

    capture = tmp_path / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    ply = capture / "output" / "scene.ply"
    ply.write_bytes(b"ply\n")
    (capture / "colmap").mkdir()
    mtime = (datetime.now(UTC) - timedelta(days=25)).timestamp()
    os.utime(ply, (mtime, mtime))
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        body = client.get("/captures").text

    assert "5 days" in body  # 30-day grace, 25 days old
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd pipeline && uv run pytest tests/webui/test_captures.py -q -k grace`
Expected: FAIL — the string is absent

- [ ] **Step 7: Show it in the captures list**

In `src/autosplat/webui/templates/partials/captures_list_inner.html`, inside the PLY-size
cell (currently line 65-69), append the warning after the existing size output:

```jinja
            {% if c.grace_days_left is not none and c.grace_days_left <= 7 %}
              <div class="dim" style="font-size:10px;color:var(--stage-failed)"
                   title="Unreviewed. Intermediates are reclaimed automatically once the grace period ends — review the capture to keep control.">
                cleanup in {{ c.grace_days_left }} days
              </div>
            {% endif %}
```

On the detail page (`capture/detail.html`, near the review panel at line 214), show what is
currently reclaimable so the number is visible before anything happens:

```jinja
            {% if capture.reclaimable_bytes %}
              <p class="dim" style="font-size:11px">
                {{ '%.1f'|format(capture.reclaimable_bytes / 1073741824) }} gb of intermediates
                can be reclaimed — this happens automatically when you complete the review.
              </p>
            {% endif %}
```

- [ ] **Step 8: Pass the configured grace period into the route**

The list route currently calls `list_captures(captures_dir, job_runner)`. Pass the config
value through so the warning respects a user override — in
`src/autosplat/webui/routes/captures.py` and `partials.py`, wherever `list_captures` is
called, add:

```python
        grace_days=request.app.state.cfg.lifecycle.unreviewed_grace_days,
```

Guard for `cfg is None` (uvicorn `--factory` mode builds the app without one) by falling
back to the default: `getattr(request.app.state.cfg, "lifecycle", None)`. Find every call
site with `grep -rn "list_captures(" src/autosplat/`.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/webui -q && uv run mypy src/`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/webui/state.py pipeline/src/autosplat/webui/routes/ pipeline/src/autosplat/webui/templates/ pipeline/tests/webui/test_captures.py
git commit -m "$(cat <<'EOF'
refactor(webui): derive review + retention state from lifecycle

state.py had its own copy of the review-marker logic while cleanup.py had
its own idea of what is disposable. Both now come from lifecycle; CaptureInfo
carries reclaimable_bytes and grace_days_left, and the captures list warns
before the grace period reclaims anything.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Review sign-off triggers the reclaim

**Files:**
- Modify: `src/autosplat/webui/routes/captures.py:440-456` (`review/confirm`) and `:458-503` (`review/upload`)
- Test: `tests/webui/test_review_routes.py`

**Interfaces:**
- Consumes: `cleanup.prune_intermediates`, `NotExported`
- Produces: `_prune_after_review(capture_dir: Path, job_runner: JobRunner | None) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/webui/test_review_routes.py`:

These follow the module's existing pattern exactly: the shared `app` fixture from
`tests/webui/conftest.py`, the local `_make_capture(tmp_path)` helper, and the
`app.state.cfg.paths.captures_dir = tmp_path` redirect before `TestClient(app)`.

```python
def test_confirm_reclaims_intermediates(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    (capture_dir / "colmap").mkdir()
    (capture_dir / "rescue").mkdir()
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post("/captures/2026-07-19_lgs/review/confirm", follow_redirects=False)

    assert r.status_code == 303
    assert not (capture_dir / "colmap").exists()
    assert not (capture_dir / "rescue").exists()
    assert (capture_dir / "output" / ".review.json").exists()


def test_confirm_does_not_reclaim_while_job_runs(app: FastAPI, tmp_path: Path) -> None:
    # resume/add-video need colmap/ and frames/ — reclaiming underneath a live
    # job would make it unrecoverable.
    capture_dir = _make_capture(tmp_path)
    (capture_dir / "colmap").mkdir()
    app.state.cfg.paths.captures_dir = tmp_path

    class _LiveJob:
        status = "running"

    app.state.job_runner.get_job = lambda _id: _LiveJob()  # type: ignore[method-assign]

    with TestClient(app) as client:
        r = client.post("/captures/2026-07-19_lgs/review/confirm", follow_redirects=False)

    assert r.status_code == 303
    assert (capture_dir / "colmap").exists()  # deferred, not lost
    assert (capture_dir / "output" / ".review.json").exists()  # the sign-off still counts


def test_upload_reclaims_intermediates(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    (capture_dir / "colmap").mkdir()
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("clean.ply", b"ply\ncleaned", "application/octet-stream")},
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert not (capture_dir / "colmap").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd pipeline && uv run pytest tests/webui/test_review_routes.py -q -k reclaim`
Expected: FAIL — `colmap` still exists after confirm

- [ ] **Step 3: Add the helper to `routes/captures.py`**

Insert above `capture_review_confirm` (currently `:440`):

```python
def _prune_after_review(capture_dir: Path, job_runner: JobRunner | None) -> None:
    """Reclaim intermediates once a human has signed the capture off.

    Deferred while a job is live: `resume`/`add-video` need colmap/ and
    frames/, and reclaiming underneath them would make the run unrecoverable.
    A prune failure never invalidates the review — unreclaimed space is
    cosmetic, a discarded sign-off is lost manual work.
    """
    job = job_runner.get_job(capture_dir.name) if job_runner is not None else None
    if job is not None and job.status in ("running", "queued"):
        logger.info("review.prune_deferred", capture=capture_dir.name)
        return
    try:
        result = cleanup.prune_intermediates(capture_dir)
    except (cleanup.NotExported, OSError) as e:
        logger.error("review.prune_failed", capture=capture_dir.name, error=str(e))
        return
    logger.info(
        "review.pruned", capture=capture_dir.name, bytes_reclaimed=result.bytes_reclaimed
    )
```

Add the imports the module needs at its top:

```python
from autosplat import cleanup
from autosplat.logging import get_logger

logger = get_logger(__name__)
```

(If `logger` already exists in this module, do not define it twice.)

- [ ] **Step 4: Call it from both review routes**

In `capture_review_confirm`, after `_write_review_marker(capture.path)` (`:454`):

```python
    _prune_after_review(capture.path, _job_runner(request))
```

In `capture_review_upload`, after `_write_review_marker(capture.path)` (`:502`), add the identical line.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/webui -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/webui/routes/captures.py pipeline/tests/webui/test_review_routes.py
git commit -m "$(cat <<'EOF'
feat(webui): review sign-off reclaims a capture's intermediates

The publish quality gate is the human confirmation that the reconstruction
is good; from that point colmap/, rescue/ and friends are dead weight. The
prune is deferred while a job is live and never invalidates the review.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Stop writing `outputs/`

**Files:**
- Modify: `src/autosplat/export.py:109-114`
- Modify: `src/autosplat/config.py` (`ExportConfig.copy_to_outputs` description)
- Modify: `src/autosplat/doctor.py` (new warning check)
- Modify: `docs/CONFIGURATION.md`
- Test: `tests/test_export.py`, `tests/test_doctor.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: no API change — behaviour change only.

- [ ] **Step 1: Write the failing tests**

In `tests/test_export.py`, add:

```python
def test_export_does_not_write_outputs_dir_by_default(tmp_path: Path) -> None:
    # outputs/ held 8,8 GB of second copies, 10 of them orphaned.
    cfg = load_config(include_xdg=False)

    assert cfg.export.copy_to_outputs is False
```

In `tests/test_doctor.py`, add:

```python
def test_doctor_warns_when_copy_to_outputs_enabled() -> None:
    cfg = load_config(include_xdg=False)
    cfg.export.copy_to_outputs = True

    entry = next(r for r in run_doctor(cfg) if r.name == "outputs-copy")

    assert not entry.ok
    assert not entry.required  # a deprecation must never block a run
    assert "deprecated" in entry.detail.lower()


def test_doctor_passes_when_copy_to_outputs_disabled() -> None:
    cfg = load_config(include_xdg=False)

    entry = next(r for r in run_doctor(cfg) if r.name == "outputs-copy")

    assert entry.ok
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd pipeline && uv run pytest tests/test_export.py tests/test_doctor.py -q -k "outputs"`
Expected: FAIL

- [ ] **Step 3: Remove the copy in `export.py`**

Replace `export.py:109-114`:

```python
    if cfg.copy_to_outputs:
        outputs_dir = cfg.outputs_dir / capture_name
        outputs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_ply, outputs_dir / "scene.ply")
        shutil.copy2(metadata_path, outputs_dir / "metadata.json")
        logger.info("export.copied_to_outputs", dest=str(outputs_dir))
```

with:

```python
    # copy_to_outputs is deprecated: outputs_dir accumulated a second, unmanaged
    # copy of every PLY that nothing ever removed (8,8 GB, 10 of 17 folders
    # orphaned). captures/<id>/output/ is the only location now. The key is
    # still honoured so existing configs keep working, but doctor warns about it.
    if cfg.copy_to_outputs:
        outputs_dir = cfg.outputs_dir / capture_name
        outputs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_ply, outputs_dir / "scene.ply")
        shutil.copy2(metadata_path, outputs_dir / "metadata.json")
        logger.warning("export.copied_to_outputs_deprecated", dest=str(outputs_dir))
```

The default flipping to `false` (Task 1) is what stops the writes; the branch stays so nobody's explicit opt-in breaks silently.

- [ ] **Step 4: Update the config description**

In `config.py`, `ExportConfig.copy_to_outputs`:

```python
    copy_to_outputs: bool = Field(
        description=(
            "DEPRECATED. If true, also copies the final PLY to outputs_dir/<capture>/. "
            "Left an unmanaged second copy that nothing reclaimed; use "
            "captures/<id>/output/ instead."
        )
    )
```

- [ ] **Step 5: Add the doctor check**

Add this function next to `_check_compress_backends` (`doctor.py:174`), matching its shape:

```python
def _check_outputs_copy(config: Config) -> CheckResult:
    """Deprecation notice — outputs_dir was a second, unreclaimed copy of every PLY."""
    if not config.export.copy_to_outputs:
        return CheckResult(
            name="outputs-copy",
            ok=True,
            detail="disabled (captures/<id>/output/ is the only location)",
            required=False,
        )
    return CheckResult(
        name="outputs-copy",
        ok=False,
        detail=(
            "copy_to_outputs is deprecated — outputs_dir keeps a second, unmanaged copy "
            "of every PLY that nothing reclaims. Set it to false and run "
            "`autosplat migrate-storage` to reclaim the existing copies."
        ),
        required=False,
    )
```

Then append its result inside `run_doctor` (`doctor.py:104`), alongside the other
config-derived checks:

```python
    results.append(_check_outputs_copy(config))
```

Match the list-building style already used there — if `run_doctor` builds a literal list
rather than appending, add `_check_outputs_copy(config)` as an element instead.

- [ ] **Step 6: Document it**

In `docs/CONFIGURATION.md`, in the `[export]` table, mark `copy_to_outputs` as deprecated with a one-line rationale and a pointer to `migrate-storage`.

- [ ] **Step 7: Run the full suite**

Run: `cd pipeline && uv run pytest -q && uv run ruff check src/ tests/ && uv run mypy src/`
Expected: all green

- [ ] **Step 8: Commit**

```bash
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/export.py pipeline/src/autosplat/config.py pipeline/src/autosplat/doctor.py pipeline/docs/CONFIGURATION.md pipeline/tests/test_export.py pipeline/tests/test_doctor.py
git commit -m "$(cat <<'EOF'
feat(pipeline): deprecate copy_to_outputs, stop duplicating every PLY

outputs_dir accumulated a second copy of every finished capture that nothing
ever removed: 8,8 GB, 10 of 17 folders orphaned by deleted captures. The
default is now false and doctor warns when it is still enabled; the branch
remains so an explicit opt-in does not break silently.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: The SOG becomes a canonical, reused artifact

**Files:**
- Modify: `src/autosplat/webui/share_runner.py:70-90`
- Test: `tests/webui/test_share_runner.py`

**Interfaces:**
- Consumes: `lifecycle.resolve_publish_ply` (already imported via `state`)
- Produces: `output/scene.sog` as the canonical compressed artifact

- [ ] **Step 1: Write the failing tests**

Append to `tests/webui/test_share_runner.py`:

These reuse the module's existing helpers `_fake_embed(root)` and `_wait(job)` and its
established `fake_compress` shape. Add one shared factory at the top of the file, right
below `_wait`:

```python
def _counting_compress(calls: list[Path]):
    """fake_compress that records which PLY it was handed."""

    def fake_compress(ply: Path, out_dir: Path, *, fmt: str = "sog", quality: str = "medium"):
        calls.append(ply)
        out_dir.mkdir(parents=True, exist_ok=True)
        sog = out_dir / f"{ply.stem}.sog"
        sog.write_bytes(b"SOG" * 100)
        return CompressResult(
            output_path=sog,
            backend_used="fake",
            quality="medium",
            duration_s=0.1,
            input_bytes=15000,
            output_bytes=300,
        )

    return fake_compress


def _share_capture(tmp_path: Path) -> tuple[Path, Path]:
    embed = _fake_embed(tmp_path)
    capture_dir = tmp_path / "2026-07-10_lgs"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"PLY" * 5000)
    return capture_dir, embed


def _share_runner(embed: Path, compressor) -> ShareJobRunner:
    cfg = load_config(include_xdg=False)
    cfg.share.base_url = "https://splat.example"
    cfg.share.embed_src_path = embed
    return ShareJobRunner(cfg, compressor=compressor)
```

Then the new tests:

```python
def test_share_writes_sog_to_output_dir(tmp_path: Path) -> None:
    capture_dir, embed = _share_capture(tmp_path)
    runner = _share_runner(embed, _counting_compress([]))

    job = runner.start("2026-07-10_lgs", capture_dir)
    _wait(job)

    assert job.status == "done"
    assert (capture_dir / "output" / "scene.sog").exists()
    assert not (capture_dir / "share" / "_tmp").exists()


def test_second_share_reuses_existing_sog(tmp_path: Path) -> None:
    capture_dir, embed = _share_capture(tmp_path)
    calls: list[Path] = []
    runner = _share_runner(embed, _counting_compress(calls))

    _wait(runner.start("2026-07-10_lgs", capture_dir))
    _wait(runner.start("2026-07-10_lgs", capture_dir))

    assert len(calls) == 1  # the second share reused output/scene.sog


def test_rebuilt_ply_forces_recompression(tmp_path: Path) -> None:
    import os

    capture_dir, embed = _share_capture(tmp_path)
    calls: list[Path] = []
    runner = _share_runner(embed, _counting_compress(calls))

    _wait(runner.start("2026-07-10_lgs", capture_dir))

    # Simulate add-video: scene.ply becomes newer than the SOG.
    future = (capture_dir / "output" / "scene.sog").stat().st_mtime + 60
    os.utime(capture_dir / "output" / "scene.ply", (future, future))

    _wait(runner.start("2026-07-10_lgs", capture_dir))

    assert len(calls) == 2


def test_reviewed_ply_still_yields_canonical_scene_sog(tmp_path: Path) -> None:
    import json

    capture_dir, embed = _share_capture(tmp_path)
    scene_ply = capture_dir / "output" / "scene.ply"
    (capture_dir / "output" / "scene_reviewed.ply").write_bytes(b"PLY-CLEANED" * 5000)
    (capture_dir / "output" / ".review.json").write_text(
        json.dumps({"status": "reviewed", "source_ply_mtime": scene_ply.stat().st_mtime})
    )
    calls: list[Path] = []
    runner = _share_runner(embed, _counting_compress(calls))

    job = runner.start("2026-07-10_lgs", capture_dir)
    _wait(job)

    assert calls == [capture_dir / "output" / "scene_reviewed.ply"]
    assert (capture_dir / "output" / "scene.sog").exists()
    assert not (capture_dir / "output" / "scene_reviewed.sog").exists()
```

Note on `ShareJobRunner.start`: it takes `(capture_id, capture_dir)` and returns the job;
poll with `_wait(job)`, not `job._thread.join`.

**Watch for a knock-on change:** `test_share_job_compresses_reviewed_ply_when_present`
currently expects the bundle to carry the compressed reviewed PLY under its own stem. With
the canonical name, the bundle asset is `c/scene.sog` for every capture. Update that
assertion — the rename is the intended behaviour, not a regression.

- [ ] **Step 2: Run to verify they fail**

Run: `cd pipeline && uv run pytest tests/webui/test_share_runner.py -q -k "sog or reuse or recompression"`
Expected: FAIL — the SOG lands in `share/_tmp`, not `output/`

- [ ] **Step 3: Rewrite the compression block in `_run`**

Replace `share_runner.py:77-86`:

```python
            result = self._compress(
                ply,
                capture_dir / "share" / "_tmp",
                fmt="sog",
                quality=self._cfg.compress.quality,
            )
            token = make_share_token(job.capture_id)
            embed_src = self._resolve_embed_src()
            paths = assemble_bundle(result.output_path, embed_src, capture_dir / "share", token)
            shutil.rmtree(capture_dir / "share" / "_tmp", ignore_errors=True)

            job.token = token
            job.zip_path = paths.zip_path
            job.output_bytes = result.output_bytes
            job.input_bytes = result.input_bytes
```

with:

```python
            # The SOG is a durable artifact under output/, not bundle scratch:
            # it is kept per the retention policy and reused by later shares,
            # turning a repeat share from minutes of compression into seconds.
            sog = capture_dir / "output" / "scene.sog"
            if sog.exists() and sog.stat().st_mtime >= ply.stat().st_mtime:
                logger.info("share.sog_reused", capture_id=job.capture_id)
            else:
                result = self._compress(
                    ply,
                    capture_dir / "output",
                    fmt="sog",
                    quality=self._cfg.compress.quality,
                )
                # compress_ply names its output after the input stem, so a
                # reviewed capture would yield scene_reviewed.sog. The canonical
                # name is scene.sog regardless of which PLY was published.
                if result.output_path != sog:
                    result.output_path.replace(sog)

            token = make_share_token(job.capture_id)
            embed_src = self._resolve_embed_src()
            paths = assemble_bundle(sog, embed_src, capture_dir / "share", token)
            shutil.rmtree(capture_dir / "share" / "_tmp", ignore_errors=True)

            job.token = token
            job.zip_path = paths.zip_path
            job.output_bytes = sog.stat().st_size
            job.input_bytes = ply.stat().st_size
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/webui -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/webui/share_runner.py pipeline/tests/webui/test_share_runner.py
git commit -m "$(cat <<'EOF'
feat(webui): keep the compressed SOG in output/ and reuse it

The SOG was produced inside share/_tmp and thrown away, so every repeat share
paid the full compression cost again — and a failed run left the scratch dir
behind. It now lives at output/scene.sog, is reused while it is newer than the
publish PLY, and is recompressed automatically after a rebuild.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Grace sweep on startup

**Files:**
- Modify: `src/autosplat/webui/app.py:38-40` (`_lifespan`)
- Test: `tests/webui/test_app.py`

**Interfaces:**
- Consumes: `cleanup.sweep_expired`, `cfg.lifecycle.unreviewed_grace_days`
- Produces: no API — a background thread on startup

> ⚠️ **Do Step 0 first. It is not optional.**
> The shared `app` fixture in `tests/webui/conftest.py` builds the app from the **real**
> packaged config, so `cfg.paths.captures_dir` points at `~/AutoSplat/captures` — the
> maintainer's actual 19 GB. Several tests enter `TestClient(app)` without redirecting it
> first. The moment the lifespan hook starts reclaiming, running the test suite would
> reclaim **real captures** (every legacy one is unreviewed and far past 30 days).
> Redirect the fixture before the sweep exists, not after.

- [ ] **Step 0: Make the shared app fixture use a temp captures dir**

Replace the fixture in `tests/webui/conftest.py`:

```python
@pytest.fixture()
def app(tmp_path_factory: pytest.TempPathFactory) -> FastAPI:
    """FastAPI app built from the packaged default config.

    captures_dir is redirected to a temp dir: tests must never read — let alone
    reclaim — the real ~/AutoSplat/captures. Individual tests still override it
    with their own tmp_path where they need to place fixtures.
    """
    cfg = load_config(include_xdg=False)
    cfg.paths.captures_dir = tmp_path_factory.mktemp("captures")
    return create_app(cfg)
```

Run `cd pipeline && uv run pytest tests/webui -q` — everything must still pass before you
continue. If a test depended on the real captures dir, that is a bug in the test; fix it by
giving it its own tmp_path.

- [ ] **Step 1: Write the failing test**

Append to `tests/webui/test_app.py`:

```python
def test_lifespan_starts_grace_sweep(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from autosplat.config import load_config
    from autosplat.webui import app as app_mod

    called: list[int] = []

    def fake_sweep(captures_dir, *, grace_days, now):
        called.append(grace_days)
        return []

    monkeypatch.setattr(app_mod.cleanup, "sweep_expired", fake_sweep)

    cfg = load_config(include_xdg=False)
    cfg.paths.captures_dir = tmp_path
    app = app_mod.create_app(cfg)

    with TestClient(app):
        pass

    assert called == [cfg.lifecycle.unreviewed_grace_days]


def test_lifespan_skips_sweep_when_grace_disabled(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from autosplat.config import load_config
    from autosplat.webui import app as app_mod

    called: list[int] = []
    monkeypatch.setattr(
        app_mod.cleanup,
        "sweep_expired",
        lambda captures_dir, *, grace_days, now: called.append(grace_days) or [],
    )

    cfg = load_config(include_xdg=False)
    cfg.paths.captures_dir = tmp_path
    cfg.lifecycle.unreviewed_grace_days = 0
    app = app_mod.create_app(cfg)

    with TestClient(app):
        pass

    assert called == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd pipeline && uv run pytest tests/webui/test_app.py -q -k sweep`
Expected: FAIL — `AttributeError: module 'autosplat.webui.app' has no attribute 'cleanup'`

- [ ] **Step 3: Wire the sweep into `_lifespan`**

Add to the imports of `app.py`:

```python
import threading
from datetime import UTC, datetime

from autosplat import cleanup
from autosplat.logging import get_logger

logger = get_logger(__name__)
```

Replace `_lifespan` (`:38-40`):

```python
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the unreviewed-grace sweep in the background on startup.

    A background thread on purpose: reclaiming must never delay or prevent the
    UI from coming up, and a failure inside the sweep must not surface as a
    failed start.
    """
    cfg: Config | None = app.state.cfg
    if cfg is not None and cfg.lifecycle.unreviewed_grace_days > 0:
        captures_dir = cfg.paths.captures_dir
        grace_days = cfg.lifecycle.unreviewed_grace_days

        def _sweep() -> None:
            try:
                results = cleanup.sweep_expired(
                    captures_dir, grace_days=grace_days, now=datetime.now(UTC)
                )
            except Exception as e:  # noqa: BLE001 — startup must never fail here
                logger.error("lifecycle.sweep_failed", error=str(e))
                return
            if results:
                total = sum(r.bytes_reclaimed for r in results)
                logger.info("lifecycle.sweep_done", captures=len(results), bytes_reclaimed=total)

        threading.Thread(target=_sweep, name="autosplat-grace-sweep", daemon=True).start()
    yield
```

Note: the sweep must be called through the module (`cleanup.sweep_expired`), not imported by name, so the test's monkeypatch takes effect.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/webui -q && uv run mypy src/`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/webui/app.py pipeline/tests/webui/test_app.py
git commit -m "$(cat <<'EOF'
feat(webui): reclaim captures past their unreviewed grace period on startup

A capture that is never reviewed would otherwise keep its intermediates
forever. The sweep runs in a background thread so it can neither delay nor
break startup, and logs one line per reclaimed capture.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: `autosplat migrate-storage`

**Files:**
- Modify: `src/autosplat/cli.py` (new command after `cleanup_intermediates`, currently ending `:534`)
- Test: `tests/test_cli_migrate_storage.py` (new)

**Interfaces:**
- Consumes: `lifecycle.find_capture_dirs`, `lifecycle.reclaimable_targets`, `lifecycle.bytes_in`, `lifecycle.find_ply`, `cleanup.prune_intermediates`
- Produces: CLI command `migrate-storage [--apply] [--config PATH]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_migrate_storage.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from autosplat.cli import app

runner = CliRunner()


def _total_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def _legacy_tree(root: Path) -> Path:
    """Mirrors the real backlog: a nested pre-Phase-9 capture with a PLY."""
    captures = root / "captures"
    inner = captures / "2026-05-25_max_strasse_rescue" / "2026-05-25_A_vor1"
    (inner / "output").mkdir(parents=True)
    (inner / "output" / "scene.ply").write_bytes(b"ply\nend_header\n")
    for sub in ("frames", "colmap", "training"):
        (inner / sub).mkdir()
        (inner / sub / "blob").write_bytes(b"x" * 100)
    return captures


def _config_for(captures: Path, tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[paths]\ncaptures_dir = "{captures}"\n\n[export]\noutputs_dir = "{tmp_path / "outputs"}"\n',
        encoding="utf-8",
    )
    return cfg


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    captures = _legacy_tree(tmp_path)
    cfg = _config_for(captures, tmp_path)
    before = _total_bytes(captures)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])

    assert result.exit_code == 0
    assert _total_bytes(captures) == before
    assert "2026-05-25_A_vor1" in result.stdout


def test_apply_reclaims_nested_legacy_capture(tmp_path: Path) -> None:
    captures = _legacy_tree(tmp_path)
    cfg = _config_for(captures, tmp_path)
    inner = captures / "2026-05-25_max_strasse_rescue" / "2026-05-25_A_vor1"

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert result.exit_code == 0
    assert not (inner / "colmap").exists()
    assert not (inner / "training").exists()
    assert (inner / "output" / "scene.ply").exists()


def test_never_touches_a_directory_holding_the_only_ply(tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    # Constructed hazard: the PLY lives INSIDE what looks like an intermediate.
    weird = captures / "2026-07-01_x" / "rescue"
    weird.mkdir(parents=True)
    (weird / "scene.ply").write_bytes(b"ply\nend_header\n")
    cfg = _config_for(captures, tmp_path)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert result.exit_code == 0
    assert (weird / "scene.ply").exists()


def test_reports_orphaned_outputs_dirs(tmp_path: Path) -> None:
    captures = _legacy_tree(tmp_path)
    outputs = tmp_path / "outputs"
    (outputs / "2026-05-14_jay_1").mkdir(parents=True)
    (outputs / "2026-05-14_jay_1" / "scene.ply").write_bytes(b"x" * 500)
    cfg = _config_for(captures, tmp_path)

    result = runner.invoke(app, ["migrate-storage", "--config", str(cfg)])

    assert "2026-05-14_jay_1" in result.stdout
    assert (outputs / "2026-05-14_jay_1").exists()  # dry run

    applied = runner.invoke(app, ["migrate-storage", "--config", str(cfg), "--apply"])

    assert applied.exit_code == 0
    assert not (outputs / "2026-05-14_jay_1").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd pipeline && uv run pytest tests/test_cli_migrate_storage.py -q`
Expected: FAIL — `No such command 'migrate-storage'`

- [ ] **Step 3: Implement the command in `cli.py`**

Add after the `cleanup_intermediates` command:

```python
@app.command("migrate-storage")
def migrate_storage(
    config: Path | None = typer.Option(None, "--config", "-c"),
    apply: bool = typer.Option(
        False, "--apply", help="Actually reclaim. Without this flag, only a preview is printed."
    ),
) -> None:
    """Bring an existing captures/ + outputs/ tree onto the lifecycle retention policy.

    Relaxed rule for the backlog: a finished PLY is enough — review status is
    not required, otherwise no legacy capture would ever qualify.
    """
    from autosplat import cleanup as cleanup_mod
    from autosplat import lifecycle

    cfg = load_config(config)
    captures_dir = cfg.paths.captures_dir
    outputs_dir = cfg.export.outputs_dir

    table = Table(title="migrate-storage" + ("" if apply else " — preview (nothing is deleted)"))
    table.add_column("Path")
    table.add_column("What")
    table.add_column("Size", justify="right")

    total = 0
    planned: list[tuple[Path, list[Path]]] = []

    for capture_dir in lifecycle.find_capture_dirs(captures_dir):
        ply = lifecycle.find_ply(capture_dir)
        if ply is None:
            continue  # failed capture — keeps everything for diagnosis
        targets = [
            t for t in lifecycle.reclaimable_targets(capture_dir) if not _holds_ply(t, ply)
        ]
        if not targets:
            continue
        size = lifecycle.bytes_in(targets)
        total += size
        planned.append((capture_dir, targets))
        table.add_row(
            str(capture_dir.relative_to(captures_dir)),
            ", ".join(t.name for t in targets),
            _human_bytes(size),
        )

    orphans: list[Path] = []
    if outputs_dir.is_dir():
        capture_names = {c.name for c in lifecycle.find_capture_dirs(captures_dir)}
        for entry in sorted(outputs_dir.iterdir()):
            if not entry.is_dir():
                continue
            size = lifecycle.bytes_in([entry])
            total += size
            orphans.append(entry)
            note = "duplicate" if entry.name in capture_names else "orphaned"
            table.add_row(f"outputs/{entry.name}", note, _human_bytes(size))

    console.print(table)
    console.print(f"[bold]Reclaimable: {_human_bytes(total)}[/bold]")

    if not apply:
        console.print("Run again with [bold]--apply[/bold] to reclaim.")
        return

    reclaimed = 0
    failures = 0
    for capture_dir, _targets in planned:
        try:
            result = cleanup_mod.prune_intermediates(capture_dir)
        except Exception as e:  # noqa: BLE001 — one failure must not stop the sweep
            console.print(f"[red]failed:[/red] {capture_dir} — {e}")
            failures += 1
            continue
        reclaimed += result.bytes_reclaimed
    for entry in orphans:
        try:
            size = lifecycle.bytes_in([entry])
            shutil.rmtree(entry)
        except OSError as e:
            console.print(f"[red]failed:[/red] {entry} — {e}")
            failures += 1
            continue
        reclaimed += size

    console.print(f"[green]Reclaimed {_human_bytes(reclaimed)}[/green], {failures} failure(s).")


def _holds_ply(target: Path, ply: Path) -> bool:
    """True if `target` contains the capture's only PLY — never reclaim those."""
    return ply == target or target in ply.parents


def _human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
```

Ensure `shutil` and `Table` are imported at the top of `cli.py` — check with
`grep -n "^import shutil\|from rich.table import Table" src/autosplat/cli.py` and add
whichever is missing. `console` already exists in that module.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/test_cli_migrate_storage.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the whole suite and the linters**

Run: `cd pipeline && uv run pytest -q && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/`
Expected: all green, 506+ tests

- [ ] **Step 6: Document the command**

Add `migrate-storage` to `README.md` (CLI section) and to `docs/CAPTURE-GUIDE.md` next to
`cleanup-intermediates`, with one sentence each: preview by default, `--apply` to reclaim,
and that failed captures are deliberately left alone.

- [ ] **Step 7: Commit**

```bash
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/cli.py pipeline/tests/test_cli_migrate_storage.py pipeline/README.md pipeline/docs/CAPTURE-GUIDE.md
git commit -m "$(cat <<'EOF'
feat(pipeline): add migrate-storage to reclaim the existing backlog

Recursively finds captures — including nested pre-Phase-9 layouts — and
previews what is reclaimable without touching anything. --apply then reclaims
intermediates and the deprecated outputs/ copies, isolating failures per
capture. A directory holding a capture's only PLY is never touched, and
failed captures keep everything for diagnosis.

Expected on the maintainer's machine: ~9,6 GB in captures/ plus 8,8 GB in
outputs/.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verification (after all tasks)

- [ ] `cd pipeline && uv run pytest -q` — all green
- [ ] `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/`
- [ ] **Real-world dry run**, the point of the whole exercise:
  ```bash
  cd pipeline && uv run autosplat migrate-storage
  ```
  Expect roughly 9,6 GB under `captures/` plus 8,8 GB under `outputs/`. Confirm by eye
  that `2026-05-22_max_strasse` and `2026-05-24_360max` are **absent** from the table —
  they have no PLY and must keep everything.
- [ ] Only then `uv run autosplat migrate-storage --apply`, and re-measure:
  ```bash
  du -sh ~/AutoSplat/captures ~/AutoSplat/outputs
  ```
- [ ] Version bump + CHANGELOG entry (root and `pipeline/`), then the release cut per the
  standing DMG invariant: signed + notarised `.app`/DMG uploaded as a Codeberg release
  asset. The shipped DMG must never lag behind the release tag.
