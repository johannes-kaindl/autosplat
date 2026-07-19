# Publish Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Force a one-time SuperSplat review checkpoint before a capture's first share, with automatic invalidation when the capture is rebuilt.

**Architecture:** `state.py` (the read-only filesystem→WebUI bridge) computes a `review_status` per capture from a small JSON marker file compared against `output/scene.ply`'s mtime — no new persistent store. Two new routes write that marker (upload a cleaned PLY, or confirm unchanged); the existing share route and `ShareJobRunner` both resolve which PLY to publish through one shared helper.

**Tech Stack:** FastAPI (routes, `UploadFile`), Jinja2 templates, pytest + Starlette `TestClient`, no new dependencies (`python-multipart` already present).

## Global Constraints

- Marker file: `output/.review.json`, schema `{"status": "reviewed", "reviewed_at": <iso8601 str>, "source_ply_mtime": <float>}`.
- Reviewed PLY, when uploaded, is saved to `output/scene_reviewed.ply`.
- Invalidation is purely mtime-based: `source_ply_mtime` (recorded at review time) must exactly match `output/scene.ply`'s current mtime, or the capture is `"unreviewed"`.
- `state.py` stays read-only/computed — no new field is written there; only read helpers live in it. Writing the marker happens in `routes/captures.py`.
- `CaptureInfo.review_status` defaults to `"unreviewed"` (a defaulted dataclass field, like the existing `detail` field) so the one other direct-construction call site in `tests/webui/test_captures.py` keeps working unchanged.
- No new CSS classes — reuse `.as-viewer-pill`, `.as-btn` (`sm`/`ghost`/`primary`), and the design-token custom properties already used throughout `view.html`/`detail.html`.

---

### Task 1: `review_status` computation in `state.py`

**Files:**
- Modify: `pipeline/src/autosplat/webui/state.py`
- Test: `pipeline/tests/webui/test_captures.py`

**Interfaces:**
- Produces: `state.ReviewStatus = Literal["unreviewed", "reviewed"]`; `state.review_marker_path(capture_dir: Path) -> Path`; `state._review_status(capture_dir: Path) -> ReviewStatus`; `state.resolve_publish_ply(capture_dir: Path, status: ReviewStatus) -> Path | None`; `CaptureInfo.review_status: ReviewStatus` (default `"unreviewed"`).

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/webui/test_captures.py` (near the other `list_captures`/fixture tests, e.g. right after `test_list_captures_propagates_in_progress_detail`):

```python
def test_review_status_unreviewed_without_marker(tmp_path: Path) -> None:
    from autosplat.webui.state import _review_status

    capture_dir = tmp_path / "2026-07-19_test"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n")

    assert _review_status(capture_dir) == "unreviewed"


def test_review_status_reviewed_with_matching_marker(tmp_path: Path) -> None:
    import json

    from autosplat.webui.state import _review_status

    capture_dir = tmp_path / "2026-07-19_test"
    output_dir = capture_dir / "output"
    output_dir.mkdir(parents=True)
    scene_ply = output_dir / "scene.ply"
    scene_ply.write_bytes(b"ply\n")
    marker = output_dir / ".review.json"
    marker.write_text(
        json.dumps(
            {
                "status": "reviewed",
                "reviewed_at": "2026-07-19T00:00:00",
                "source_ply_mtime": scene_ply.stat().st_mtime,
            }
        )
    )

    assert _review_status(capture_dir) == "reviewed"


def test_review_status_unreviewed_after_ply_rebuilt(tmp_path: Path) -> None:
    import json
    import time

    from autosplat.webui.state import _review_status

    capture_dir = tmp_path / "2026-07-19_test"
    output_dir = capture_dir / "output"
    output_dir.mkdir(parents=True)
    scene_ply = output_dir / "scene.ply"
    scene_ply.write_bytes(b"ply\n")
    marker = output_dir / ".review.json"
    marker.write_text(
        json.dumps(
            {
                "status": "reviewed",
                "reviewed_at": "2026-07-19T00:00:00",
                "source_ply_mtime": scene_ply.stat().st_mtime,
            }
        )
    )

    time.sleep(0.01)
    scene_ply.write_bytes(b"ply\nrebuilt")

    assert _review_status(capture_dir) == "unreviewed"


def test_review_status_unreviewed_when_marker_corrupt(tmp_path: Path) -> None:
    from autosplat.webui.state import _review_status

    capture_dir = tmp_path / "2026-07-19_test"
    output_dir = capture_dir / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "scene.ply").write_bytes(b"ply\n")
    (output_dir / ".review.json").write_text("not json")

    assert _review_status(capture_dir) == "unreviewed"


def test_resolve_publish_ply_prefers_reviewed_file(tmp_path: Path) -> None:
    from autosplat.webui.state import resolve_publish_ply

    capture_dir = tmp_path / "2026-07-19_test"
    output_dir = capture_dir / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "scene.ply").write_bytes(b"ply\noriginal")
    reviewed = output_dir / "scene_reviewed.ply"
    reviewed.write_bytes(b"ply\ncleaned")

    assert resolve_publish_ply(capture_dir, "reviewed") == reviewed


def test_resolve_publish_ply_falls_back_when_unreviewed(tmp_path: Path) -> None:
    from autosplat.webui.state import resolve_publish_ply

    capture_dir = tmp_path / "2026-07-19_test"
    output_dir = capture_dir / "output"
    output_dir.mkdir(parents=True)
    scene_ply = output_dir / "scene.ply"
    scene_ply.write_bytes(b"ply\noriginal")
    (output_dir / "scene_reviewed.ply").write_bytes(b"ply\ncleaned")

    assert resolve_publish_ply(capture_dir, "unreviewed") == scene_ply


def test_resolve_publish_ply_falls_back_when_reviewed_file_missing(tmp_path: Path) -> None:
    from autosplat.webui.state import resolve_publish_ply

    capture_dir = tmp_path / "2026-07-19_test"
    output_dir = capture_dir / "output"
    output_dir.mkdir(parents=True)
    scene_ply = output_dir / "scene.ply"
    scene_ply.write_bytes(b"ply\noriginal")

    assert resolve_publish_ply(capture_dir, "reviewed") == scene_ply


def test_list_captures_surfaces_review_status(tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-07-19_test"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n")

    captures = list_captures(tmp_path)
    assert captures[0].review_status == "unreviewed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && uv run pytest tests/webui/test_captures.py -k review_status -v` and `uv run pytest tests/webui/test_captures.py -k resolve_publish_ply -v` and `uv run pytest tests/webui/test_captures.py::test_list_captures_surfaces_review_status -v`
Expected: FAIL — `ImportError: cannot import name '_review_status'` (and similarly for `resolve_publish_ply`, and an `AttributeError` for `.review_status` on the last one).

- [ ] **Step 3: Implement in `state.py`**

Add `json` to the import block (`pipeline/src/autosplat/webui/state.py:7-9`):

```python
import contextlib
import json
import re
import time
```

Add a `ReviewStatus` type alias next to `CaptureStatus` (`state.py:19`):

```python
CaptureStatus = Literal["idle", "queued", "running", "done", "failed"]
ReviewStatus = Literal["unreviewed", "reviewed"]
```

Add `review_status` as the new last field of `CaptureInfo` (`state.py:27-41`), right after `detail`:

```python
@dataclass
class CaptureInfo:
    id: str
    path: Path
    status: CaptureStatus
    stage: str | None
    has_ply: bool
    ply_path: Path | None
    ply_size_bytes: int | None
    has_log: bool
    started_at: str | None
    finished_at: str | None
    duration_s: float | None
    reason: str | None
    detail: str | None = None  # v1.4.1: stage-specific sub-info (e.g. bisect clip)
    review_status: ReviewStatus = "unreviewed"  # v1.15.0: publish quality gate
```

Add the marker path helper, status computation, and PLY resolver right after `_find_ply` (`state.py:44-52`):

```python
def _find_ply(capture_dir: Path) -> Path | None:
    for candidate in [
        capture_dir / "output" / "scene.ply",
        capture_dir / "scene.ply",
    ]:
        if candidate.exists():
            return candidate
    plys = sorted(capture_dir.glob("*.ply"))
    return plys[0] if plys else None


def review_marker_path(capture_dir: Path) -> Path:
    """Where the publish-quality-gate review marker lives for a capture."""
    return capture_dir / "output" / ".review.json"


def _review_status(capture_dir: Path) -> ReviewStatus:
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
    recorded_mtime = data.get("source_ply_mtime")
    scene_ply = capture_dir / "output" / "scene.ply"
    try:
        current_mtime = scene_ply.stat().st_mtime
    except OSError:
        return "unreviewed"
    if recorded_mtime != current_mtime:
        return "unreviewed"
    return "reviewed"


def resolve_publish_ply(capture_dir: Path, status: ReviewStatus) -> Path | None:
    """Which PLY represents this capture for viewing/sharing.

    Prefers the manually-cleaned output/scene_reviewed.ply once the capture
    is reviewed and that file exists; otherwise falls back to the normal
    _find_ply chain. A stale scene_reviewed.ply left over from before a
    rebuild is automatically skipped once `status` recomputes to unreviewed.
    """
    if status == "reviewed":
        reviewed_ply = capture_dir / "output" / "scene_reviewed.ply"
        if reviewed_ply.exists():
            return reviewed_ply
    return _find_ply(capture_dir)
```

Wire it into `list_captures` — replace the single line `ply = _find_ply(entry)` (`state.py:90`) with:

```python
review_status = _review_status(entry)
ply = resolve_publish_ply(entry, review_status)
```

And add `review_status=review_status` to the `CaptureInfo(...)` construction (`state.py:195-211`), as the new last argument:

```python
        captures.append(
            CaptureInfo(
                id=entry.name,
                path=entry,
                status=status,
                stage=stage,
                has_ply=ply is not None,
                ply_path=ply,
                ply_size_bytes=ply.stat().st_size if ply is not None else None,
                has_log=log_path.exists(),
                started_at=started_at,
                finished_at=finished_at,
                duration_s=duration_s,
                reason=reason,
                detail=detail,
                review_status=review_status,
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/webui/test_captures.py -v`
Expected: PASS (all tests in the file, including the new ones — this also confirms the existing `_capture_info()` helper at `test_captures.py:568-584` still works since `review_status` has a default).

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/autosplat/webui/state.py pipeline/tests/webui/test_captures.py
git commit -m "feat(webui): compute review_status + resolve_publish_ply in state.py"
```

---

### Task 2: `ShareJobRunner` publishes the reviewed PLY when present

**Files:**
- Modify: `pipeline/src/autosplat/webui/share_runner.py`
- Test: `pipeline/tests/webui/test_share_runner.py`

**Interfaces:**
- Consumes: `state._review_status(capture_dir) -> ReviewStatus`, `state.resolve_publish_ply(capture_dir, status) -> Path | None` (Task 1).
- Produces: no new public interface — `ShareJobRunner._run` now compresses whichever PLY `resolve_publish_ply` returns.

- [ ] **Step 1: Write the failing test**

Append to `pipeline/tests/webui/test_share_runner.py`:

```python
def test_share_job_compresses_reviewed_ply_when_present(tmp_path: Path) -> None:
    import json

    embed = _fake_embed(tmp_path)
    capture_dir = tmp_path / "2026-07-10_lgs"
    output_dir = capture_dir / "output"
    output_dir.mkdir(parents=True)
    scene_ply = output_dir / "scene.ply"
    scene_ply.write_bytes(b"PLY" * 5000)
    reviewed_ply = output_dir / "scene_reviewed.ply"
    reviewed_ply.write_bytes(b"PLY-CLEANED" * 5000)
    (output_dir / ".review.json").write_text(
        json.dumps(
            {
                "status": "reviewed",
                "reviewed_at": "2026-07-19T00:00:00",
                "source_ply_mtime": scene_ply.stat().st_mtime,
            }
        )
    )

    compressed_paths = []

    def fake_compress(ply: Path, out_dir: Path, *, fmt: str = "sog", quality: str = "medium"):
        compressed_paths.append(ply)
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

    cfg = load_config(include_xdg=False)
    cfg.share.embed_src_path = embed
    runner = ShareJobRunner(cfg, compressor=fake_compress)

    job = runner.start("2026-07-10_lgs", capture_dir)
    _wait(job)

    assert job.status == "done"
    assert compressed_paths == [reviewed_ply]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/webui/test_share_runner.py::test_share_job_compresses_reviewed_ply_when_present -v`
Expected: FAIL — `compressed_paths == [scene_ply]`, not `[reviewed_ply]` (the runner still hardcodes `output/scene.ply`).

- [ ] **Step 3: Implement in `share_runner.py`**

Add the import (`pipeline/src/autosplat/webui/share_runner.py:22`, right after the existing `from autosplat.webui.share import ...` line):

```python
from autosplat.webui.share import assemble_bundle, make_share_token, share_link
from autosplat.webui.state import _review_status, resolve_publish_ply
```

Replace the PLY resolution at the top of `_run` (`share_runner.py:69-73`):

```python
    def _run(self, job: ShareJob, capture_dir: Path) -> None:
        try:
            ply = capture_dir / "output" / "scene.ply"
            if not ply.exists():
                raise FileNotFoundError(f"No output/scene.ply in {capture_dir}")
```

with:

```python
    def _run(self, job: ShareJob, capture_dir: Path) -> None:
        try:
            review_status = _review_status(capture_dir)
            ply = resolve_publish_ply(capture_dir, review_status)
            if ply is None or not ply.exists():
                raise FileNotFoundError(f"No output/scene.ply in {capture_dir}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/webui/test_share_runner.py -v`
Expected: PASS (all tests, including the three pre-existing ones — their fixtures have no `.review.json`, so `_review_status` returns `"unreviewed"` and `resolve_publish_ply` falls back to `output/scene.ply`, identical to the old hardcoded behavior).

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/autosplat/webui/share_runner.py pipeline/tests/webui/test_share_runner.py
git commit -m "feat(webui): ShareJobRunner publishes scene_reviewed.ply when reviewed"
```

---

### Task 3: `POST /review/confirm` route

**Files:**
- Modify: `pipeline/src/autosplat/webui/routes/captures.py`
- Create: `pipeline/tests/webui/test_review_routes.py`

**Interfaces:**
- Consumes: `state.review_marker_path(capture_dir) -> Path` (Task 1), `get_capture`, `_captures_dir`, `_job_runner` (existing module helpers).
- Produces: `_write_review_marker(capture_dir: Path) -> None` (module-private helper in `routes/captures.py`, reused by Task 4); route `POST /captures/{capture_id}/review/confirm`.

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/webui/test_review_routes.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient


def _make_capture(tmp_path: Path, capture_id: str = "2026-07-19_lgs") -> Path:
    capture_dir = tmp_path / capture_id
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 1000)
    (capture_dir / "pipeline.log").write_text("done\n")
    return capture_dir


def test_confirm_writes_review_marker(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/confirm", follow_redirects=False
        )

    assert r.status_code == 303
    assert r.headers["location"] == "/captures/2026-07-19_lgs"
    marker = capture_dir / "output" / ".review.json"
    assert marker.exists()
    data = json.loads(marker.read_text())
    assert data["status"] == "reviewed"
    assert data["source_ply_mtime"] == (capture_dir / "output" / "scene.ply").stat().st_mtime
    assert not (capture_dir / "output" / "scene_reviewed.ply").exists()


def test_confirm_unknown_capture_404s(app: FastAPI, tmp_path: Path) -> None:
    app.state.cfg.paths.captures_dir = tmp_path
    with TestClient(app) as client:
        r = client.post("/captures/does-not-exist/review/confirm")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && uv run pytest tests/webui/test_review_routes.py -v`
Expected: FAIL — `404 Not Found` for the confirm route (doesn't exist yet), so both the success and the "unknown capture" assertions fail (the first with a wrong status code, since the route itself 404s).

- [ ] **Step 3: Implement in `routes/captures.py`**

Add imports (`routes/captures.py:1-22`) — extend the existing `datetime`-free imports and the `state` import:

```python
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from autosplat import __version__
from autosplat import cleanup as cleanup_mod
from autosplat.config import apply_override
from autosplat.failure import classify_failure, failure_reason_from_log
from autosplat.webui.jobs_runner import JobRunner
from autosplat.webui.state import (
    get_capture,
    last_activity_age_s,
    list_captures,
    read_log_tail,
    review_marker_path,
    sort_captures,
)
```

Add the marker-writing helper and the confirm route right after `capture_prune` (`routes/captures.py:405-417`, before `@router.post("/{capture_id}/share")`):

```python
def _write_review_marker(capture_dir: Path) -> None:
    """Mark capture_dir as reviewed against output/scene.ply's current mtime."""
    scene_ply = capture_dir / "output" / "scene.ply"
    marker = review_marker_path(capture_dir)
    marker.write_text(
        json.dumps(
            {
                "status": "reviewed",
                "reviewed_at": datetime.now(UTC).isoformat(),
                "source_ply_mtime": scene_ply.stat().st_mtime,
            }
        ),
        encoding="utf-8",
    )


@router.post("/{capture_id}/review/confirm")
async def capture_review_confirm(request: Request, capture_id: str) -> RedirectResponse:
    """Mark a capture as reviewed without changing its PLY (publish quality gate)."""
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    if not capture.has_ply:
        raise HTTPException(status_code=409, detail="Capture has no output/scene.ply yet")
    _write_review_marker(capture.path)
    return RedirectResponse(url=f"/captures/{capture_id}", status_code=303)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/webui/test_review_routes.py -v`
Expected: PASS

Then run the full webui suite to check nothing else broke: `cd pipeline && uv run pytest tests/webui/ -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/autosplat/webui/routes/captures.py pipeline/tests/webui/test_review_routes.py
git commit -m "feat(webui): POST /captures/{id}/review/confirm marks capture reviewed"
```

---

### Task 4: `POST /review/upload` route

**Files:**
- Modify: `pipeline/src/autosplat/webui/routes/captures.py`
- Modify: `pipeline/tests/webui/test_review_routes.py`

**Interfaces:**
- Consumes: `_write_review_marker(capture_dir)` (Task 3).
- Produces: `_supersplat_embed_context(request, capture) -> tuple[bool, str]` (DRY helper, replaces inline logic in `capture_view`); route `POST /captures/{capture_id}/review/upload`.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/webui/test_review_routes.py`:

```python
def test_upload_valid_ply_saves_reviewed_file_and_marker(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.ply", b"ply\ncleaned-data", "application/octet-stream")},
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert r.headers["location"] == "/captures/2026-07-19_lgs"
    reviewed = capture_dir / "output" / "scene_reviewed.ply"
    assert reviewed.exists()
    assert reviewed.read_bytes() == b"ply\ncleaned-data"
    marker = capture_dir / "output" / ".review.json"
    assert json.loads(marker.read_text())["status"] == "reviewed"


def test_upload_rejects_non_ply_extension(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.txt", b"ply\ndata", "text/plain")},
        )

    assert r.status_code == 400
    assert "Unsupported file type" in r.text


def test_upload_rejects_missing_ply_header(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.ply", b"not a ply file", "application/octet-stream")},
        )

    assert r.status_code == 400
    assert "PLY" in r.text


def test_upload_rejects_empty_file(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.ply", b"", "application/octet-stream")},
        )

    assert r.status_code == 400
    assert "empty" in r.text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && uv run pytest tests/webui/test_review_routes.py -k upload -v`
Expected: FAIL — `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Implement in `routes/captures.py`**

Add `File` and `UploadFile` to the `fastapi` import (`routes/captures.py`, the `from fastapi import ...` line):

```python
from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
```

Extract the embed-context computation out of `capture_view` into a shared helper, and reuse it. Replace the body of `capture_view` (`routes/captures.py:245-271`):

```python
@router.get("/{capture_id}/view", response_class=HTMLResponse)
async def capture_view(request: Request, capture_id: str) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")

    # Check if SuperSplat is mounted (app.mount sets it in app.routes)
    supersplat_available = any(getattr(r, "name", None) == "supersplat" for r in request.app.routes)

    # Build the iframe embed URL — SuperSplat loads the PLY via ?load=
    embed_url = ""
    if supersplat_available and capture.has_ply:
        # Absolute URL so the iframe can resolve the PLY route correctly
        base = str(request.base_url).rstrip("/")
        embed_url = f"{base}/supersplat/index.html?load={base}/captures/{capture_id}/scene.ply"

    return _templates(request).TemplateResponse(
        request,
        "capture/view.html",
        {
            "version": __version__,
            "capture": capture,
            "supersplat_available": supersplat_available,
            "embed_url": embed_url,
        },
    )
```

with:

```python
def _supersplat_embed_context(request: Request, capture_id: str, has_ply: bool) -> tuple[bool, str]:
    """(supersplat_available, embed_url) for the SuperSplat iframe on a capture."""
    supersplat_available = any(getattr(r, "name", None) == "supersplat" for r in request.app.routes)
    embed_url = ""
    if supersplat_available and has_ply:
        base = str(request.base_url).rstrip("/")
        embed_url = f"{base}/supersplat/index.html?load={base}/captures/{capture_id}/scene.ply"
    return supersplat_available, embed_url


@router.get("/{capture_id}/view", response_class=HTMLResponse)
async def capture_view(request: Request, capture_id: str) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")

    supersplat_available, embed_url = _supersplat_embed_context(request, capture_id, capture.has_ply)

    return _templates(request).TemplateResponse(
        request,
        "capture/view.html",
        {
            "version": __version__,
            "capture": capture,
            "supersplat_available": supersplat_available,
            "embed_url": embed_url,
        },
    )
```

Add the upload route right after `capture_review_confirm` (Task 3):

```python
@router.post("/{capture_id}/review/upload")
async def capture_review_upload(
    request: Request,
    capture_id: str,
    reviewed_ply: UploadFile = File(...),
) -> Response:
    """Accept a cleaned PLY exported from SuperSplat (publish quality gate)."""
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    if not capture.has_ply:
        raise HTTPException(status_code=409, detail="Capture has no output/scene.ply yet")

    filename = reviewed_ply.filename or ""
    content = await reviewed_ply.read()

    error: str | None = None
    if not filename.lower().endswith(".ply"):
        error = f"Unsupported file type — expected a .ply file, got '{filename}'."
    elif not content:
        error = "Uploaded file is empty."
    elif not content.startswith(b"ply\n"):
        error = "File does not look like a valid PLY (missing 'ply' header)."

    if error is not None:
        supersplat_available, embed_url = _supersplat_embed_context(
            request, capture_id, capture.has_ply
        )
        return _templates(request).TemplateResponse(
            request,
            "capture/view.html",
            {
                "version": __version__,
                "capture": capture,
                "supersplat_available": supersplat_available,
                "embed_url": embed_url,
                "review_error": error,
            },
            status_code=400,
        )

    (capture.path / "output" / "scene_reviewed.ply").write_bytes(content)
    _write_review_marker(capture.path)
    return RedirectResponse(url=f"/captures/{capture_id}", status_code=303)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/webui/test_review_routes.py -v`
Expected: PASS

Then: `cd pipeline && uv run pytest tests/webui/ -v`
Expected: PASS (all — confirms the `capture_view` refactor didn't change its observable behavior)

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/autosplat/webui/routes/captures.py pipeline/tests/webui/test_review_routes.py
git commit -m "feat(webui): POST /captures/{id}/review/upload accepts a cleaned PLY"
```

---

### Task 5: Gate `POST /share` on `review_status`

**Files:**
- Modify: `pipeline/src/autosplat/webui/routes/captures.py`
- Modify: `pipeline/tests/webui/test_share_routes.py`

**Interfaces:**
- Consumes: `capture.review_status` (Task 1).
- Produces: no new interface — changes `POST /captures/{id}/share`'s behavior for `review_status == "unreviewed"`.

- [ ] **Step 1: Update the test fixture, then write the failing test**

The existing `_install()` helper in `test_share_routes.py` builds a capture with no review marker, so after this task's change it would default to `"unreviewed"` and break all three existing tests (they all expect `POST /share` to start a job). Fix the fixture first so existing tests keep testing the "already reviewed" happy path, and add a new test for the gate itself.

Replace `_install()` in `pipeline/tests/webui/test_share_routes.py` (`test_share_routes.py:20-37`):

```python
def _install(app: FastAPI, tmp_path: Path) -> Path:
    embed = _fake_embed(tmp_path)
    capture_dir = tmp_path / "2026-07-10_lgs"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"PLY" * 5000)
    (capture_dir / "pipeline.log").write_text("done\n")
    app.state.cfg.paths.captures_dir = tmp_path
    app.state.cfg.share.embed_src_path = embed
    app.state.cfg.share.base_url = "https://splat.example"

    def fake_compress(ply, out_dir, *, fmt="sog", quality="medium"):
        out_dir.mkdir(parents=True, exist_ok=True)
        sog = out_dir / f"{ply.stem}.sog"
        sog.write_bytes(b"SOG")
        return CompressResult(sog, "fake", "medium", 0.1, 15000, 3)

    app.state.share_runner = ShareJobRunner(app.state.cfg, compressor=fake_compress)
    return capture_dir
```

with:

```python
def _mark_reviewed(capture_dir: Path) -> None:
    import json

    scene_ply = capture_dir / "output" / "scene.ply"
    marker = capture_dir / "output" / ".review.json"
    marker.write_text(
        json.dumps(
            {
                "status": "reviewed",
                "reviewed_at": "2026-07-19T00:00:00",
                "source_ply_mtime": scene_ply.stat().st_mtime,
            }
        )
    )


def _install(app: FastAPI, tmp_path: Path, *, reviewed: bool = True) -> Path:
    embed = _fake_embed(tmp_path)
    capture_dir = tmp_path / "2026-07-10_lgs"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"PLY" * 5000)
    (capture_dir / "pipeline.log").write_text("done\n")
    app.state.cfg.paths.captures_dir = tmp_path
    app.state.cfg.share.embed_src_path = embed
    app.state.cfg.share.base_url = "https://splat.example"
    if reviewed:
        _mark_reviewed(capture_dir)

    def fake_compress(ply, out_dir, *, fmt="sog", quality="medium"):
        out_dir.mkdir(parents=True, exist_ok=True)
        sog = out_dir / f"{ply.stem}.sog"
        sog.write_bytes(b"SOG")
        return CompressResult(sog, "fake", "medium", 0.1, 15000, 3)

    app.state.share_runner = ShareJobRunner(app.state.cfg, compressor=fake_compress)
    return capture_dir
```

Append a new test to the same file:

```python
def test_post_share_redirects_to_view_when_unreviewed(app: FastAPI, tmp_path: Path) -> None:
    _install(app, tmp_path, reviewed=False)
    with TestClient(app) as client:
        r = client.post("/captures/2026-07-10_lgs/share", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/captures/2026-07-10_lgs/view"
    # no share job was started
    assert app.state.share_runner.get("2026-07-10_lgs") is None
```

- [ ] **Step 2: Run tests to verify state**

Run: `cd pipeline && uv run pytest tests/webui/test_share_routes.py -v`
Expected: the three pre-existing tests PASS (fixture now marks reviewed by default, so behavior is unchanged for them); `test_post_share_redirects_to_view_when_unreviewed` FAILS — the route currently starts a share job regardless of review status, so the redirect location is `/captures/2026-07-10_lgs` (not `/view`) and a job *was* started.

- [ ] **Step 3: Implement the gate in `routes/captures.py`**

Modify `capture_share` (`routes/captures.py:419-430`):

```python
@router.post("/{capture_id}/share")
async def capture_share(request: Request, capture_id: str) -> RedirectResponse:
    """Compress + assemble a self-hostable share bundle in the background."""
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
```

with:

```python
@router.post("/{capture_id}/share")
async def capture_share(request: Request, capture_id: str) -> RedirectResponse:
    """Compress + assemble a self-hostable share bundle in the background.

    Gated on the publish quality review (see review_status) — a capture
    must be reviewed at least once before its first share.
    """
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    if capture.review_status == "unreviewed":
        return RedirectResponse(url=f"/captures/{capture_id}/view", status_code=303)
```

(The rest of the function — `runner = _share_runner(request)` through the final redirect — is unchanged, just now reached only when reviewed.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/webui/test_share_routes.py -v`
Expected: PASS (all four tests)

Then: `cd pipeline && uv run pytest tests/webui/ -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/autosplat/webui/routes/captures.py pipeline/tests/webui/test_share_routes.py
git commit -m "feat(webui): gate POST /share on review_status"
```

---

### Task 6: Review panel on the view page

**Files:**
- Modify: `pipeline/src/autosplat/webui/templates/capture/view.html`
- Modify: `pipeline/tests/webui/test_review_routes.py`

**Interfaces:**
- Consumes: `capture.review_status` (Task 1), `review_error` (optional template var, Task 4), routes `/review/upload` and `/review/confirm` (Tasks 3-4).
- Produces: no new interface — purely template markup.

- [ ] **Step 1: Write the failing test**

Append to `pipeline/tests/webui/test_review_routes.py`:

```python
def test_view_page_shows_review_panel_when_unreviewed(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        body = client.get("/captures/2026-07-19_lgs/view").text

    assert 'action="/captures/2026-07-19_lgs/review/upload"' in body
    assert 'action="/captures/2026-07-19_lgs/review/confirm"' in body
    assert "Confirm unchanged" in body


def test_view_page_hides_review_panel_when_reviewed(app: FastAPI, tmp_path: Path) -> None:
    import json

    capture_dir = _make_capture(tmp_path)
    scene_ply = capture_dir / "output" / "scene.ply"
    (capture_dir / "output" / ".review.json").write_text(
        json.dumps(
            {
                "status": "reviewed",
                "reviewed_at": "2026-07-19T00:00:00",
                "source_ply_mtime": scene_ply.stat().st_mtime,
            }
        )
    )
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        body = client.get("/captures/2026-07-19_lgs/view").text

    assert 'action="/captures/2026-07-19_lgs/review/upload"' not in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && uv run pytest tests/webui/test_review_routes.py -k view_page -v`
Expected: FAIL — the panel doesn't exist yet, so `test_view_page_shows_review_panel_when_unreviewed` fails (no `review/upload` form in body); `test_view_page_hides_review_panel_when_reviewed` passes vacuously (nothing to hide yet) — that's expected at this point, it'll stay meaningful once Step 3 lands.

- [ ] **Step 3: Implement the panel in `view.html`**

Insert the review panel inside the `.as-viewer` div, right after the HUD top-right block and before its closing tag (`view.html:46-53`) — i.e. right before the floating fullscreen-close button:

```html
    {# HUD — bottom-center: publish quality gate (only before first review) #}
    {% if capture.review_status == 'unreviewed' %}
    <div class="as-viewer-pill" style="position:absolute;bottom:var(--space-3);left:50%;transform:translateX(-50%);z-index:2;flex-direction:column;align-items:stretch;gap:8px;padding:12px 16px;width:340px;text-transform:none;letter-spacing:normal">
      <div style="font-family:var(--font-mono);font-size:10px;font-weight:600;letter-spacing:var(--tracking-caps);text-transform:uppercase;color:var(--fg-secondary)">review before first share</div>
      {% if review_error %}
      <div style="color:var(--stage-failed);font-family:var(--font-mono);font-size:11px">{{ review_error }}</div>
      {% endif %}
      <form method="post" action="/captures/{{ capture.id }}/review/upload" enctype="multipart/form-data" style="display:flex;flex-direction:column;gap:6px">
        <input type="file" name="reviewed_ply" accept=".ply" required
               style="font-family:var(--font-mono);font-size:11px;color:var(--fg-primary)">
        <button type="submit" class="as-btn sm">Upload cleaned PLY</button>
      </form>
      <form method="post" action="/captures/{{ capture.id }}/review/confirm">
        <button type="submit" class="as-btn ghost sm" style="width:100%">{{ icon('check', 12) }} Confirm unchanged &rarr;</button>
      </form>
    </div>
    {% endif %}

    {# Floating close button — hidden by default, CSS shows it in viewer-fullscreen mode #}
    <button class="as-viewer-fs-close as-viewer-iconbtn" id="as-fs-close-btn" type="button" title="Exit fullscreen (Esc)">
      {{ icon('x', 14) }}
    </button>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/webui/test_review_routes.py -v`
Expected: PASS (all)

Then: `cd pipeline && uv run pytest tests/webui/ -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/autosplat/webui/templates/capture/view.html pipeline/tests/webui/test_review_routes.py
git commit -m "feat(webui): review panel on the view page before first share"
```

---

### Task 7: Share card branches on `review_status`

**Files:**
- Modify: `pipeline/src/autosplat/webui/templates/capture/detail.html`
- Modify: `pipeline/tests/webui/test_share_routes.py`

**Interfaces:**
- Consumes: `capture.review_status` (Task 1).
- Produces: no new interface — purely template markup.

- [ ] **Step 1: Write the failing test**

Append to `pipeline/tests/webui/test_share_routes.py`:

```python
def test_detail_page_shows_review_prompt_when_unreviewed(app: FastAPI, tmp_path: Path) -> None:
    _install(app, tmp_path, reviewed=False)
    with TestClient(app) as client:
        body = client.get("/captures/2026-07-10_lgs").text
    assert "Review &amp; Share" in body or "Review & Share" in body
    assert 'action="/captures/2026-07-10_lgs/share"' not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/webui/test_share_routes.py::test_detail_page_shows_review_prompt_when_unreviewed -v`
Expected: FAIL — the share card currently always renders the "Create share bundle" form regardless of `review_status`.

- [ ] **Step 3: Implement the branch in `detail.html`**

Replace the share card body (`pipeline/src/autosplat/webui/templates/capture/detail.html:214-221`):

```html
          <div id="as-share-region"
               hx-get="/partials/capture/{{ capture.id }}/share"
               hx-trigger="load"
               hx-swap="innerHTML">
            <form method="post" action="/captures/{{ capture.id }}/share">
              <button type="submit" class="as-btn sm">{{ icon('external', 12) }} Create share bundle</button>
            </form>
          </div>
```

with:

```html
          {% if capture.review_status == 'unreviewed' %}
          <a href="/captures/{{ capture.id }}/view" class="as-btn sm" style="text-decoration:none;display:inline-flex">
            {{ icon('eye', 12) }} Review &amp; Share
          </a>
          {% else %}
          <div id="as-share-region"
               hx-get="/partials/capture/{{ capture.id }}/share"
               hx-trigger="load"
               hx-swap="innerHTML">
            <form method="post" action="/captures/{{ capture.id }}/share">
              <button type="submit" class="as-btn sm">{{ icon('external', 12) }} Create share bundle</button>
            </form>
          </div>
          {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/webui/test_share_routes.py -v`
Expected: PASS (all five tests — including the pre-existing `test_detail_page_shows_share_card_for_done_capture`, which still passes because `_install()` defaults to `reviewed=True`)

Then run the full suite: `cd pipeline && uv run pytest -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/autosplat/webui/templates/capture/detail.html pipeline/tests/webui/test_share_routes.py
git commit -m "feat(webui): share card shows Review & Share prompt when unreviewed"
```

---

### Task 8: Full-suite verification + CHANGELOG

**Files:**
- Modify: `pipeline/CHANGELOG.md`
- Modify: `CHANGELOG.md` (root, if the repo's monorepo convention requires a root entry for cross-cutting WebUI features — check the last few entries for the pattern first)

**Interfaces:**
- Consumes: nothing new — this task only verifies and documents.

- [ ] **Step 1: Run the full pipeline test suite**

Run: `cd pipeline && uv run pytest -q`
Expected: PASS (all tests, including the ~470+ pre-existing ones plus the ~20 new ones from Tasks 1-7)

- [ ] **Step 2: Run lint + type checks**

Run: `cd pipeline && uv run ruff check . && uv run mypy src/autosplat/webui/`
Expected: no errors. If `mypy` flags the `UploadFile`/`File` usage or the `Literal` default on `CaptureInfo.review_status`, fix the reported issue directly (e.g. an explicit type annotation) rather than suppressing it.

- [ ] **Step 3: Add a CHANGELOG entry**

Read `pipeline/CHANGELOG.md`'s top entry first to match its exact heading style, then add a new `### Added` bullet under an `## [Unreleased]` (or next-version) heading describing: "Publish quality gate — captures must be reviewed once in the SuperSplat viewer (upload a cleaned PLY or confirm unchanged) before their first share; auto-invalidates when the capture is rebuilt."

- [ ] **Step 4: Commit**

```bash
git add pipeline/CHANGELOG.md
git commit -m "docs(pipeline): changelog entry for publish quality gate"
```

## Manual verification (not automated — do after Task 8)

Start the WebUI (`cd pipeline && uv run autosplat webui --port 8080`) against a real `done` capture and confirm in the browser:
1. Detail page shows "Review & Share" (not "Create share bundle") for a capture that has never been reviewed.
2. Clicking it opens the view page with the bottom panel visible.
3. "Confirm unchanged" round-trips back to the detail page, which now shows the normal "Create share bundle" button.
4. Uploading a non-`.ply` file shows the error banner and stays on the view page.
5. Uploading a real cleaned `.ply` (e.g. exported from SuperSplat's own export feature) round-trips, and the "View splat" iframe subsequently loads the cleaned file (confirm via file size or visual diff).
6. Triggering "Add video & rebuild" on a reviewed capture flips the detail page back to "Review & Share" once the rebuild finishes.
