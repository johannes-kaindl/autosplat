# Share-Bundle-Migration auf `embed/` + DMG-Packaging-Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch the pipeline's WebUI "Create share bundle" export from the geparkten `viewer/` to the new zero-external `embed/` component, and fix the underlying CWD-relative path bug that makes the feature non-functional in the packaged DMG app.

**Architecture:** `ShareConfig.embed_src_path` (renamed from `viewer_src_path`) gets a frozen-aware `default_factory` mirroring `_packaged_default_config()` in `config.py`. `share.py`'s `_EMBED_ALLOWLIST` copies `embed/`'s public files (`index.html, js, css, vendor`) into each bundle; `embed/index.html` is itself the entry point, so the old redirect-file logic is removed and `share_link()` appends `?src=c/scene.sog` directly. `AutoSplat.spec` gains `datas` entries so a future PyInstaller build actually contains `embed/`.

**Tech Stack:** Python 3.11+, pydantic (Config), pytest (`uv run pytest -q`).

## Global Constraints

- **`cd pipeline && uv run pytest -q` muss vor jedem Commit grün sein.**
- Conventional Commits mit Trailer `Co-Authored-By: Claude <noreply@anthropic.com>`
  (bzw. dem Modell-spezifischen Trailer der ausführenden Session).
- Config-Feld wird **umbenannt** (`viewer_src_path` → `embed_src_path`), nicht als
  Alias beibehalten — die alte Bezeichnung würde dauerhaft in die Irre führen.
- `default.toml`s explizite `viewer_src_path = "../viewer"`-Zeile wird **entfernt**
  (nicht umbenannt) — ein expliziter TOML-Wert würde den neuen, frozen-aware
  Python-Default sonst wieder überschreiben.
- DMG neu bauen/signieren/releasen ist **nicht** Teil dieses Plans (Task 6 ist
  reine Doku- und Test-Verifikation, kein Rebuild).
- Alle Pfade unten relativ zum Repo-Root `/Users/Shared/code/autosplat`.

---

### Task 1: Config-Layer — `embed_src_path` mit Frozen-Aware Default

**Files:**
- Modify: `pipeline/src/autosplat/config.py`
- Modify: `pipeline/config/default.toml`
- Modify: `pipeline/tests/test_config.py`

**Interfaces:**
- Consumes: —
- Produces: `Config.share.embed_src_path: Path` (immer absolut, Default via
  `_default_embed_src()`) — konsumiert von Task 3 (`share_runner.py`).

- [ ] **Step 1: Failing Test schreiben**

In `pipeline/tests/test_config.py` die bestehende Funktion `test_share_config_defaults`
(Zeilen 37-40) ersetzen durch:

```python
def test_share_config_defaults() -> None:
    cfg = load_config(include_xdg=False)
    assert cfg.share.base_url == ""
    assert cfg.share.embed_src_path.is_absolute()
    assert cfg.share.embed_src_path.name == "embed"
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `cd pipeline && uv run pytest tests/test_config.py::test_share_config_defaults -q`
Expected: FAIL — `AttributeError: 'ShareConfig' object has no attribute 'embed_src_path'`

- [ ] **Step 3: `config.py` implementieren**

In `pipeline/src/autosplat/config.py` direkt nach der bestehenden Funktion
`_packaged_default_config()` (endet vor `PACKAGED_DEFAULT_CONFIG = _packaged_default_config()`
bei Zeile 34/35) folgende neue Funktion einfügen:

```python
def _default_embed_src() -> Path:
    """Locate the embed/ viewer sources copied into share bundles — frozen-aware.

    In a PyInstaller bundle, resolve against `sys._MEIPASS` (where build_app.sh
    stages `embed/`); otherwise use the monorepo-relative path (config.py →
    autosplat → src → pipeline → repo root → embed).
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "embed"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[3] / "embed"
```

Dann die `ShareConfig`-Klasse (Zeilen 385-397) ändern von:

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

zu:

```python
class ShareConfig(BaseModel):
    """Web-export share bundles: compress + self-contained embed-viewer package."""

    base_url: str = Field(
        default="",
        description="Public base URL of your splat host, e.g. 'https://splat.jkaindl.de'. "
        "Empty → the UI shows a host-agnostic link template instead.",
    )
    embed_src_path: Path = Field(
        default_factory=_default_embed_src,
        description="Path to the embed/ viewer sources copied into each share "
        "bundle. Frozen-app aware (resolves inside the DMG bundle when "
        "packaged); override only if your embed/ checkout lives elsewhere.",
    )
```

- [ ] **Step 4: `default.toml` anpassen**

In `pipeline/config/default.toml` den `[share]`-Block (Zeilen 119-124) ändern von:

```toml
[share]
# WebUI web-export share bundles. base_url is your public splat host; empty
# shows a host-agnostic link template. viewer_src_path is copied into each
# self-contained bundle (relative paths resolve against the working directory).
base_url = ""
viewer_src_path = "../viewer"
```

zu:

```toml
[share]
# WebUI web-export share bundles. base_url is your public splat host; empty
# shows a host-agnostic link template. embed_src_path is NOT set here — it
# defaults to the monorepo's embed/ viewer sources (frozen-app aware, see
# config.py's _default_embed_src()). Only set it if your embed/ checkout
# lives somewhere unusual.
base_url = ""
```

- [ ] **Step 5: Test laufen lassen — muss bestehen**

Run: `cd pipeline && uv run pytest tests/test_config.py -q`
Expected: PASS (alle Tests in der Datei, inkl. der geänderten)

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/autosplat/config.py pipeline/config/default.toml pipeline/tests/test_config.py
git commit -m "feat(pipeline): frozen-aware embed_src_path config (replaces viewer_src_path)"
```

---

### Task 2: `share.py` — Embed-Allowlist, kein Redirect mehr, Link mit `?src=`

**Files:**
- Modify: `pipeline/src/autosplat/webui/share.py`
- Modify: `pipeline/tests/webui/test_share.py`

**Interfaces:**
- Consumes: —
- Produces: `assemble_bundle(sog_path, embed_src, share_dir, token) → BundlePaths`
  (Parametername `viewer_src` → `embed_src`); `share_link(base_url, token) → str | None`
  gibt jetzt `{base_url}/{token}/?src=c/scene.sog` zurück. Beide konsumiert von
  Task 3 (`share_runner.py`).

- [ ] **Step 1: Failing Test schreiben**

`pipeline/tests/webui/test_share.py` (vollständige neue Datei):

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

import zipfile
from pathlib import Path

from autosplat.webui.share import BundlePaths, assemble_bundle, make_share_token, share_link


def _fake_embed(root: Path) -> Path:
    e = root / "embed"
    (e / "js").mkdir(parents=True)
    (e / "css").mkdir()
    (e / "vendor").mkdir()
    (e / "tests").mkdir()
    (e / "index.html").write_text("<html>embed</html>")
    (e / "js" / "main.js").write_text("// main")
    (e / "css" / "embed.css").write_text("/* css */")
    (e / "vendor" / "playcanvas.mjs").write_bytes(b"ENGINE" * 100)
    (e / "tests" / "t.mjs").write_text("// test")  # must NOT be copied
    (e / "AGENTS.md").write_text("# agents")  # must NOT be copied
    return e


def test_assemble_bundle_builds_self_contained_tree(tmp_path: Path) -> None:
    embed = _fake_embed(tmp_path)
    sog = tmp_path / "scene.sog"
    sog.write_bytes(b"SPLAT" * 1000)
    share_dir = tmp_path / "cap" / "share"

    paths = assemble_bundle(sog, embed, share_dir, "lgs-pv-aaaaaaaaaa")

    assert isinstance(paths, BundlePaths)
    folder = paths.folder
    assert folder == share_dir / "lgs-pv-aaaaaaaaaa"
    # embed viewer runtime copied — index.html is the original, no redirect written
    assert (folder / "index.html").read_text() == "<html>embed</html>"
    assert (folder / "js" / "main.js").exists()
    assert (folder / "css" / "embed.css").exists()
    assert (folder / "vendor" / "playcanvas.mjs").exists()
    # client splat placed under c/
    assert (folder / "c" / "scene.sog").read_bytes() == b"SPLAT" * 1000
    # allowlist: tests dir and AGENTS.md excluded
    assert not (folder / "tests").exists()
    assert not (folder / "AGENTS.md").exists()
    # zip mirrors the folder
    assert paths.zip_path == share_dir / "lgs-pv-aaaaaaaaaa.zip"
    with zipfile.ZipFile(paths.zip_path) as zf:
        names = zf.namelist()
        assert any(n.endswith("c/scene.sog") for n in names)
        assert any(n.endswith("index.html") for n in names)


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
    assert share_link("https://splat.jkaindl.de/", "abc") == (
        "https://splat.jkaindl.de/abc/?src=c/scene.sog"
    )


def test_share_link_none_when_base_url_empty() -> None:
    assert share_link("", "abc") is None
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `cd pipeline && uv run pytest tests/webui/test_share.py -q`
Expected: FAIL — Assertions gegen `index.html`/`vendor` schlagen fehl (aktueller
Code kopiert noch `viewer.html`/`icons`/etc. und schreibt eine Redirect-`index.html`);
`share_link`-Test schlägt fehl (kein `?src=`-Suffix).

- [ ] **Step 3: `share.py` implementieren**

`pipeline/src/autosplat/webui/share.py` (vollständige neue Datei):

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Assemble a self-contained, self-hostable share bundle from a compressed splat.

A bundle is a folder named by an unguessable token containing a copy of the
embed viewer runtime plus the client's `.sog` at `c/scene.sog`. `embed/index.html`
is itself the entry point (`?src=c/scene.sog`), so no redirect file is written.
"Unlisted" = the token is unguessable; this is not access control.
"""

from __future__ import annotations

import re
import secrets
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
    """Full ``{base_url}/{token}/?src=c/scene.sog`` link, or None when base_url is unset.

    embed/index.html is the bundle's entry point and needs the ``src`` query
    param to load the scene (no redirect file is written into the bundle).
    """
    if not base_url.strip():
        return None
    return f"{base_url.rstrip('/')}/{token}/?src=c/scene.sog"


# Top-level embed entries copied into a bundle. Allowlist (not denylist) so a
# future stray file in embed/ never leaks into a client's public bundle.
_EMBED_ALLOWLIST = (
    "index.html",
    "js",
    "css",
    "vendor",
)


@dataclass
class BundlePaths:
    folder: Path
    zip_path: Path


def assemble_bundle(
    sog_path: Path, embed_src: Path, share_dir: Path, token: str
) -> BundlePaths:
    """Build ``share_dir/<token>/`` (self-contained embed viewer + splat) and its zip.

    Raises FileNotFoundError if ``embed_src`` is missing its ``index.html``
    (surfaces the monorepo-source / frozen-bundle requirement clearly).
    """
    if not (embed_src / "index.html").exists():
        raise FileNotFoundError(f"embed viewer sources not found at {embed_src}")

    folder = share_dir / token
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    for name in _EMBED_ALLOWLIST:
        src = embed_src / name
        if not src.exists():
            continue  # optional entries tolerated
        dest = folder / name
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)

    c_dir = folder / "c"
    c_dir.mkdir()
    shutil.copy2(sog_path, c_dir / "scene.sog")

    zip_path = share_dir / f"{token}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            zf.write(path, path.relative_to(share_dir))

    return BundlePaths(folder=folder, zip_path=zip_path)
```

- [ ] **Step 4: Test laufen lassen — muss bestehen**

Run: `cd pipeline && uv run pytest tests/webui/test_share.py -q`
Expected: PASS (6 Tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/src/autosplat/webui/share.py pipeline/tests/webui/test_share.py
git commit -m "feat(pipeline): share bundles use embed/ allowlist, index.html is the entry point"
```

---

### Task 3: `share_runner.py` — `embed_src_path` konsumieren + abhängige Tests

**Files:**
- Modify: `pipeline/src/autosplat/webui/share_runner.py`
- Modify: `pipeline/tests/webui/test_share_runner.py`
- Modify: `pipeline/tests/webui/test_share_routes.py`

**Interfaces:**
- Consumes: `Config.share.embed_src_path` (Task 1), `assemble_bundle`/`share_link`
  (Task 2).
- Produces: unverändertes `ShareJobRunner`-Public-API (`start`, `get`,
  `ShareJob`-Felder) — nur die interne Pfad-Auflösung ändert sich.

- [ ] **Step 1: Failing Tests schreiben**

`pipeline/tests/webui/test_share_runner.py` (vollständige neue Datei):

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

import time
from pathlib import Path

from autosplat.compress import CompressResult
from autosplat.config import load_config
from autosplat.webui.share_runner import ShareJobRunner


def _fake_embed(root: Path) -> Path:
    e = root / "embed"
    e.mkdir()
    (e / "index.html").write_text("<html>e</html>")
    return e


def _wait(job, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(0.02)


def test_share_job_compresses_and_bundles(tmp_path: Path) -> None:
    embed = _fake_embed(tmp_path)
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
    cfg.share.embed_src_path = embed
    runner = ShareJobRunner(cfg, compressor=fake_compress)

    job = runner.start("2026-07-10_lgs", capture_dir)
    _wait(job)

    assert job.status == "done"
    assert job.token and job.token.startswith("lgs-")
    assert job.zip_path is not None and job.zip_path.exists()
    assert (capture_dir / "share" / job.token / "c" / "scene.sog").exists()
    assert job.output_bytes == 300 and job.input_bytes == 15000
    assert job.link == f"https://splat.example/{job.token}/?src=c/scene.sog"


def test_share_job_fails_without_ply(tmp_path: Path) -> None:
    embed = _fake_embed(tmp_path)
    capture_dir = tmp_path / "2026-07-10_empty"
    capture_dir.mkdir()
    cfg = load_config(include_xdg=False)
    cfg.share.embed_src_path = embed
    runner = ShareJobRunner(cfg)

    job = runner.start("2026-07-10_empty", capture_dir)
    _wait(job)

    assert job.status == "failed"
    assert job.error and "scene.ply" in job.error
```

`pipeline/tests/webui/test_share_routes.py` (vollständige neue Datei):

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

import time
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from autosplat.compress import CompressResult
from autosplat.webui.share_runner import ShareJobRunner


def _fake_embed(root: Path) -> Path:
    e = root / "embed"
    e.mkdir()
    (e / "index.html").write_text("<html>e</html>")
    return e


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


def test_post_share_starts_job_and_partial_shows_link(app: FastAPI, tmp_path: Path) -> None:
    _install(app, tmp_path)
    with TestClient(app) as client:
        r = client.post("/captures/2026-07-10_lgs/share", follow_redirects=False)
        assert r.status_code == 303
        # let the background thread finish
        body = ""
        for _ in range(150):
            body = client.get("/partials/capture/2026-07-10_lgs/share").text
            if "https://splat.example/" in body:
                break
            time.sleep(0.02)
        assert "https://splat.example/lgs-" in body
        assert "share/lgs-" in body and ".zip" in body


def test_detail_page_shows_share_card_for_done_capture(app: FastAPI, tmp_path: Path) -> None:
    _install(app, tmp_path)
    with TestClient(app) as client:
        body = client.get("/captures/2026-07-10_lgs").text
    assert "Create share bundle" in body
    assert "anyone with this link" in body.lower()


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

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `cd pipeline && uv run pytest tests/webui/test_share_runner.py tests/webui/test_share_routes.py -q`
Expected: FAIL — `ShareConfig` hat nach Task 1 bereits `embed_src_path` statt
`viewer_src_path`; `share_runner.py`s noch unveränderte `_resolve_viewer_src()`
liest intern weiterhin `self._cfg.share.viewer_src_path`, was
`AttributeError: 'ShareConfig' object has no attribute 'viewer_src_path'` wirft.

- [ ] **Step 3: `share_runner.py` implementieren**

`pipeline/src/autosplat/webui/share_runner.py` (vollständige neue Datei):

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Background runner for share-bundle jobs.

Kept separate from the pipeline JobRunner: a share job must NOT flip the
capture's status to 'running' — the capture stays 'done' and only the share
card reflects bundle progress.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from autosplat.compress import CompressResult, compress_ply
from autosplat.config import Config
from autosplat.logging import get_logger
from autosplat.webui.share import assemble_bundle, make_share_token, share_link

logger = get_logger(__name__)

ShareStatus = Literal["running", "done", "failed"]

Compressor = Callable[..., CompressResult]


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
    def __init__(self, cfg: Config, compressor: Compressor = compress_ply) -> None:
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
            target=self._run,
            args=(job, capture_dir),
            daemon=True,
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
                ply,
                capture_dir / "share" / "_tmp",
                fmt="sog",
                quality=self._cfg.compress.quality,
            )
            token = make_share_token(job.capture_id)
            embed_src = self._resolve_embed_src()
            paths = assemble_bundle(
                result.output_path, embed_src, capture_dir / "share", token
            )

            job.token = token
            job.zip_path = paths.zip_path
            job.output_bytes = result.output_bytes
            job.input_bytes = result.input_bytes
            job.link = share_link(self._cfg.share.base_url, token)
            job.status = "done"
            logger.info("share.done", capture_id=job.capture_id, token=token)
        except Exception as e:  # surfaced on the job, not raised
            job.status = "failed"
            job.error = str(e)
            logger.error("share.failed", capture_id=job.capture_id, error=str(e))

    def _resolve_embed_src(self) -> Path:
        p = self._cfg.share.embed_src_path
        return p if p.is_absolute() else (Path.cwd() / p)
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `cd pipeline && uv run pytest tests/webui/test_share_runner.py tests/webui/test_share_routes.py -q`
Expected: PASS (5 Tests: 2 in test_share_runner.py + 3 in test_share_routes.py)

- [ ] **Step 5: Regression — komplette Pipeline-Testsuite**

Run: `cd pipeline && uv run pytest -q`
Expected: alle Tests PASS (keine anderen Module referenzieren `viewer_src_path`
mehr, siehe Task-Vorbedingung — verifiziert vor Plan-Erstellung)

- [ ] **Step 6: Commit**

```bash
git add pipeline/src/autosplat/webui/share_runner.py pipeline/tests/webui/test_share_runner.py pipeline/tests/webui/test_share_routes.py
git commit -m "feat(pipeline): share_runner resolves embed_src_path"
```

---

### Task 4: `AutoSplat.spec` — `embed/` als PyInstaller-Daten bündeln

**Files:**
- Modify: `pipeline/packaging/AutoSplat.spec`

**Interfaces:**
- Consumes: `embed/index.html`, `embed/css`, `embed/js`, `embed/vendor` (bereits
  vorhanden aus der embed-Viewer-Arbeit).
- Produces: `sys._MEIPASS/embed/{index.html,css,js,vendor}` zur Laufzeit in
  einem zukünftigen PyInstaller-Build — konsumiert von `_default_embed_src()`
  (Task 1) im Frozen-Zweig.

- [ ] **Step 1: `datas`-Liste erweitern**

In `pipeline/packaging/AutoSplat.spec` den `datas`-Block (Zeilen 30-39) ändern von:

```python
# Data files: (source, dest-in-bundle). The webui resolves templates/static via
# sys._MEIPASS/autosplat/webui when frozen; config.py reads
# sys._MEIPASS/config/default.toml; desktop.py finds scripts/ for first-run setup.
datas = [
    (_p("src/autosplat/webui/templates"), "autosplat/webui/templates"),
    (_p("src/autosplat/webui/static"), "autosplat/webui/static"),
    (_p("config/default.toml"), "config"),
    (_p("scripts/install_deps.sh"), "scripts"),
    (_p("scripts/fetch_brush.sh"), "scripts"),
]
```

zu:

```python
# Data files: (source, dest-in-bundle). The webui resolves templates/static via
# sys._MEIPASS/autosplat/webui when frozen; config.py reads
# sys._MEIPASS/config/default.toml; desktop.py finds scripts/ for first-run
# setup; share.py's ShareJobRunner reads sys._MEIPASS/embed for share-bundle
# assembly (see config.py's _default_embed_src()). embed/ is bundled as an
# explicit allowlist (not the whole folder) so tests/ and AGENTS.md never end
# up inside the .app, mirroring share.py's own _EMBED_ALLOWLIST.
datas = [
    (_p("src/autosplat/webui/templates"), "autosplat/webui/templates"),
    (_p("src/autosplat/webui/static"), "autosplat/webui/static"),
    (_p("config/default.toml"), "config"),
    (_p("scripts/install_deps.sh"), "scripts"),
    (_p("scripts/fetch_brush.sh"), "scripts"),
    (_p("..", "embed", "index.html"), "embed"),
    (_p("..", "embed", "css"), "embed/css"),
    (_p("..", "embed", "js"), "embed/js"),
    (_p("..", "embed", "vendor"), "embed/vendor"),
]
```

- [ ] **Step 2: Statische Verifikation (kein PyInstaller-Build in diesem Task)**

Run:

```bash
cd pipeline
python3 -c "
import ast
with open('packaging/AutoSplat.spec') as f:
    ast.parse(f.read())
print('AutoSplat.spec: syntax OK')
"
python3 -c "
from pathlib import Path
root = Path('..').resolve()
for p in ['embed/index.html', 'embed/css', 'embed/js', 'embed/vendor']:
    assert (root / p).exists(), f'missing: {p}'
print('all embed/ datas sources exist')
"
```

Expected: `AutoSplat.spec: syntax OK` und `all embed/ datas sources exist`
(ein echter `build_app.sh`-Lauf inkl. Codesigning ist bewusst außerhalb des
Scopes dieses Plans, siehe Spec).

- [ ] **Step 3: Regression — komplette Pipeline-Testsuite**

Run: `cd pipeline && uv run pytest -q`
Expected: alle Tests PASS (dieser Task ändert keinen Python-Laufzeitcode)

- [ ] **Step 4: Commit**

```bash
git add pipeline/packaging/AutoSplat.spec
git commit -m "build(pipeline): bundle embed/ into the PyInstaller .app"
```

---

### Task 5: Doku

**Files:**
- Modify: `pipeline/CHANGELOG.md`
- Modify: `pipeline/docs/superpowers/specs/2026-07-14-embed-viewer-design.md`

**Interfaces:**
- Consumes: alles aus Tasks 1–4 (beschreibt es nur).
- Produces: —

- [ ] **Step 1: `pipeline/CHANGELOG.md` — `[Unreleased]` füllen**

Die leere `## [Unreleased]`-Sektion (Zeilen 10-12) ersetzen durch:

```markdown
## [Unreleased]

### Changed

- **Share bundles now use the `embed/` viewer runtime, not `viewer/`.**
  Bundles are genuinely zero-external (PlayCanvas vendored, no CDN request)
  instead of self-hosted-for-code-but-CDN-for-engine. Fixes the share-bundle
  feature being non-functional in the packaged DMG app (`viewer/` was never
  bundled by PyInstaller and the old `viewer_src_path` had no frozen-app
  path resolution — `[share].embed_src_path` now resolves correctly in both
  the dev checkout and the frozen `.app`).

---
```

- [ ] **Step 2: `2026-07-14-embed-viewer-design.md` — Follow-up als erledigt markieren**

Zeile 25 (Entscheidungstabelle) ändern von:

```markdown
| Share-Bundle-Umstellung | **Folge-Slice**, nicht Teil dieser Arbeit |
```

zu:

```markdown
| Share-Bundle-Umstellung | **Folge-Slice**, nicht Teil dieser Arbeit — umgesetzt in `2026-07-15-share-bundle-embed-migration-design.md` |
```

Zeile 105 (Bewusst-außerhalb-des-Scopes-Liste) ändern von:

```markdown
- Share-Bundle-Umstellung der Pipeline auf `embed/` als Bundle-Runtime
  (Folge-Slice; macht Bundles dann echt zero-external).
```

zu:

```markdown
- ~~Share-Bundle-Umstellung der Pipeline auf `embed/` als Bundle-Runtime~~ —
  umgesetzt, siehe `2026-07-15-share-bundle-embed-migration-design.md`.
```

- [ ] **Step 3: Regression + Commit**

Run: `cd pipeline && uv run pytest -q`
Expected: alle Tests PASS (Doku-Änderungen brechen nichts)

```bash
git add pipeline/CHANGELOG.md pipeline/docs/superpowers/specs/2026-07-14-embed-viewer-design.md
git commit -m "docs(pipeline): share-bundle embed/ migration changelog + scope update"
```

---

### Task 6: Vollverifikation + manueller Smoke

**Files:**
- Modify: keine (nur Verifikation)

**Interfaces:**
- Consumes: alles.
- Produces: verifizierter Endzustand.

- [ ] **Step 1: Volle Testsuite**

```bash
cd /Users/Shared/code/autosplat/pipeline && uv run pytest -q
cd /Users/Shared/code/autosplat/embed && ./tests/run.sh
```

Expected: beide komplett PASS (`embed/` selbst wurde in diesem Plan nicht
verändert — seine Tests müssen unverändert grün sein).

- [ ] **Step 2: `viewer_src_path`-Referenz-Check (Regressions-Grep)**

```bash
grep -rn "viewer_src_path" pipeline/ --include="*.py" --include="*.toml" || echo "OK: keine Referenzen mehr"
```

Expected: `OK: keine Referenzen mehr` (alle Stellen auf `embed_src_path`
migriert).

- [ ] **Step 3: Manueller Smoke (WebUI im Dev-Checkout)**

```bash
cd /Users/Shared/code/autosplat/pipeline && uv run autosplat webui
```

Dann im Browser (`http://localhost:8000` o. ä., siehe Terminal-Ausgabe):
1. Eine bestehende, fertige Capture öffnen.
2. „Create share bundle" klicken, Job abwarten.
3. Im Dateisystem prüfen: `<capture>/share/<token>/` enthält `index.html`,
   `js/`, `css/`, `vendor/`, `c/scene.sog` — **kein** `viewer.html`, **kein**
   `tests/`-Ordner.
4. `cd <capture>/share/<token> && python3 -m http.server 8199`, im Browser
   `http://localhost:8199/` öffnen (ohne Query — sollte die Hinweis-Karte
   „No scene specified" zeigen, da `index.html` jetzt der rohe Embed-Entry-
   Point ist) und dann `http://localhost:8199/?src=c/scene.sog` (Szene lädt,
   Netzwerk-Tab zeigt ausschließlich `localhost`-Requests).
5. Den in der WebUI angezeigten Share-Link kopieren — er muss auf
   `?src=c/scene.sog` enden.

- [ ] **Step 4: Abschluss**

`git log --oneline` zeigt die 5 Task-Commits; Arbeitsbaum sauber. Kein
DMG-Rebuild in dieser Session (bleibt expliziter Folgeschritt, siehe Spec).
