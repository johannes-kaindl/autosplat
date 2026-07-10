# WebUI Share Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an on-demand WebUI action on a finished capture that compresses the scene to `.sog` and assembles a self-contained, self-hostable share bundle with an unguessable link.

**Architecture:** A pure assembly module (`share.py`) builds the bundle; a small dedicated `ShareJobRunner` runs compression + assembly in a background thread (keyed by capture_id, separate from the pipeline `JobRunner` so the capture stays `done`); FastAPI routes start the job, poll a partial, and serve the zip; a detail-page card drives it.

**Tech Stack:** Python 3.11+, FastAPI, HTMX, Jinja2, Pydantic v2, pytest. Compression via the existing `compress_ply` (splat-transform over npx).

## Global Constraints

- SPDX header on every new file: `# SPDX-License-Identifier: AGPL-3.0-or-later`
- `uv run mypy` must pass (strict) and `uv run ruff check` clean before each commit.
- SOG only in v1 (`fmt="sog"`); no SPZ/KSPLAT knob.
- Compression quality reuses the existing `cfg.compress.quality` (DRY — no separate `[share] quality`).
- Viewer runtime is copied from `cfg.share.viewer_src_path` (default `../viewer`, resolved against cwd like `viewer.supersplat_dist_path`); v1 runs from the monorepo source checkout.
- **Known characteristic (not a bug):** the bundled `viewer.html` loads the PlayCanvas engine from `cdn.jsdelivr.net` via importmap — same as the live viewer. The bundle is self-hosted for viewer code + splat data, but needs internet for the engine. Vendoring the engine is a possible later slice.
- Security model is **unlisted** (unguessable token), not access control — surfaced in the UI copy.
- Run commands from `pipeline/`. Test command: `uv run pytest <path> -v`.

---

## File Structure

- Create: `src/autosplat/webui/share.py` — pure token/link/bundle logic.
- Create: `src/autosplat/webui/share_runner.py` — `ShareJob` + `ShareJobRunner`.
- Create: `src/autosplat/webui/templates/partials/share.html` — poll/result partial.
- Create: `tests/webui/test_share.py` — unit tests for share.py.
- Create: `tests/webui/test_share_runner.py` — ShareJobRunner tests.
- Create: `tests/webui/test_share_routes.py` — route tests.
- Modify: `src/autosplat/config.py` — add `ShareConfig` + `Config.share`.
- Modify: `config/default.toml` — add `[share]` section.
- Modify: `src/autosplat/webui/app.py` — wire `app.state.share_runner`.
- Modify: `src/autosplat/webui/routes/captures.py` — `POST /share`, `GET /share/{token}.zip`.
- Modify: `src/autosplat/webui/routes/partials.py` — `GET /capture/{id}/share`.
- Modify: `src/autosplat/webui/templates/capture/detail.html` — share card.

---

## Task 1: `[share]` config section

**Files:**
- Modify: `src/autosplat/config.py` (add `ShareConfig`, add field to `Config`)
- Modify: `config/default.toml` (add `[share]`)
- Test: `tests/test_config.py` (or nearest existing config test)

**Interfaces:**
- Produces: `cfg.share.base_url: str`, `cfg.share.viewer_src_path: Path`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_share_config_defaults() -> None:
    from autosplat.config import load_config

    cfg = load_config(include_xdg=False)
    assert cfg.share.base_url == ""
    assert str(cfg.share.viewer_src_path) == "../viewer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_share_config_defaults -v`
Expected: FAIL (`Config` has no attribute `share`).

- [ ] **Step 3: Implement**

In `src/autosplat/config.py`, add after `CompressConfig`:

```python
class ShareConfig(BaseModel):
    """Web-export share bundles: compress + self-contained viewer package."""

    base_url: str = Field(
        default="",
        description="Public base URL of your splat host, e.g. 'https://splat.jkaindl.de'. "
        "Empty → the UI shows a host-agnostic link template instead.",
    )
    viewer_src_path: Path = Field(
        default=Path("../viewer"),
        description="Path to the viewer static sources copied into each bundle. "
        "Relative paths resolve against the current working directory.",
    )
```

Add to `class Config` (after the `compress` field):

```python
    share: ShareConfig = Field(default_factory=ShareConfig)
```

In `config/default.toml`, add a new section (after `[compress]` if present, else at end):

```toml
[share]
# Web-export share bundles. base_url is your public splat host; empty shows a
# link template. viewer_src_path is copied into each self-contained bundle.
base_url = ""
viewer_src_path = "../viewer"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py::test_share_config_defaults -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autosplat/config.py config/default.toml tests/test_config.py
git commit -m "feat(webui): [share] config section for web-export bundles"
```

---

## Task 2: token + link builders (`share.py`)

**Files:**
- Create: `src/autosplat/webui/share.py`
- Test: `tests/webui/test_share.py`

**Interfaces:**
- Produces: `make_share_token(capture_id: str, *, rand: Callable[[int], str] | None = None) -> str`
- Produces: `share_link(base_url: str, token: str) -> str | None`

- [ ] **Step 1: Write the failing test**

Create `tests/webui/test_share.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

from autosplat.webui.share import make_share_token, share_link


def test_token_is_url_safe_with_capture_prefix() -> None:
    token = make_share_token("2026-07-10_LGS_PV_20260610", rand=lambda n: "a" * n)
    # date stripped, stem slugified, fixed random suffix
    assert token == "lgs-pv-20260610-aaaaaaaaaa"
    assert all(c.islower() or c.isdigit() or c == "-" for c in token)


def test_token_random_suffix_differs() -> None:
    calls = iter(["k7m2a9x4qz", "zz11yy22xx"])
    t1 = make_share_token("2026-07-10_x", rand=lambda n: next(calls))
    t2 = make_share_token("2026-07-10_x", rand=lambda n: next(calls))
    assert t1 != t2


def test_share_link_complete_when_base_url_set() -> None:
    assert share_link("https://splat.jkaindl.de/", "abc") == "https://splat.jkaindl.de/abc/"


def test_share_link_none_when_base_url_empty() -> None:
    assert share_link("", "abc") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/webui/test_share.py -v`
Expected: FAIL (`No module named 'autosplat.webui.share'`).

- [ ] **Step 3: Implement**

Create `src/autosplat/webui/share.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Assemble a self-contained, self-hostable share bundle from a compressed splat.

A bundle is a folder named by an unguessable token containing a copy of the
viewer runtime plus the client's `.sog` at `c/scene.sog`, entered via an
`index.html` redirect to `viewer.html?src=c/scene.sog`. The whole folder is also
zipped for one-click download. "Unlisted" = the token is unguessable; this is
not access control.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# base32 alphabet without padding — URL-safe, case-insensitive
_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
_SUFFIX_LEN = 10  # ~50 bits of entropy


def _default_rand(n: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")


def make_share_token(capture_id: str, *, rand: Callable[[int], str] | None = None) -> str:
    """Return a URL-safe token: slugified capture stem + random base32 suffix.

    The leading ``YYYY-MM-DD_`` date prefix of the capture id is dropped so the
    readable part is the scene name, e.g. ``lgs-pv-20260610-k7m2a9x4qz``.
    """
    rand = rand or _default_rand
    stem = capture_id.split("_", 1)[1] if "_" in capture_id else capture_id
    prefix = _slugify(stem) or "scene"
    return f"{prefix}-{rand(_SUFFIX_LEN)}"


def share_link(base_url: str, token: str) -> str | None:
    """Full ``{base_url}/{token}/`` link, or None when base_url is unset."""
    if not base_url.strip():
        return None
    return f"{base_url.rstrip('/')}/{token}/"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/webui/test_share.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/autosplat/webui/share.py tests/webui/test_share.py
git commit -m "feat(webui): share token + link builders"
```

---

## Task 3: bundle assembler (`share.py`)

**Files:**
- Modify: `src/autosplat/webui/share.py` (add `assemble_bundle` + `BundlePaths`)
- Test: `tests/webui/test_share.py` (add cases)

**Interfaces:**
- Consumes: nothing new.
- Produces: `assemble_bundle(sog_path: Path, viewer_src: Path, share_dir: Path, token: str) -> BundlePaths` where `BundlePaths` has `.folder: Path` and `.zip_path: Path`.

- [ ] **Step 1: Write the failing test**

Add to `tests/webui/test_share.py`:

```python
import zipfile
from pathlib import Path

from autosplat.webui.share import BundlePaths, assemble_bundle


def _fake_viewer(root: Path) -> Path:
    v = root / "viewer"
    (v / "js").mkdir(parents=True)
    (v / "assets" / "demo").mkdir(parents=True)
    (v / "tests").mkdir()
    (v / "viewer.html").write_text("<html>viewer</html>")
    (v / "js" / "app.js").write_text("// app")
    (v / "assets" / "demo" / "scene.sog").write_bytes(b"DEMO" * 100)  # must NOT be copied
    (v / "tests" / "t.py").write_text("# test")  # must NOT be copied
    (v / "LICENSE").write_text("AGPL")
    return v


def test_assemble_bundle_builds_self_contained_tree(tmp_path: Path) -> None:
    viewer = _fake_viewer(tmp_path)
    sog = tmp_path / "scene.sog"
    sog.write_bytes(b"SPLAT" * 1000)
    share_dir = tmp_path / "cap" / "share"

    paths = assemble_bundle(sog, viewer, share_dir, "lgs-pv-aaaaaaaaaa")

    assert isinstance(paths, BundlePaths)
    folder = paths.folder
    assert folder == share_dir / "lgs-pv-aaaaaaaaaa"
    # viewer runtime copied
    assert (folder / "viewer.html").exists()
    assert (folder / "js" / "app.js").exists()
    assert (folder / "LICENSE").exists()
    # client splat placed under c/
    assert (folder / "c" / "scene.sog").read_bytes() == b"SPLAT" * 1000
    # entry redirect
    index = (folder / "index.html").read_text()
    assert "viewer.html?src=c/scene.sog" in index
    # allowlist: demo sog + tests dir excluded
    assert not (folder / "assets").exists()
    assert not (folder / "tests").exists()
    # zip mirrors the folder
    assert paths.zip_path == share_dir / "lgs-pv-aaaaaaaaaa.zip"
    with zipfile.ZipFile(paths.zip_path) as zf:
        names = zf.namelist()
        assert any(n.endswith("c/scene.sog") for n in names)
        assert any(n.endswith("viewer.html") for n in names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/webui/test_share.py::test_assemble_bundle_builds_self_contained_tree -v`
Expected: FAIL (`cannot import name 'assemble_bundle'`).

- [ ] **Step 3: Implement**

Add to `src/autosplat/webui/share.py` (imports at top, then the code):

```python
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Top-level viewer entries copied into a bundle. Allowlist (not denylist) so a
# future stray file in viewer/ never leaks into a client's public bundle.
_VIEWER_ALLOWLIST = (
    "viewer.html",
    "js",
    "css",
    "icons",
    "manifest.webmanifest",
    "service-worker.js",
    "LICENSE",
)

_INDEX_REDIRECT = (
    "<!doctype html><meta charset=utf-8>"
    '<meta http-equiv=refresh content="0; url=viewer.html?src=c/scene.sog">'
    '<link rel=canonical href="viewer.html?src=c/scene.sog">'
    '<a href="viewer.html?src=c/scene.sog">Open viewer</a>'
)


@dataclass
class BundlePaths:
    folder: Path
    zip_path: Path


def assemble_bundle(
    sog_path: Path, viewer_src: Path, share_dir: Path, token: str
) -> BundlePaths:
    """Build ``share_dir/<token>/`` (self-contained viewer + splat) and its zip.

    Raises FileNotFoundError if ``viewer_src`` or a required allowlist entry is
    missing (surfaces the monorepo-source requirement clearly).
    """
    if not (viewer_src / "viewer.html").exists():
        raise FileNotFoundError(f"viewer sources not found at {viewer_src}")

    folder = share_dir / token
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    for name in _VIEWER_ALLOWLIST:
        src = viewer_src / name
        if not src.exists():
            continue  # optional entries (e.g. service-worker) tolerated
        dest = folder / name
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)

    c_dir = folder / "c"
    c_dir.mkdir()
    shutil.copy2(sog_path, c_dir / "scene.sog")

    (folder / "index.html").write_text(_INDEX_REDIRECT, encoding="utf-8")

    zip_path = share_dir / f"{token}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            zf.write(path, path.relative_to(share_dir))

    return BundlePaths(folder=folder, zip_path=zip_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/webui/test_share.py -v`
Expected: PASS (all share.py tests).

- [ ] **Step 5: Commit**

```bash
git add src/autosplat/webui/share.py tests/webui/test_share.py
git commit -m "feat(webui): self-contained share-bundle assembler"
```

---

## Task 4: ShareJobRunner (`share_runner.py`)

**Files:**
- Create: `src/autosplat/webui/share_runner.py`
- Test: `tests/webui/test_share_runner.py`

**Interfaces:**
- Consumes: `make_share_token`, `assemble_bundle`, `share_link`, `Config`.
- Produces:
  - `ShareJob` dataclass with `.status: Literal["running","done","failed"]`, `.token: str | None`, `.zip_path: Path | None`, `.output_bytes: int | None`, `.input_bytes: int | None`, `.error: str | None`, `.link: str | None`.
  - `ShareJobRunner(cfg, compressor=compress_ply)` with `.start(capture_id, capture_dir) -> ShareJob`, `.get(capture_id) -> ShareJob | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/webui/test_share_runner.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

import time
from pathlib import Path

from autosplat.compress import CompressResult
from autosplat.config import load_config
from autosplat.webui.share_runner import ShareJobRunner


def _fake_viewer(root: Path) -> Path:
    v = root / "viewer"
    v.mkdir()
    (v / "viewer.html").write_text("<html>v</html>")
    return v


def _wait(job, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(0.02)


def test_share_job_compresses_and_bundles(tmp_path: Path) -> None:
    viewer = _fake_viewer(tmp_path)
    capture_dir = tmp_path / "2026-07-10_lgs"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"PLY" * 5000)

    def fake_compress(ply: Path, out_dir: Path, *, fmt: str = "sog", quality: str = "medium"):
        out_dir.mkdir(parents=True, exist_ok=True)
        sog = out_dir / f"{ply.stem}.sog"
        sog.write_bytes(b"SOG" * 100)
        return CompressResult(
            output_path=sog, backend_used="fake", quality="medium",
            duration_s=0.1, input_bytes=15000, output_bytes=300,
        )

    cfg = load_config(include_xdg=False)
    cfg.share.base_url = "https://splat.example"
    cfg.share.viewer_src_path = viewer
    runner = ShareJobRunner(cfg, compressor=fake_compress)

    job = runner.start("2026-07-10_lgs", capture_dir)
    _wait(job)

    assert job.status == "done"
    assert job.token and job.token.startswith("lgs-")
    assert job.zip_path is not None and job.zip_path.exists()
    assert (capture_dir / "share" / job.token / "c" / "scene.sog").exists()
    assert job.output_bytes == 300 and job.input_bytes == 15000
    assert job.link == f"https://splat.example/{job.token}/"


def test_share_job_fails_without_ply(tmp_path: Path) -> None:
    viewer = _fake_viewer(tmp_path)
    capture_dir = tmp_path / "2026-07-10_empty"
    capture_dir.mkdir()
    cfg = load_config(include_xdg=False)
    cfg.share.viewer_src_path = viewer
    runner = ShareJobRunner(cfg)

    job = runner.start("2026-07-10_empty", capture_dir)
    _wait(job)

    assert job.status == "failed"
    assert job.error and "scene.ply" in job.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/webui/test_share_runner.py -v`
Expected: FAIL (`No module named 'autosplat.webui.share_runner'`).

- [ ] **Step 3: Implement**

Create `src/autosplat/webui/share_runner.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Background runner for share-bundle jobs.

Kept separate from the pipeline JobRunner: a share job must NOT flip the
capture's status to 'running' — the capture stays 'done' and only the share
card reflects bundle progress.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from autosplat.compress import compress_ply
from autosplat.config import Config
from autosplat.logging import get_logger
from autosplat.webui.share import assemble_bundle, make_share_token, share_link

logger = get_logger(__name__)

ShareStatus = Literal["running", "done", "failed"]


@dataclass
class ShareJob:
    capture_id: str
    status: ShareStatus = "running"
    token: str | None = None
    zip_path: Path | None = None
    output_bytes: int | None = None
    input_bytes: int | None = None
    link: str | None = None
    error: str | None = None
    _thread: threading.Thread | None = field(default=None, repr=False)


class ShareJobRunner:
    def __init__(self, cfg: Config, compressor=compress_ply) -> None:
        self._cfg = cfg
        self._compress = compressor
        self._jobs: dict[str, ShareJob] = {}

    def get(self, capture_id: str) -> ShareJob | None:
        return self._jobs.get(capture_id)

    def start(self, capture_id: str, capture_dir: Path) -> ShareJob:
        existing = self._jobs.get(capture_id)
        if existing is not None and existing.status == "running":
            return existing
        job = ShareJob(capture_id=capture_id)
        self._jobs[capture_id] = job
        thread = threading.Thread(
            target=self._run, args=(job, capture_dir), daemon=True,
            name=f"autosplat-share-{capture_id}",
        )
        job._thread = thread
        thread.start()
        return job

    def _run(self, job: ShareJob, capture_dir: Path) -> None:
        try:
            ply = capture_dir / "output" / "scene.ply"
            if not ply.exists():
                raise FileNotFoundError(f"No output/scene.ply in {capture_dir}")

            result = self._compress(
                ply, capture_dir / "share" / "_tmp",
                fmt="sog", quality=self._cfg.compress.quality,
            )
            token = make_share_token(job.capture_id)
            viewer_src = self._resolve_viewer_src()
            paths = assemble_bundle(
                result.output_path, viewer_src, capture_dir / "share", token
            )

            job.token = token
            job.zip_path = paths.zip_path
            job.output_bytes = result.output_bytes
            job.input_bytes = result.input_bytes
            job.link = share_link(self._cfg.share.base_url, token)
            job.status = "done"
            logger.info("share.done", capture_id=job.capture_id, token=token)
        except Exception as e:  # noqa: BLE001 — surfaced on the job, not raised
            job.status = "failed"
            job.error = str(e)
            logger.error("share.failed", capture_id=job.capture_id, error=str(e))

    def _resolve_viewer_src(self) -> Path:
        p = self._cfg.share.viewer_src_path
        return p if p.is_absolute() else (Path.cwd() / p)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/webui/test_share_runner.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/autosplat/webui/share_runner.py tests/webui/test_share_runner.py
git commit -m "feat(webui): ShareJobRunner — background compress + bundle"
```

---

## Task 5: routes + app wiring

**Files:**
- Modify: `src/autosplat/webui/app.py` (create `app.state.share_runner`)
- Modify: `src/autosplat/webui/routes/captures.py` (`POST /share`, `GET /share/{token}.zip`)
- Modify: `src/autosplat/webui/routes/partials.py` (`GET /capture/{id}/share`)
- Test: `tests/webui/test_share_routes.py`

**Interfaces:**
- Consumes: `ShareJobRunner`, `get_capture`.
- Produces: `app.state.share_runner: ShareJobRunner`; routes `POST /captures/{id}/share`, `GET /captures/{id}/share/{token}.zip`, `GET /partials/capture/{id}/share`.

- [ ] **Step 1: Write the failing test**

Create `tests/webui/test_share_routes.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

import time
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from autosplat.compress import CompressResult
from autosplat.webui.share_runner import ShareJobRunner


def _fake_viewer(root: Path) -> Path:
    v = root / "viewer"
    v.mkdir()
    (v / "viewer.html").write_text("<html>v</html>")
    return v


def _install(app: FastAPI, tmp_path: Path) -> Path:
    viewer = _fake_viewer(tmp_path)
    capture_dir = tmp_path / "2026-07-10_lgs"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"PLY" * 5000)
    (capture_dir / "pipeline.log").write_text("done\n")
    app.state.cfg.paths.captures_dir = tmp_path
    app.state.cfg.share.viewer_src_path = viewer
    app.state.cfg.share.base_url = "https://splat.example"

    def fake_compress(ply, out_dir, *, fmt="sog", quality="medium"):
        out_dir.mkdir(parents=True, exist_ok=True)
        sog = out_dir / f"{ply.stem}.sog"
        sog.write_bytes(b"SOG")
        return CompressResult(sog, "fake", "medium", 0.1, 15000, 3)

    app.state.share_runner = ShareJobRunner(app.state.cfg, compressor=fake_compress)
    return capture_dir


def test_post_share_starts_job_and_partial_shows_link(app: FastAPI, tmp_path: Path) -> None:
    _install(app, tmp_path)
    with TestClient(app) as client:
        r = client.post("/captures/2026-07-10_lgs/share", follow_redirects=False)
        assert r.status_code == 303
        # let the background thread finish
        for _ in range(150):
            body = client.get("/partials/capture/2026-07-10_lgs/share").text
            if "https://splat.example/" in body:
                break
            time.sleep(0.02)
        assert "https://splat.example/lgs-" in body
        assert "share/lgs-" in body and ".zip" in body


def test_share_zip_downloads(app: FastAPI, tmp_path: Path) -> None:
    _install(app, tmp_path)
    with TestClient(app) as client:
        client.post("/captures/2026-07-10_lgs/share", follow_redirects=False)
        token = None
        for _ in range(150):
            job = app.state.share_runner.get("2026-07-10_lgs")
            if job and job.status == "done":
                token = job.token
                break
            time.sleep(0.02)
        assert token is not None
        r = client.get(f"/captures/2026-07-10_lgs/share/{token}.zip")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/webui/test_share_routes.py -v`
Expected: FAIL (404 on `/share` — routes not defined).

- [ ] **Step 3: Implement**

In `src/autosplat/webui/app.py`, after `app.state.job_runner = runner`, add:

```python
    from .share_runner import ShareJobRunner

    app.state.share_runner = ShareJobRunner(cfg) if cfg is not None else None
```

In `src/autosplat/webui/routes/captures.py`, add a helper near `_job_runner`:

```python
def _share_runner(request: Request):
    return getattr(request.app.state, "share_runner", None)
```

Add these routes to `captures.py` (import `FileResponse` is already present):

```python
@router.post("/{capture_id}/share")
async def capture_share(request: Request, capture_id: str) -> RedirectResponse:
    """Compress + assemble a self-hostable share bundle in the background."""
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    runner = _share_runner(request)
    if runner is None:
        raise HTTPException(status_code=503, detail="Share runner not available")
    runner.start(capture_id, capture.path)
    return RedirectResponse(url=f"/captures/{capture_id}", status_code=303)


@router.get("/{capture_id}/share/{token}.zip")
async def capture_share_zip(request: Request, capture_id: str, token: str) -> FileResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    zip_path = capture.path / "share" / f"{token}.zip"
    if not zip_path.is_file():
        raise HTTPException(status_code=404, detail="Bundle not found")
    return FileResponse(
        zip_path, media_type="application/zip",
        filename=f"{token}.zip",
    )
```

In `src/autosplat/webui/routes/partials.py`, add:

```python
@router.get("/capture/{capture_id}/share", response_class=HTMLResponse)
async def capture_share_partial(request: Request, capture_id: str) -> HTMLResponse:
    runner = getattr(request.app.state, "share_runner", None)
    job = runner.get(capture_id) if runner is not None else None
    return _templates(request).TemplateResponse(
        request,
        "partials/share.html",
        {"capture_id": capture_id, "job": job},
    )
```

- [ ] **Step 4: Run test to verify it passes**

First create a minimal `partials/share.html` so the partial renders (full styling in Task 6):

```html
{% if job and job.status == 'done' %}
  <div class="share-done">
    {% if job.link %}<a href="{{ job.link }}">{{ job.link }}</a>{% else %}<code>{{ job.token }}/</code>{% endif %}
    <a href="/captures/{{ capture_id }}/share/{{ job.token }}.zip">Download .zip</a>
  </div>
{% elif job and job.status == 'failed' %}
  <div class="share-failed">{{ job.error }}</div>
{% elif job %}
  <div hx-get="/partials/capture/{{ capture_id }}/share" hx-trigger="every 2s" hx-swap="outerHTML">building…</div>
{% else %}
  <div>—</div>
{% endif %}
```

Run: `uv run pytest tests/webui/test_share_routes.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/autosplat/webui/app.py src/autosplat/webui/routes/captures.py \
  src/autosplat/webui/routes/partials.py \
  src/autosplat/webui/templates/partials/share.html tests/webui/test_share_routes.py
git commit -m "feat(webui): share routes + app wiring (POST/partial/zip)"
```

---

## Task 6: GUI — detail-page share card

**Files:**
- Modify: `src/autosplat/webui/templates/capture/detail.html` (add card)
- Modify: `src/autosplat/webui/templates/partials/share.html` (full styling)
- Test: `tests/webui/test_share_routes.py` (add a render assertion)

**Interfaces:**
- Consumes: `capture` (CaptureInfo), the `/share` partial + routes from Task 5.

- [ ] **Step 1: Write the failing test**

Add to `tests/webui/test_share_routes.py`:

```python
def test_detail_page_shows_share_card_for_done_capture(app: FastAPI, tmp_path: Path) -> None:
    _install(app, tmp_path)
    with TestClient(app) as client:
        body = client.get("/captures/2026-07-10_lgs").text
    assert "Create share bundle" in body
    assert "anyone with this link" in body.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/webui/test_share_routes.py::test_detail_page_shows_share_card_for_done_capture -v`
Expected: FAIL (card copy not present).

- [ ] **Step 3: Implement**

In `src/autosplat/webui/templates/capture/detail.html`, inside the right-column `<aside>`, after the `capture.status == 'done'` splat-final card block, add:

```html
      {% if capture.status == 'done' and capture.has_ply %}
      <div class="as-card" id="as-share-card">
        <div class="as-card-head">
          <span class="t">web export · share</span><span class="spacer"></span>
          {{ icon('share-2', 13) }}
        </div>
        <div class="as-card-body" style="display:flex;flex-direction:column;gap:10px">
          <p style="margin:0;font-family:var(--font-body);font-size:12.5px;color:var(--fg-secondary);line-height:1.55">
            Compress to a web-optimal <code style="font-family:var(--font-mono);font-size:10px">.sog</code>
            and package a self-contained viewer you can host anywhere.
            <strong>Anyone with this link can view this model</strong> — it is unlisted, not access-controlled.
          </p>
          <div id="as-share-region"
               hx-get="/partials/capture/{{ capture.id }}/share"
               hx-trigger="load"
               hx-swap="innerHTML">
            <form method="post" action="/captures/{{ capture.id }}/share">
              <button type="submit" class="as-btn sm">{{ icon('share-2', 12) }} Create share bundle</button>
            </form>
          </div>
        </div>
      </div>
      {% endif %}
```

Replace `src/autosplat/webui/templates/partials/share.html` with:

```html
{%- from "_icons.html" import icon -%}
{% if job and job.status == 'done' %}
<div style="display:flex;flex-direction:column;gap:8px;font-family:var(--font-mono);font-size:11px">
  <div style="color:var(--fg-tertiary)">
    {% if job.output_bytes and job.input_bytes %}
    {{ '%.0f'|format(job.output_bytes / 1048576) }} mb ·
    {{ '%.0f'|format((1 - job.output_bytes / job.input_bytes) * 100) }} % smaller
    {% endif %}
  </div>
  {% if job.link %}
  <a href="{{ job.link }}" target="_blank" rel="noopener"
     style="color:var(--signal-circuit);word-break:break-all">{{ job.link }}</a>
  {% else %}
  <div style="color:var(--fg-secondary)">Upload the bundle, then share
    <code>&lt;your-host&gt;/{{ job.token }}/</code></div>
  {% endif %}
  <a href="/captures/{{ capture_id }}/share/{{ job.token }}.zip"
     class="as-btn sm ghost" download>{{ icon('download', 11) }} Download bundle (.zip)</a>
</div>
{% elif job and job.status == 'failed' %}
<div style="color:var(--stage-failed);font-family:var(--font-mono);font-size:11px">{{ job.error }}</div>
{% elif job %}
<div hx-get="/partials/capture/{{ capture_id }}/share" hx-trigger="every 2s" hx-swap="outerHTML"
     style="display:flex;align-items:center;gap:7px;font-family:var(--font-mono);font-size:11px;color:var(--fg-tertiary)">
  <span class="as-pulse-dot" style="width:7px;height:7px;border-radius:50%;background:var(--signal-circuit);display:inline-block"></span>
  building bundle…
</div>
{% else %}
<form method="post" action="/captures/{{ capture_id }}/share">
  <button type="submit" class="as-btn sm">{{ icon('share-2', 12) }} Create share bundle</button>
</form>
{% endif %}
```

Note: the partial is self-driving — while `running` it polls itself; when
terminal it renders without a poll trigger, so polling stops. The card's initial
`hx-trigger="load"` fetch reflects an already-running/finished job on page load.

If `icon('share-2', …)` is not in `_icons.html`, use `icon('upload', …)` or add
a `share-2` entry mirroring an existing icon macro.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/webui/test_share_routes.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/autosplat/webui/templates/capture/detail.html \
  src/autosplat/webui/templates/partials/share.html tests/webui/test_share_routes.py
git commit -m "feat(webui): share-bundle card on capture detail page"
```

---

## Task 7: Full-suite verify + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run the whole WebUI suite + type/lint**

```bash
uv run pytest tests/webui/ -q
uv run mypy src/autosplat/webui/
uv run ruff check src/autosplat/webui/ tests/webui/
```

Expected: all pass, mypy + ruff clean.

- [ ] **Step 2: Add CHANGELOG entry**

Under `## [Unreleased]` → `### Added` in `CHANGELOG.md`:

```markdown
### Added

- **WebUI "Create share bundle"** — an on-demand action on a finished capture
  compresses the scene to `.sog` and assembles a self-contained, self-hostable
  viewer bundle (folder + `.zip`) reachable via an unguessable link
  (`[share] base_url`). Unlisted, not access-controlled. Runs as a background
  job that leaves the capture's `done` status untouched.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): WebUI share bundle"
```

---

## Self-Review

**Spec coverage:**
- Compression (reuse `compress_ply`) → Task 4. ✓
- Self-contained bundle (viewer copy + `c/scene.sog` + index redirect + zip) → Task 3. ✓
- Unguessable token + link → Task 2. ✓
- Separate ShareJobRunner (capture stays `done`) → Task 4 + route test asserts no status change indirectly (capture rendered as done in Task 6). ✓
- Routes POST/partial/zip → Task 5. ✓
- GUI card → Task 6. ✓
- `[share]` config (base_url, viewer_src_path) → Task 1. ✓
- Unlisted-not-access-control UI copy → Task 6 (asserted). ✓
- Testing with stubbed compressor → Tasks 4–6. ✓
- CDN engine characteristic documented → Global Constraints. ✓

**Deviations from spec (intentional):** `[share] quality` dropped — compression
quality reuses `cfg.compress.quality` (DRY). Spec's `assets/` handling: the
allowlist omits `assets/` entirely (no runtime need; keeps bundles small).

**Type consistency:** `ShareJob` fields (`token`, `zip_path`, `output_bytes`,
`input_bytes`, `link`, `error`, `status`) are consumed identically in
`share.html` and the route tests. `assemble_bundle(sog_path, viewer_src,
share_dir, token) -> BundlePaths(.folder, .zip_path)` matches its caller in
`share_runner._run`. `CompressResult(output_path, backend_used, quality,
duration_s, input_bytes, output_bytes)` matches the real dataclass.
