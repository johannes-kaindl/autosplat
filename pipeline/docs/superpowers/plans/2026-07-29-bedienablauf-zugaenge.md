# Bedienablauf & Zugänge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `AutoSplat.app` the door where every step from import to publication is
clickable, give the CLI the two publishing steps it lacks, and give each of the three
viewers one named role and one working entrance.

**Architecture:** One resolver (`resources.py`) replaces every ad-hoc lookup of a bundled
asset, so SuperSplat and `viewer/` can join `embed/` inside the app bundle. Two new
read-mostly pages (`/system`, `/storage`) surface information the code already computes
and throws away. Two extractions — the migrate-storage planner out of `cli.py`, the
share-bundle body out of `ShareJobRunner` — turn CLI-only and GUI-only logic into shared
layers that both surfaces call.

**Tech Stack:** Python 3.12 · uv · FastAPI + Jinja2 + htmx · Typer · pytest ·
PyInstaller · vanilla ES modules (viewer) · node:test (viewer tests)

## Global Constraints

- Reference spec: `pipeline/docs/superpowers/specs/2026-07-29-bedienablauf-zugaenge-design.md`
- Every new Python file starts with `# SPDX-License-Identifier: AGPL-3.0-or-later`
- Every new Python module uses `from __future__ import annotations`
- `cd pipeline && uv run pytest -q` must pass before every commit (597 tests green at
  `2282cf4`; the count only grows)
- `cd pipeline && uv run mypy src` (strict) and `uv run ruff check src tests` must be clean
- Viewer changes: `cd viewer && ./tests/run.sh unit` must pass
- **No new config keys.** `share.embed_src_path` and `viewer.supersplat_dist_path` keep
  their meaning; only their defaults change.
- **Never restate a protective predicate.** Deletion eligibility lives in
  `lifecycle.reclaimable_targets` / `lifecycle.protected_targets`; call them.
- **No test may name a real path under `$HOME`.** `tests/conftest.py` has a session-scoped
  autouse guard that fails the suite on violations — do not weaken it.
- Bundling uses an **allowlist**, never a denylist (precedent: `share.py:_EMBED_ALLOWLIST`)
- Commit style: conventional commits, English subject, scope `pipeline`/`viewer`/`docs`,
  and every commit message ends with
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- Work on a branch: `git checkout -b feat/bedienablauf-zugaenge` before Task 1

## File Structure

| File | Responsibility |
|---|---|
| `pipeline/src/autosplat/resources.py` *(new)* | Resolve a bundled resource dir (frozen bundle vs. repo checkout) and report which bundled viewers are present, with their charter role. Both the mount in `app.py` and the `/system` page read it — one place, so they cannot disagree. |
| `pipeline/src/autosplat/migration.py` *(new)* | Decide *what* migrate-storage would reclaim (pure planner) and execute a plan. No rendering. |
| `pipeline/src/autosplat/webui/routes/system.py` *(new)* | `/system` — render doctor results + bundled-resource status. |
| `pipeline/src/autosplat/webui/routes/storage.py` *(new)* | `/storage` — render a migration plan; POST runs the apply off-request as a `ReclaimJob`. |
| `pipeline/src/autosplat/webui/templates/partials/storage_status.html` *(new)* | Self-terminating htmx poll for a running reclaim sweep. |
| `pipeline/src/autosplat/webui/templates/system.html` *(new)* | Presentation for `/system`. |
| `pipeline/src/autosplat/webui/templates/storage.html` *(new)* | Presentation for `/storage`. |
| `pipeline/src/autosplat/config.py` | Loses `_default_embed_src`; both viewer paths default via `resources`. |
| `pipeline/src/autosplat/webui/app.py` | Mounts `/supersplat` and `/viewer` via `resources`, records what is missing. |
| `pipeline/src/autosplat/webui/share_runner.py` | Gains `build_share_bundle()` (sync, raises) + `UnreviewedCapture`; `_run` becomes thin. |
| `pipeline/src/autosplat/lifecycle.py` | Gains `write_review_marker()` — the marker writer both surfaces share. |
| `pipeline/src/autosplat/cli.py` | `migrate-storage` renders a plan it no longer computes; gains `review` + `share`. |
| `pipeline/src/autosplat/webui/routes/captures.py` | Gains `/{id}/walk`; review + share routes call the shared layers. |
| `pipeline/packaging/AutoSplat.spec` | Bundles `supersplat` (no `*.map`) and `viewer` (allowlist). |
| `pipeline/scripts/build_app.sh` | Preflight: refuse to build without a SuperSplat dist. |
| `viewer/viewer.html` | Importmap points at `./vendor/playcanvas.mjs`. |
| `viewer/vendor/playcanvas.mjs` *(new)* | Byte-identical copy of `embed/vendor/playcanvas.mjs`. |

---

### Task 1: `resources.py` — one resolver for bundled assets

**Files:**
- Create: `pipeline/src/autosplat/resources.py`
- Create: `pipeline/tests/test_resources.py`
- Modify: `pipeline/src/autosplat/config.py:37-47` (delete `_default_embed_src`), `:248-251` (`supersplat_dist_path` default)
- Modify: `pipeline/src/autosplat/webui/share_runner.py:113-115` (`_resolve_embed_src`)

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `resources.REPO_ROOT: Path`
  - `resources.bundled_path(name: str) -> Path`
  - `resources.ResourceStatus` — frozen dataclass: `name: str`, `role: str`, `path: Path`,
    `present: bool`
  - `resources.viewer_status(cfg: Config | None) -> list[ResourceStatus]`
  - Tasks 2, 4, 7 and 8 rely on these.

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_resources.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from autosplat import resources


def test_repo_checkout_resolves_relative_to_repo_root() -> None:
    # resources.py → autosplat → src → pipeline → repo root
    assert resources.bundled_path("embed") == resources.REPO_ROOT / "embed"
    assert (resources.REPO_ROOT / "embed" / "index.html").is_file()


def test_frozen_bundle_resolves_against_meipass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resources.bundled_path("supersplat") == tmp_path / "supersplat"


def test_name_must_be_a_single_segment() -> None:
    # A resource "name" is a bundle top-level dir, never a path — silently
    # accepting "../.." would resolve outside the bundle.
    with pytest.raises(ValueError):
        resources.bundled_path("../etc")


def test_viewer_status_names_all_three_roles() -> None:
    from autosplat.config import load_config

    statuses = resources.viewer_status(load_config(include_xdg=False))

    assert [s.name for s in statuses] == ["supersplat", "embed", "viewer"]
    roles = " ".join(s.role for s in statuses)
    assert "clean up" in roles and "share" in roles and "walk" in roles


def test_viewer_status_reports_absence(tmp_path: Path) -> None:
    """The defect this exists for: a missing viewer used to be invisible."""
    from autosplat.config import load_config

    cfg = load_config(include_xdg=False)
    cfg.viewer.supersplat_dist_path = tmp_path / "nope"

    supersplat = next(s for s in resources.viewer_status(cfg) if s.name == "supersplat")
    assert supersplat.present is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/test_resources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autosplat.resources'`

- [ ] **Step 3: Write minimal implementation**

Create `pipeline/src/autosplat/resources.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Resolution of resource trees bundled into the frozen app.

One resolver for every asset directory that ships inside AutoSplat.app
(`embed/`, `supersplat/`, `viewer/`). Before this module each caller rolled
its own: `config.py` checked `sys.frozen`, while `webui/app.py` resolved the
SuperSplat dist against `Path.cwd()` — which is meaningless for a Finder
launch, so the shipped app silently had no review viewer at all.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autosplat.config import Config

# resources.py → autosplat → src → pipeline → repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


def bundled_path(name: str) -> Path:
    """Directory of the bundled resource `name`.

    Frozen (PyInstaller) → `sys._MEIPASS/<name>`, where AutoSplat.spec stages
    it. Otherwise the monorepo checkout's `<repo root>/<name>`.

    `name` is a single path segment by contract; anything else would let a
    caller escape the bundle root.
    """
    if "/" in name or name in ("", ".", ".."):
        raise ValueError(f"resource name must be a single path segment, got {name!r}")
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / name  # type: ignore[attr-defined]
    return REPO_ROOT / name


@dataclass(frozen=True)
class ResourceStatus:
    """A bundled viewer, its one job, and whether it is actually there."""

    name: str
    role: str
    path: Path
    present: bool


# The charter of viewer roles (AGENTS.md), as data. The three overlap only on
# plain viewing; each entry's `role` is why it exists. A fourth entry is a
# design decision, not a detail.
_VIEWER_ROLES: tuple[tuple[str, str, str], ...] = (
    ("supersplat", "clean up — the review-gate editor", "index.html"),
    ("embed", "share — the runtime inside share bundles", "index.html"),
    ("viewer", "walk — first-person walking mode", "viewer.html"),
)


def viewer_status(cfg: Config | None) -> list[ResourceStatus]:
    """Each bundled viewer's role and whether its sentinel file is present.

    Single source of truth for two callers that must not disagree: `webui/app.py`
    decides what to mount, `/system` reports what is missing. Config overrides
    win where they exist, so a locally built SuperSplat dist is honoured.
    """
    statuses = []
    for name, role, sentinel in _VIEWER_ROLES:
        root = _root_for(cfg, name)
        statuses.append(
            ResourceStatus(name=name, role=role, path=root, present=(root / sentinel).is_file())
        )
    return statuses


def _root_for(cfg: Config | None, name: str) -> Path:
    """Where a bundled viewer lives — an explicit config override wins."""
    if cfg is not None:
        if name == "supersplat":
            return cfg.viewer.supersplat_dist_path
        if name == "embed":
            return cfg.share.embed_src_path
    return bundled_path(name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd pipeline && uv run pytest tests/test_resources.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Point the three existing callers at it**

In `pipeline/src/autosplat/config.py`, delete `_default_embed_src` (lines 37-47) and
change the two fields:

```python
# ShareConfig.embed_src_path
    embed_src_path: Path = Field(
        default_factory=lambda: resources.bundled_path("embed"),
        description="Path to the embed/ viewer sources copied into each share "
        "bundle. Resolved via resources.bundled_path (inside the DMG bundle "
        "when packaged); override only if your embed/ checkout lives elsewhere.",
    )

# ViewerConfig.supersplat_dist_path
    supersplat_dist_path: Path = Field(
        default_factory=lambda: resources.bundled_path("supersplat"),
        description="Path to the SuperSplat viewer/editor that drives the "
        "review gate. Resolved via resources.bundled_path; override to point "
        "at a locally built target/supersplat/dist instead.",
    )
```

Add `from autosplat import resources` to the imports. Drop the now-unused `import sys`
only if `_packaged_default_config` no longer needs it — it does, so keep it.

In `pipeline/src/autosplat/webui/share_runner.py` replace `_resolve_embed_src`:

```python
    def _resolve_embed_src(self) -> Path:
        p = self._cfg.share.embed_src_path
        return p if p.is_absolute() else (resources.REPO_ROOT / p)
```

with `from autosplat import resources` added to its imports. A relative override now
resolves against the repo root rather than whatever directory the process happens to be
in — the same class of bug as the SuperSplat one, just with a currently-absolute default
hiding it.

- [ ] **Step 6: Add a regression test for the default that was broken**

Append to `pipeline/tests/test_resources.py`:

```python
def test_supersplat_default_does_not_depend_on_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The shipped app had no review viewer because this default was
    cwd-relative and a Finder launch has no meaningful cwd."""
    from autosplat.config import load_config

    monkeypatch.chdir(tmp_path)
    cfg = load_config(include_xdg=False)
    assert cfg.viewer.supersplat_dist_path.is_absolute()
    assert cfg.share.embed_src_path.is_absolute()
```

- [ ] **Step 7: Run the full suite**

Run: `cd pipeline && uv run pytest -q && uv run mypy src && uv run ruff check src tests`
Expected: all pass. `tests/test_config.py` and `tests/webui/test_share_runner.py` exercise
these fields — if either asserted the old `target/supersplat/dist` default, update the
assertion to the resolver's value (do not reintroduce the cwd-relative default).

- [ ] **Step 8: Commit**

```bash
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/resources.py pipeline/tests/test_resources.py \
        pipeline/src/autosplat/config.py pipeline/src/autosplat/webui/share_runner.py
git commit -m "feat(pipeline): resolve bundled assets through one resolver

Replaces config.py's frozen-aware _default_embed_src and webui/app.py's
cwd-relative SuperSplat lookup with resources.bundled_path. The cwd-relative
default is why /Applications/AutoSplat.app has no review viewer: a Finder
launch has no meaningful cwd, so the dist never resolved and the mount was
skipped without a word.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Bundle SuperSplat + `viewer/` into the app

**Files:**
- Modify: `pipeline/packaging/AutoSplat.spec:30-47` (`datas`)
- Modify: `pipeline/scripts/build_app.sh:38-40` (preflight block)
- Create: `pipeline/tests/test_packaging.py`

**Interfaces:**
- Consumes: `resources.bundled_path` (Task 1) — the spec stages trees at the top level
  named exactly `embed`, `supersplat`, `viewer`, which is what `bundled_path` expects.
- Produces: bundle layout `<bundle>/supersplat/...`, `<bundle>/viewer/...`. Task 7 mounts
  them.

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_packaging.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The PyInstaller spec is executable Python, so its data-file plan is
testable without running a 10-minute build. These tests guard the two rules
the plan must keep: allowlist only, and no source maps."""

from __future__ import annotations

from pathlib import Path

import pytest

from autosplat import resources

SPEC = resources.REPO_ROOT / "pipeline" / "packaging" / "AutoSplat.spec"
DIST = resources.REPO_ROOT / "pipeline" / "target" / "supersplat" / "dist"

# The SuperSplat dist is built by scripts/setup_supersplat.sh, not checked in,
# so a fresh clone has none. Skipping keeps the suite honest there; build_app.sh
# is what refuses to *ship* without it.
needs_dist = pytest.mark.skipif(
    not (DIST / "index.html").is_file(),
    reason="SuperSplat dist not built — run scripts/setup_supersplat.sh",
)


def _spec_datas() -> list[tuple[str, str]]:
    """Execute the spec's `datas` construction in isolation.

    The spec references PyInstaller globals (SPECPATH, Analysis, ...) that
    only exist under pyinstaller, so we exec only up to the datas list by
    providing SPECPATH and stopping at the first PyInstaller call.
    """
    source = SPEC.read_text(encoding="utf-8")
    head = source.split("# uvicorn[standard]")[0]
    namespace: dict[str, object] = {"SPECPATH": str(SPEC.parent)}
    exec(compile(head, str(SPEC), "exec"), namespace)  # noqa: S102
    datas = namespace["datas"]
    assert isinstance(datas, list)
    return [(str(src), str(dest)) for src, dest in datas]


@needs_dist
def test_supersplat_is_bundled_without_source_maps() -> None:
    datas = _spec_datas()
    supersplat = [d for d in datas if d[1].startswith("supersplat")]
    assert supersplat, "SuperSplat dist is not bundled — the app's review gate needs it"
    assert not [d for d in supersplat if d[0].endswith(".map")]


def test_viewer_is_bundled_by_allowlist() -> None:
    datas = _spec_datas()
    dests = [d[1] for d in datas]
    assert "viewer" in dests or any(x.startswith("viewer/") for x in dests)
    sources = [Path(d[0]).name for d in datas if d[1].startswith("viewer")]
    # The 17 MB marketing assets, the landing page and its script stay out.
    assert "assets" not in sources
    assert "index.html" not in sources
    assert "landing.js" not in sources


def test_embed_is_still_bundled() -> None:
    """Share bundles are assembled from it — a regression here breaks sharing."""
    datas = _spec_datas()
    assert [d for d in datas if d[1].startswith("embed")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/test_packaging.py -v`
Expected: `test_supersplat_is_bundled_without_source_maps` and
`test_viewer_is_bundled_by_allowlist` FAIL; `test_embed_is_still_bundled` PASSES.

- [ ] **Step 3: Extend the spec's `datas`**

In `pipeline/packaging/AutoSplat.spec`, after the existing `datas` list, add:

```python
# SuperSplat drives the v1.15.0 review gate. It is a built artifact
# (scripts/setup_supersplat.sh), not a checked-in tree, so build_app.sh
# refuses to build without it rather than shipping a bundle whose review
# gate silently degrades to blind "confirm unchanged" — which is exactly
# what every DMG up to v1.16.0 did. Source maps are excluded: 23 MB → 9,5 MB.
def _tree(src_root, dest_root, *, skip_suffixes=()):
    """(source, dest) pairs for every file under `src_root`, recursively."""
    pairs = []
    for path in sorted(Path(src_root).rglob("*")):
        if not path.is_file() or path.suffix in skip_suffixes:
            continue
        rel_parent = path.parent.relative_to(src_root)
        pairs.append((str(path), os.path.join(dest_root, str(rel_parent))))
    return pairs


datas += _tree(_p("target/supersplat/dist"), "supersplat", skip_suffixes=(".map",))

# viewer/ carries the walking mode (walking.js, heightmap.js, collision/) that
# no other runtime has. Allowlist, mirroring share.py's _EMBED_ALLOWLIST:
# index.html + landing.js (the marketing landing page) and assets/ (17 MB of
# hero imagery) have no business inside the app. js/ is taken whole — app.js
# imports dropzone.js, so cherry-picking modules breaks the viewer to save
# kilobytes.
datas += [
    (_p("..", "viewer", "viewer.html"), "viewer"),
    (_p("..", "viewer", "js"), "viewer/js"),
    (_p("..", "viewer", "css"), "viewer/css"),
    (_p("..", "viewer", "icons"), "viewer/icons"),
    (_p("..", "viewer", "vendor"), "viewer/vendor"),
]
```

Add `from pathlib import Path` to the spec's imports (`os` is already imported).

Note: `viewer/vendor/` does not exist until Task 3. Run Task 3 before the first real
`build_app.sh` invocation; `_spec_datas()` does not touch the filesystem for the
explicitly-listed viewer entries, so the tests pass either way.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd pipeline && uv run pytest tests/test_packaging.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the build preflight**

In `pipeline/scripts/build_app.sh`, after the PyInstaller availability check (line ~40):

```bash
# A bundle without SuperSplat ships a review gate that can only be answered
# blind — v1.15.0 through v1.16.0 did exactly that. Fail the build instead.
readonly SUPERSPLAT_DIST="${REPO_ROOT}/target/supersplat/dist"
[[ -f "${SUPERSPLAT_DIST}/index.html" ]] \
  || fail "SuperSplat dist missing at ${SUPERSPLAT_DIST} — run scripts/setup_supersplat.sh"

# viewer/vendor holds the engine copy that makes walking mode work offline.
[[ -f "${REPO_ROOT}/../viewer/vendor/playcanvas.mjs" ]] \
  || fail "viewer/vendor/playcanvas.mjs missing — see viewer/vendor/README.md"
```

- [ ] **Step 6: Verify the preflight fires and the build still works**

Run: `cd pipeline && bash -n scripts/build_app.sh` (syntax) then
`cd pipeline && SUPERSPLAT_DIST_OVERRIDE=1 bash -c 'true'` — no override exists, so
verify manually instead:

```bash
cd /Users/Shared/code/autosplat/pipeline
mv target/supersplat/dist target/supersplat/dist.bak
./scripts/build_app.sh 2>&1 | tail -2   # expect: the SuperSplat fail message
mv target/supersplat/dist.bak target/supersplat/dist
```

Expected: the build aborts with `SuperSplat dist missing …`. Do **not** run the full build
yet — `viewer/vendor/` arrives in Task 3.

- [ ] **Step 7: Commit**

```bash
cd /Users/Shared/code/autosplat
git add pipeline/packaging/AutoSplat.spec pipeline/scripts/build_app.sh \
        pipeline/tests/test_packaging.py
git commit -m "feat(pipeline): bundle SuperSplat and the walking viewer into the app

SuperSplat (source maps stripped, 23 MB -> 9,5 MB) and an allowlisted
viewer/ join embed/ in the bundle, and build_app.sh now refuses to build
without either. Every DMG through v1.16.0 shipped a review gate with no
editor behind it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `viewer/` runs on the vendored engine

**Files:**
- Modify: `viewer/viewer.html:24-30` (importmap)
- Create: `viewer/vendor/playcanvas.mjs` (copy), `viewer/vendor/README.md`
- Create: `viewer/tests/unit/vendor.test.mjs`

**Interfaces:**
- Consumes: `embed/vendor/playcanvas.mjs` (existing, 3,6 MB)
- Produces: `viewer/vendor/playcanvas.mjs`, required by Task 2's preflight and Task 7's
  mount.

- [ ] **Step 1: Write the failing test**

Create `viewer/tests/unit/vendor.test.mjs`:

```javascript
// SPDX-License-Identifier: AGPL-3.0-or-later
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const VIEWER = join(HERE, '..', '..');
const REPO = join(VIEWER, '..');

test('viewer loads the engine from vendor/, not a CDN', () => {
  const html = readFileSync(join(VIEWER, 'viewer.html'), 'utf8');
  assert.match(html, /"playcanvas":\s*"\.\/vendor\/playcanvas\.mjs"/);
  assert.doesNotMatch(html, /cdn\.jsdelivr\.net/);
});

test('no allowlisted module specifier points at an external host', () => {
  // The app bundles these files and claims to be zero-external. That claim
  // was already wrong once (v1.14.0 share bundles), so it gets a gate.
  const files = ['viewer.html', 'js/app.js', 'js/viewer.js', 'js/walking.js'];
  for (const rel of files) {
    const text = readFileSync(join(VIEWER, rel), 'utf8');
    const specifiers = [...text.matchAll(/(?:from|import)\s+['"]([^'"]+)['"]/g)].map((m) => m[1]);
    for (const spec of specifiers) {
      assert.ok(!/^https?:/.test(spec), `${rel} imports external ${spec}`);
    }
  }
});

test('the vendored engine has not drifted from embed/', () => {
  // Two copies of one engine is a deliberate cost: embed/ is lifted whole
  // into every share bundle and must stay self-contained, and the Pages
  // deploy is a subtree split of viewer/ alone where ../embed/ does not
  // exist. This test is the only thing standing between two copies and a
  // silent version split.
  const a = readFileSync(join(VIEWER, 'vendor', 'playcanvas.mjs'));
  const b = readFileSync(join(REPO, 'embed', 'vendor', 'playcanvas.mjs'));
  assert.ok(a.equals(b), 'viewer/vendor and embed/vendor disagree — update both');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd viewer && node --test tests/unit/vendor.test.mjs`
Expected: all three FAIL — the importmap still names jsdelivr, and
`viewer/vendor/playcanvas.mjs` does not exist (ENOENT).

- [ ] **Step 3: Vendor the engine and remap the specifier**

```bash
cd /Users/Shared/code/autosplat
mkdir -p viewer/vendor
cp embed/vendor/playcanvas.mjs viewer/vendor/playcanvas.mjs
```

Create `viewer/vendor/README.md`:

```markdown
# vendor/

`playcanvas.mjs` — PlayCanvas engine, vendored so this viewer needs no CDN:
it is bundled into AutoSplat.app (walking mode must work offline) and served
from Codeberg Pages.

**It is a copy of `embed/vendor/playcanvas.mjs` and must stay byte-identical.**
`tests/unit/vendor.test.mjs` fails if the two drift. Update both together:

    cp ../embed/vendor/playcanvas.mjs vendor/playcanvas.mjs

Two copies rather than one shared file, deliberately: `embed/` is copied
wholesale into every share bundle and has to be self-contained, and the Pages
deploy is a `git subtree split` of `viewer/` alone, where `../embed/` is absent.
```

In `viewer/viewer.html`, replace the importmap (lines 24-30):

```html
  <script type="importmap">
  {
    "imports": {
      "playcanvas": "./vendor/playcanvas.mjs"
    }
  }
  </script>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd viewer && ./tests/run.sh unit`
Expected: PASS, including the pre-existing unit tests.

- [ ] **Step 5: Verify the viewer still actually renders**

```bash
cd /Users/Shared/code/autosplat/viewer && ./serve.sh
```

Open `http://localhost:<port>/viewer.html`, load the demo, enter walking mode once.
A working importmap that resolves to a broken file would pass the tests above and fail
here — the engine has to execute, not just exist.

- [ ] **Step 6: Commit**

```bash
cd /Users/Shared/code/autosplat
git add viewer/viewer.html viewer/vendor viewer/tests/unit/vendor.test.mjs
git commit -m "feat(viewer): vendor the engine instead of loading it from a CDN

viewer.html mapped the playcanvas specifier at cdn.jsdelivr.net, so bundling
it into AutoSplat.app would have broken walking mode offline and voided the
app's zero-external property. The engine is now a byte-identical copy of
embed/vendor, guarded by a drift test, and the Pages deploy loses its CDN
dependency too.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `/system` — show what the launcher already knows

**Files:**
- Create: `pipeline/src/autosplat/webui/routes/system.py`
- Create: `pipeline/src/autosplat/webui/templates/system.html`
- Create: `pipeline/tests/webui/test_system_routes.py`
- Modify: `pipeline/src/autosplat/webui/app.py` (import + `include_router`)
- Modify: `pipeline/src/autosplat/webui/templates/base.html:98-117` (nav)

**Interfaces:**
- Consumes: `doctor.run_doctor(config) -> list[CheckResult]` with fields
  `name: str`, `ok: bool`, `detail: str`, `required: bool`, property `status_emoji`;
  `resources.viewer_status(cfg) -> list[ResourceStatus]` (Task 1)
- Produces: route `GET /system`. No new types — the viewer roles live in `resources`
  precisely so this page and `app.py`'s mount cannot drift apart.

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/webui/test_system_routes.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient


def test_system_page_lists_external_tools(app: FastAPI) -> None:
    with TestClient(app) as client:
        r = client.get("/system")
    assert r.status_code == 200
    body = r.text
    for tool in ("ffmpeg", "colmap", "brush"):
        assert tool in body


def test_system_page_reports_a_missing_bundled_viewer(app: FastAPI, tmp_path: Path) -> None:
    """The defect this page exists for: a missing viewer used to be invisible."""
    app.state.cfg.viewer.supersplat_dist_path = tmp_path / "nope"
    with TestClient(app) as client:
        r = client.get("/system")
    assert r.status_code == 200
    assert "supersplat" in r.text.lower()
    assert "missing" in r.text.lower()


def test_system_page_names_the_role_of_each_viewer(app: FastAPI) -> None:
    with TestClient(app) as client:
        body = client.get("/system").text
    # The charter, rendered: three viewers, three jobs.
    assert "clean up" in body.lower()
    assert "share" in body.lower()
    assert "walk" in body.lower()


def test_nav_links_to_system(app: FastAPI) -> None:
    with TestClient(app) as client:
        body = client.get("/").text
    assert 'href="/system"' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/webui/test_system_routes.py -v`
Expected: FAIL — 404 for `/system`.

- [ ] **Step 3: Write the route module**

Create `pipeline/src/autosplat/webui/routes/system.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`/system` — external tool status and bundled-resource status.

Both halves already existed and were discarded: `desktop.main` runs
`run_doctor` on every launch, then spins in a silent
`while needs_first_run_setup(cfg)` loop, and `webui/app.py` skips the
SuperSplat mount without telling anyone. This page is where that goes.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from autosplat import resources
from autosplat.config import Config
from autosplat.doctor import run_doctor

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/", response_class=HTMLResponse)
async def system_page(request: Request) -> HTMLResponse:
    cfg: Config | None = request.app.state.cfg
    return request.app.state.templates.TemplateResponse(
        request,
        "system.html",
        {
            "checks": run_doctor(cfg) if cfg is not None else [],
            "viewers": resources.viewer_status(cfg),
        },
    )
```

- [ ] **Step 4: Write the template**

Create `pipeline/src/autosplat/webui/templates/system.html`:

```html
{% extends "base.html" %}
{% block title %}System · AutoSplat{% endblock %}
{% block content %}
<h1>System</h1>

<section>
  <h2>External tools</h2>
  <table class="as-table">
    <thead><tr><th>Tool</th><th>Status</th><th>Detail</th></tr></thead>
    <tbody>
      {% for c in checks %}
      <tr>
        <td>{{ c.name }}</td>
        <td>{{ c.status_emoji }}</td>
        <td>{{ c.detail }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <p class="as-muted">
    Missing required tools are installed by <code>scripts/install_deps.sh</code>,
    which the app runs in Terminal on first launch.
  </p>
</section>

<section>
  <h2>Bundled viewers</h2>
  <table class="as-table">
    <thead><tr><th>Name</th><th>Role</th><th>Status</th><th>Path</th></tr></thead>
    <tbody>
      {% for v in viewers %}
      <tr>
        <td>{{ v.name }}</td>
        <td>{{ v.role }}</td>
        <td>{% if v.present %}OK{% else %}MISSING{% endif %}</td>
        <td><code>{{ v.path }}</code></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
{% endblock %}
```

If `base.html` uses different block names or lacks an `as-table` class, follow whatever
`source.html` does — it is the closest existing single-purpose page.

- [ ] **Step 5: Register the router and the nav entry**

In `pipeline/src/autosplat/webui/app.py`, add `system` to the route imports and
`app.include_router(system.router)` after `source`.

In `pipeline/src/autosplat/webui/templates/base.html`, inside `<nav class="as-nav">` after
the `/source` link:

```html
    <a href="/system" class="{% if request.url.path.startswith('/system') %}active{% endif %}">
      System
    </a>
```

Match the icon/markup pattern the neighbouring links use.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd pipeline && uv run pytest tests/webui/test_system_routes.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Run the full suite and commit**

```bash
cd /Users/Shared/code/autosplat/pipeline
uv run pytest -q && uv run mypy src && uv run ruff check src tests
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/webui/routes/system.py \
        pipeline/src/autosplat/webui/templates/system.html \
        pipeline/src/autosplat/webui/app.py \
        pipeline/src/autosplat/webui/templates/base.html \
        pipeline/tests/webui/test_system_routes.py
git commit -m "feat(pipeline): add a /system page for tool and viewer status

desktop.main already ran doctor on every launch and threw the result away,
then waited in a silent loop for tools to appear. The same page names each
bundled viewer's role and says which are actually present, so a broken
install stops looking like an empty capture.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Extract the migrate-storage planner

**Files:**
- Create: `pipeline/src/autosplat/migration.py`
- Create: `pipeline/tests/test_migration.py`
- Modify: `pipeline/src/autosplat/cli.py:546-735` (`migrate_storage` becomes a renderer)

**Interfaces:**
- Consumes: `lifecycle.find_capture_dirs`, `lifecycle.find_ply`,
  `lifecycle.reclaimable_targets`, `lifecycle.protected_targets`, `lifecycle.bytes_in`,
  `lifecycle.recently_active`, `cleanup.prune_intermediates`
- Produces:
  - `migration.PlanRow` — frozen dataclass: `display: str`, `kind: str`, `label: str`,
    `size: int`, `targets: tuple[Path, ...]`, `capture_dir: Path | None`,
    `outputs_entry: Path | None`
  - `migration.MigrationPlan` — frozen dataclass: `rows: tuple[PlanRow, ...]`,
    `reclaimable_bytes: int`, `skipped: int`, `duplicate_names: tuple[str, ...]`
  - `migration.ApplyResult` — frozen dataclass: `reclaimed_bytes: int`,
    `failures: tuple[str, ...]`
  - `migration.plan_migration(captures_dir: Path, outputs_dir: Path, *, now: datetime) -> MigrationPlan`
  - `migration.apply_migration(plan: MigrationPlan) -> ApplyResult`
  - `kind` is one of `"reclaim"`, `"kept"`, `"active"`, `"failed"`, `"outputs_reclaim"`,
    `"outputs_kept"`. Task 6 renders these.

This is a **behaviour-preserving extraction**. `tests/test_cli_migrate_storage.py` is the
oracle: it must stay green without edits to its assertions.

- [ ] **Step 1: Read the source of truth**

Read `pipeline/src/autosplat/cli.py:546-735` in full, plus its docstring. Every rule
encoded there — the relaxed backlog rule, the `recently_active` skip, the outputs/
"last surviving copy" rule, the duplicate-name warning, kept rows staying visible with a
reason — moves verbatim into `plan_migration`. Do not re-derive any of them.

- [ ] **Step 2: Write the failing test**

Create `pipeline/tests/test_migration.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autosplat import migration


def _settled_capture(captures: Path, name: str, *, with_ply: bool = True) -> Path:
    capture = captures / name
    (capture / "output").mkdir(parents=True)
    if with_ply:
        (capture / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 100)
    (capture / "frames").mkdir()
    (capture / "frames" / "0001.png").write_bytes(b"x" * 5000)
    ts = time.time() - 2 * 3600
    for p in [capture, *capture.rglob("*")]:
        os.utime(p, (ts, ts))
    return capture


def test_plan_lists_a_finished_capture_as_reclaimable(tmp_path: Path) -> None:
    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    outputs.mkdir()
    _settled_capture(captures, "2026-05-01_demo")

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))

    assert plan.reclaimable_bytes > 0
    kinds = {r.kind for r in plan.rows}
    assert "reclaim" in kinds


def test_plan_keeps_a_capture_without_a_ply(tmp_path: Path) -> None:
    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    outputs.mkdir()
    _settled_capture(captures, "2026-05-02_failed", with_ply=False)

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))

    assert plan.reclaimable_bytes == 0
    assert [r for r in plan.rows if r.kind == "failed"]
    assert plan.skipped == 1


def test_plan_never_reclaims_an_orphaned_outputs_entry(tmp_path: Path) -> None:
    """The 10 orphans on the real disk are each the last copy of their scene."""
    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    orphan = outputs / "2026-04-01_gone"
    orphan.mkdir(parents=True)
    (orphan / "scene.ply").write_bytes(b"ply\n" + b"x" * 900)

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))

    assert plan.reclaimable_bytes == 0
    row = next(r for r in plan.rows if r.kind == "outputs_kept")
    assert "orphaned" in row.label


def test_plan_skips_a_capture_with_an_in_flight_run(tmp_path: Path) -> None:
    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    outputs.mkdir()
    capture = _settled_capture(captures, "2026-05-03_live")
    (capture / "pipeline.log").write_text("running\n")  # fresh mtime

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))

    assert [r for r in plan.rows if r.kind == "active"]
    assert plan.reclaimable_bytes == 0


def test_plan_delegates_eligibility_to_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The protective predicate must be lifecycle's, not a second copy.

    Written twice, this rule was wrong twice — once locking training/ out of
    cleanup forever, once exposing the bisection probe workspaces. Neutering
    lifecycle.reclaimable_targets must therefore neuter the whole plan; if
    anything is still planned, migration.py has its own opinion about what
    may be deleted, and that is the defect.
    """
    from autosplat import lifecycle

    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    outputs.mkdir()
    _settled_capture(captures, "2026-05-05_demo")

    monkeypatch.setattr(lifecycle, "reclaimable_targets", lambda _c: [])

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))

    assert plan.reclaimable_bytes == 0
    assert not [r for r in plan.rows if r.kind == "reclaim"]


def test_apply_reclaims_only_planned_targets(tmp_path: Path) -> None:
    captures, outputs = tmp_path / "captures", tmp_path / "outputs"
    captures.mkdir()
    outputs.mkdir()
    capture = _settled_capture(captures, "2026-05-04_demo")

    plan = migration.plan_migration(captures, outputs, now=datetime.now(UTC))
    result = migration.apply_migration(plan)

    assert result.failures == ()
    assert result.reclaimed_bytes > 0
    assert not (capture / "frames").exists()
    assert (capture / "output" / "scene.ply").exists()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/test_migration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autosplat.migration'`

- [ ] **Step 4: Write the module**

Create `pipeline/src/autosplat/migration.py`. Structure — the loop bodies are the ones
lifted from `cli.py`, with `table.add_row(...)` replaced by `rows.append(PlanRow(...))`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

"""What `migrate-storage` would reclaim, decided separately from how it is shown.

The rules lived inside `cli.py`'s command body, interleaved with Rich table
construction, which made them reachable only from a terminal. They are
unchanged here — `tests/test_cli_migrate_storage.py` is the oracle for that —
but now a WebUI page can ask the same question.

Nothing in this module decides *whether* a target may be deleted: that is
`lifecycle.reclaimable_targets` / `protected_targets`, called, never restated.
The one time that rule was written a second time it was wrong twice.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from autosplat import cleanup, lifecycle
from autosplat.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PlanRow:
    display: str
    kind: str  # reclaim | kept | active | failed | outputs_reclaim | outputs_kept
    label: str
    size: int
    targets: tuple[Path, ...] = ()
    capture_dir: Path | None = None
    outputs_entry: Path | None = None


@dataclass(frozen=True)
class MigrationPlan:
    rows: tuple[PlanRow, ...]
    reclaimable_bytes: int
    skipped: int
    duplicate_names: tuple[str, ...]


@dataclass(frozen=True)
class ApplyResult:
    reclaimed_bytes: int
    failures: tuple[str, ...]


def target_labels(capture_dir: Path, targets: list[Path]) -> str:
    """Name reclaim targets by their path relative to the capture.

    A bare `.name` is ambiguous now that targets can be nested: `share/_tmp`
    and `rescue/probes` would both read as a single opaque leaf ("_tmp",
    "probes") in a report whose whole purpose is telling the user exactly what
    is about to be deleted.
    """
    return ", ".join(t.relative_to(capture_dir).as_posix() for t in targets)


def plan_migration(captures_dir: Path, outputs_dir: Path, *, now: datetime) -> MigrationPlan:
    """What a migrate-storage run would reclaim, and what it would keep and why.

    Relaxed rule for the backlog: a finished PLY is enough — review status is
    not required, otherwise no legacy capture would ever qualify.

    Callers must apply their own unsafe-layout guard before acting on this
    (see `cli._refuse_if_unsafe_storage_layout`); a planner that refused by
    raising would be awkward to render.
    """
    rows: list[PlanRow] = []
    total = 0
    skipped = 0

    capture_dirs = lifecycle.find_capture_dirs(captures_dir)

    # Deliberate last-wins on a basename collision (the real backlog has
    # repeated names, e.g. two unrelated captures both called
    # "2026-05-25_A_vor1" under different parents) — reported below rather
    # than silently letting an outputs/<name> match resolve against
    # whichever capture happened to be enumerated last.
    capture_by_name: dict[str, Path] = {}
    duplicate_names: set[str] = set()
    for c in capture_dirs:
        if c.name in capture_by_name:
            duplicate_names.add(c.name)
        capture_by_name[c.name] = c

    for capture_dir in capture_dirs:
        display = str(capture_dir.relative_to(captures_dir))
        if lifecycle.find_ply(capture_dir) is None:
            # Failed/unfinished capture — colmap/rescue are still needed for
            # diagnosis or `resume`. Listed (not skipped silently) so the user
            # can see why it's absent from the reclaim total.
            skipped += 1
            rows.append(
                PlanRow(
                    display=display,
                    kind="failed",
                    label="failed — kept (no scene.ply)",
                    size=0,
                    capture_dir=capture_dir,
                )
            )
            continue

        # The safety rule itself lives in `lifecycle.reclaimable_targets`, so
        # every deletion path inherits it. All that is left here is naming
        # what was kept, which `protected_targets` answers.
        targets = lifecycle.reclaimable_targets(capture_dir)
        protected = lifecycle.protected_targets(capture_dir)
        if not targets and not protected:
            continue  # genuinely nothing there — nothing to explain
        protected_note = (
            f" (kept: {target_labels(capture_dir, protected)} — holds a nested capture)"
            if protected
            else ""
        )
        if not targets:
            # Something was there, but every single target is protected (e.g. a
            # nested capture buried in rescue/) — listed as kept, by name,
            # instead of letting the capture vanish with no explanation.
            skipped += 1
            rows.append(
                PlanRow(
                    display=display,
                    kind="kept",
                    label=f"kept{protected_note}",
                    size=0,
                    capture_dir=capture_dir,
                )
            )
            continue

        size = lifecycle.bytes_in(targets)

        if lifecycle.recently_active(capture_dir, now=now):
            # The old output/scene.ply keeps its stale mtime for the whole
            # duration of an add-video/resume rebuild while frames/colmap are
            # rewritten from scratch, so reclaim eligibility alone can't tell a
            # finished capture from one mid-rebuild.
            skipped += 1
            rows.append(
                PlanRow(
                    display=display,
                    kind="active",
                    label=f"active — skipped (in-flight run){protected_note}",
                    size=size,
                    capture_dir=capture_dir,
                )
            )
            continue

        total += size
        # A target can be protected even while others on the same capture are
        # reclaimed normally (a probe that succeeded sits next to abandoned
        # ones under rescue/) — protected_note names it instead of letting it
        # disappear from this row with no trace, which is exactly what hid the
        # round-2 regression until real data surfaced it.
        rows.append(
            PlanRow(
                display=display,
                kind="reclaim",
                label=f"{target_labels(capture_dir, targets)}{protected_note}",
                size=size,
                targets=tuple(targets),
                capture_dir=capture_dir,
            )
        )

    if outputs_dir.is_dir():
        for entry in sorted(outputs_dir.iterdir()):
            if entry.is_symlink() or not entry.is_dir():
                continue
            size = lifecycle.bytes_in([entry])
            owning_capture = capture_by_name.get(entry.name)
            if owning_capture is not None and lifecycle.find_ply(owning_capture) is not None:
                total += size
                rows.append(
                    PlanRow(
                        display=f"outputs/{entry.name}",
                        kind="outputs_reclaim",
                        label="duplicate — reclaimed",
                        size=size,
                        outputs_entry=entry,
                    )
                )
                continue
            # Otherwise it is the last surviving copy of a scene whose capture
            # directory is gone (or never finished): kept unconditionally, no
            # matter how long it has sat there.
            skipped += 1
            rows.append(
                PlanRow(
                    display=f"outputs/{entry.name}",
                    kind="outputs_kept",
                    label=(
                        "orphaned — kept (no capture holds this scene)"
                        if owning_capture is None
                        else "duplicate — kept (capture has no scene.ply yet)"
                    ),
                    size=size,
                    outputs_entry=entry,
                )
            )

    return MigrationPlan(
        rows=tuple(rows),
        reclaimable_bytes=total,
        skipped=skipped,
        duplicate_names=tuple(sorted(duplicate_names)),
    )


def apply_migration(plan: MigrationPlan) -> ApplyResult:
    """Execute a plan's reclaim rows. One failure never stops the sweep."""
    reclaimed = 0
    failures: list[str] = []

    for row in plan.rows:
        if row.kind == "reclaim" and row.capture_dir is not None:
            try:
                result = cleanup.prune_intermediates(row.capture_dir, targets=list(row.targets))
            except Exception as e:
                failures.append(f"{row.capture_dir} — {e}")
                continue
            reclaimed += result.bytes_reclaimed
            failures.extend(str(f) for f in result.failed)
        elif row.kind == "outputs_reclaim" and row.outputs_entry is not None:
            try:
                size = lifecycle.bytes_in([row.outputs_entry])
                shutil.rmtree(row.outputs_entry)
            except OSError as e:
                failures.append(f"{row.outputs_entry} — {e}")
                continue
            reclaimed += size

    logger.info("migration.applied", reclaimed=reclaimed, failures=len(failures))
    return ApplyResult(reclaimed_bytes=reclaimed, failures=tuple(failures))
```

- [ ] **Step 5: Run the new tests**

Run: `cd pipeline && uv run pytest tests/test_migration.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Rewrite the CLI command as a renderer**

In `pipeline/src/autosplat/cli.py`, `migrate_storage` keeps its signature, docstring
(unchanged — the rules are still accurate), config load and
`_refuse_if_unsafe_storage_layout` call, then becomes:

```python
    plan = migration.plan_migration(captures_dir, outputs_dir, now=now)

    table_console = Console(width=200)
    table = Table(title="migrate-storage" + ("" if apply else " — preview (nothing is deleted)"))
    table.add_column("Path")
    table.add_column("What")
    table.add_column("Size", justify="right")
    for row in plan.rows:
        what = row.label if row.kind in ("reclaim", "outputs_reclaim") else f"[dim]{row.label}[/dim]"
        if row.kind == "active":
            what = f"[yellow]{row.label}[/yellow]"
        size = _human_bytes(row.size) if row.size else "—"
        table.add_row(row.display, what, size)
    table_console.print(table)
    console.print(f"[bold]Reclaimable: {_human_bytes(plan.reclaimable_bytes)}[/bold]")
```

followed by the existing skipped/duplicate-name notices (reading `plan.skipped` and
`plan.duplicate_names`), the `if not apply: return` early exit, and:

```python
    result = migration.apply_migration(plan)
    for failure in result.failures:
        console.print(f"[red]failed:[/red] {failure}")
    console.print(
        f"[green]Reclaimed {_human_bytes(result.reclaimed_bytes)}[/green], "
        f"{plan.skipped} skipped, {len(result.failures)} failure(s)."
    )
    if result.failures:
        raise typer.Exit(EXIT_PIPELINE_FAILURE)
```

Then delete `_target_labels` from `cli.py` (lines 822-830) — `migration.target_labels` is
now its home, and `migrate_storage` was its only caller. Keep `_human_bytes`: it is pure
rendering and other commands use it.

Preserve the exact wording of every label and notice — the existing CLI tests assert on
this text. `PlanRow.label` holds **plain text, never Rich markup**: the CLI wraps it in
`[dim]`/`[yellow]` at render time and the HTML template in Task 6 would otherwise print
`[dim]…[/dim]` literally. The one visible difference from before: on an `active` row the
`protected_note` suffix now sits inside the yellow span rather than outside it. Colour
only, and `CliRunner` output carries no colour codes, so no assertion sees it.

- [ ] **Step 7: Verify behaviour is unchanged**

Run: `cd pipeline && uv run pytest tests/test_cli_migrate_storage.py -v`
Expected: PASS with **no edits to that file**. If an assertion fails, the extraction
changed behaviour — fix the extraction, not the test.

Then the real preview, which must report nothing left to do (the sweep already ran on
2026-07-29):

```bash
cd /Users/Shared/code/autosplat/pipeline && uv run autosplat migrate-storage
```

Expected: a table whose *Reclaimable* total is ~0, with the 10 orphaned `outputs/`
entries listed as kept. **Do not pass `--apply`.**

- [ ] **Step 8: Run the full suite and commit**

```bash
cd /Users/Shared/code/autosplat/pipeline
uv run pytest -q && uv run mypy src && uv run ruff check src tests
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/migration.py pipeline/tests/test_migration.py \
        pipeline/src/autosplat/cli.py
git commit -m "refactor(pipeline): separate the migrate-storage plan from its rendering

The retention rules were interleaved with Rich table construction inside the
command body, so only a terminal could ask what was reclaimable. Behaviour is
unchanged — test_cli_migrate_storage.py passes untouched — and the safety
predicates are still lifecycle's, called rather than restated.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `/storage` — the plan, in the app

**Files:**
- Create: `pipeline/src/autosplat/webui/routes/storage.py`
- Create: `pipeline/src/autosplat/webui/templates/storage.html`
- Create: `pipeline/tests/webui/test_storage_routes.py`
- Modify: `pipeline/src/autosplat/webui/app.py`, `templates/base.html` (nav)

**Interfaces:**
- Consumes: `migration.plan_migration`, `migration.apply_migration`,
  `migration.MigrationPlan`, `migration.PlanRow`, `migration.ApplyResult` (Task 5)
- Produces:
  - routes `GET /storage`, `POST /storage/reclaim`, `GET /partials/storage-status`
  - `storage.ReclaimJob` — dataclass: `status: Literal["running", "done", "failed"]`,
    `reclaimed_bytes: int`, `failures: tuple[str, ...]`, `error: str | None`,
    `thread: threading.Thread | None`. Lives on `app.state.reclaim_job`.

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/webui/test_storage_routes.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient


def _settled_capture(captures: Path, name: str) -> Path:
    capture = captures / name
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 100)
    (capture / "frames").mkdir()
    (capture / "frames" / "0001.png").write_bytes(b"x" * 5000)
    ts = time.time() - 2 * 3600
    for p in [capture, *capture.rglob("*")]:
        os.utime(p, (ts, ts))
    return capture


def test_get_storage_previews_and_never_deletes(app: FastAPI, tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    captures.mkdir()
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = tmp_path / "outputs"
    capture = _settled_capture(captures, "2026-05-01_demo")

    with TestClient(app) as client:
        r = client.get("/storage")

    assert r.status_code == 200
    assert "2026-05-01_demo" in r.text
    assert (capture / "frames").exists(), "GET must never mutate"


def test_get_storage_shows_kept_rows_with_a_reason(app: FastAPI, tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    captures.mkdir()
    outputs = tmp_path / "outputs"
    orphan = outputs / "2026-04-01_gone"
    orphan.mkdir(parents=True)
    (orphan / "scene.ply").write_bytes(b"ply\n" + b"x" * 900)
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = outputs

    with TestClient(app) as client:
        body = client.get("/storage").text

    assert "orphaned" in body
    assert orphan.exists()


def test_post_reclaim_frees_space(app: FastAPI, tmp_path: Path) -> None:
    captures = tmp_path / "captures"
    captures.mkdir()
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = tmp_path / "outputs"
    capture = _settled_capture(captures, "2026-05-02_demo")

    with TestClient(app) as client:
        r = client.post("/storage/reclaim", follow_redirects=False)
        assert r.status_code == 303
        job = app.state.reclaim_job
        assert job.thread is not None
        job.thread.join(timeout=30)

    assert job.status == "done", job.error
    assert job.failures == ()
    assert not (capture / "frames").exists()
    assert (capture / "output" / "scene.ply").exists()


def test_reclaim_reports_progress_without_blocking_the_request(
    app: FastAPI, tmp_path: Path
) -> None:
    """The apply runs off-request: a multi-GB rmtree in a WKWebView window
    would otherwise look exactly like a frozen app."""
    captures = tmp_path / "captures"
    captures.mkdir()
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = tmp_path / "outputs"
    _settled_capture(captures, "2026-05-03_demo")

    with TestClient(app) as client:
        client.post("/storage/reclaim", follow_redirects=False)
        app.state.reclaim_job.thread.join(timeout=30)
        r = client.get("/partials/storage-status")

    assert r.status_code == 200
    assert "done" in r.text.lower() or "reclaimed" in r.text.lower()


def test_second_reclaim_while_one_runs_is_refused(app: FastAPI, tmp_path: Path) -> None:
    import threading

    captures = tmp_path / "captures"
    captures.mkdir()
    app.state.cfg.paths.captures_dir = captures
    app.state.cfg.export.outputs_dir = tmp_path / "outputs"

    from autosplat.webui.routes import storage

    app.state.reclaim_job = storage.ReclaimJob(status="running", thread=threading.Thread(target=lambda: None))

    with TestClient(app) as client:
        r = client.post("/storage/reclaim", follow_redirects=False)

    assert r.status_code == 409


def test_nav_links_to_storage(app: FastAPI) -> None:
    with TestClient(app) as client:
        assert 'href="/storage"' in client.get("/").text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/webui/test_storage_routes.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Write the route module**

Create `pipeline/src/autosplat/webui/routes/storage.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`/storage` — what disk is being used, and what may be reclaimed.

GET renders a preview and never mutates; the apply is a separate POST. That
asymmetry is the same one `migrate-storage` has on the command line, and it
is deliberate: this page's subject is irreversible deletion.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from autosplat import migration
from autosplat.config import Config
from autosplat.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/storage", tags=["storage"])

ReclaimStatus = Literal["running", "done", "failed"]


@dataclass
class ReclaimJob:
    """A reclaim sweep running off-request.

    Deleting multiple GB can take a while, and a WKWebView window with a
    blocked request in flight is indistinguishable from a frozen app — this
    repo has already shipped one of those.
    """

    status: ReclaimStatus = "running"
    reclaimed_bytes: int = 0
    failures: tuple[str, ...] = ()
    error: str | None = None
    thread: threading.Thread | None = field(default=None, repr=False)


def _cfg(request: Request) -> Config:
    cfg: Config | None = request.app.state.cfg
    if cfg is None:
        raise HTTPException(status_code=503, detail="No config loaded")
    return cfg


def _plan(cfg: Config) -> migration.MigrationPlan:
    return migration.plan_migration(
        cfg.paths.captures_dir, cfg.export.outputs_dir, now=datetime.now(UTC)
    )


@router.get("/", response_class=HTMLResponse)
async def storage_page(request: Request) -> HTMLResponse:
    cfg = _cfg(request)
    return request.app.state.templates.TemplateResponse(
        request,
        "storage.html",
        {"plan": _plan(cfg), "job": getattr(request.app.state, "reclaim_job", None)},
    )


@router.post("/reclaim")
async def storage_reclaim(request: Request) -> RedirectResponse:
    """Start a reclaim sweep in a background thread.

    The plan is recomputed inside the thread, not carried over from the
    preview: a preview is a plan of unknown age, and a run that started in
    between must not have its working dirs pulled out from under it.
    `plan_migration`'s `recently_active` check is what knows that.
    """
    cfg = _cfg(request)
    existing: ReclaimJob | None = getattr(request.app.state, "reclaim_job", None)
    if existing is not None and existing.status == "running":
        raise HTTPException(status_code=409, detail="A reclaim sweep is already running")

    job = ReclaimJob()

    def _run() -> None:
        try:
            result = migration.apply_migration(_plan(cfg))
        except Exception as e:  # surfaced on the job, not raised into nowhere
            job.status = "failed"
            job.error = str(e)
            logger.error("storage.reclaim_failed", error=str(e))
            return
        job.reclaimed_bytes = result.reclaimed_bytes
        job.failures = result.failures
        job.status = "done"

    job.thread = threading.Thread(target=_run, name="autosplat-reclaim", daemon=True)
    request.app.state.reclaim_job = job
    job.thread.start()
    return RedirectResponse(url="/storage", status_code=303)
```

And in `pipeline/src/autosplat/webui/routes/partials.py`, the polling fragment:

```python
@router.get("/storage-status", response_class=HTMLResponse)
async def storage_status_partial(request: Request) -> HTMLResponse:
    return _templates(request).TemplateResponse(
        request,
        "partials/storage_status.html",
        {"job": getattr(request.app.state, "reclaim_job", None)},
    )
```

Follow whatever `_templates(request)` helper that module already uses.

- [ ] **Step 4: Write the template**

Create `pipeline/src/autosplat/webui/templates/storage.html`:

```html
{% extends "base.html" %}
{% block title %}Storage · AutoSplat{% endblock %}
{% block content %}
<h1>Storage</h1>

<p>
  Reclaimable: <strong>{{ plan.reclaimable_bytes | filesizeformat }}</strong>
  {% if plan.skipped %}
  · {{ plan.skipped }} entr{{ "y" if plan.skipped == 1 else "ies" }} deliberately kept
  {% endif %}
</p>

{% if plan.duplicate_names %}
<p class="as-warn">
  {{ plan.duplicate_names | length }} capture name(s) appear more than once
  ({{ plan.duplicate_names | join(", ") }}) — an outputs/ entry may have been judged
  against the wrong same-named capture.
</p>
{% endif %}

<table class="as-table">
  <thead><tr><th>Path</th><th>What</th><th>Size</th></tr></thead>
  <tbody>
    {% for row in plan.rows %}
    <tr class="as-row-{{ row.kind }}">
      <td><code>{{ row.display }}</code></td>
      <td>{{ row.label }}</td>
      <td>{{ row.size | filesizeformat if row.size else "—" }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<p class="as-muted">
  Sizes on kept rows are informational — they are not part of the reclaimable total.
</p>

{% include "partials/storage_status.html" %}

{% if plan.reclaimable_bytes and not (job and job.status == "running") %}
<form method="post" action="/storage/reclaim"
      onsubmit="return confirm('Reclaim {{ plan.reclaimable_bytes | filesizeformat }}? This deletes working directories and cannot be undone.')">
  <button type="submit" class="as-btn as-btn-danger">Reclaim now</button>
</form>
{% endif %}
{% endblock %}
```

Create `pipeline/src/autosplat/webui/templates/partials/storage_status.html`:

```html
<div id="storage-status"
     {% if job and job.status == "running" %}
     hx-get="/partials/storage-status" hx-trigger="every 2s" hx-swap="outerHTML"
     {% endif %}>
  {% if job %}
    {% if job.status == "running" %}
      <p class="as-muted">Reclaiming… this page updates itself.</p>
    {% elif job.status == "done" %}
      <p>Reclaimed {{ job.reclaimed_bytes | filesizeformat }}.
      {% if job.failures %}
        <span class="as-warn">{{ job.failures | length }} failure(s):</span>
        <ul>{% for f in job.failures %}<li><code>{{ f }}</code></li>{% endfor %}</ul>
      {% endif %}
      </p>
    {% else %}
      <p class="as-warn">Reclaim failed: {{ job.error }}</p>
    {% endif %}
  {% endif %}
</div>
```

The wrapper `div` lives **only** in the partial, and `storage.html` includes it rather than
wrapping it — with `hx-swap="outerHTML"` the fragment replaces the element itself, so a
second wrapper in the page would leave two elements sharing one id after the first swap.
The polling attributes are inside the same `{% if %}` as the running state, which makes the
poll self-terminating: a fragment that keeps polling after `done` is a busy loop in a
desktop window.

- [ ] **Step 5: Register router and nav**

`app.include_router(storage.router)` in `webui/app.py`, and a `/storage` nav link in
`base.html` beside the `/system` one from Task 4:

```html
    <a href="/storage" class="{% if request.url.path.startswith('/storage') %}active{% endif %}">
      Storage
    </a>
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd pipeline && uv run pytest tests/webui/test_storage_routes.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Run the full suite and commit**

```bash
cd /Users/Shared/code/autosplat/pipeline
uv run pytest -q && uv run mypy src && uv run ruff check src tests
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/webui/routes/storage.py \
        pipeline/src/autosplat/webui/routes/partials.py \
        pipeline/src/autosplat/webui/templates/storage.html \
        pipeline/src/autosplat/webui/templates/partials/storage_status.html \
        pipeline/src/autosplat/webui/app.py \
        pipeline/src/autosplat/webui/templates/base.html \
        pipeline/tests/webui/test_storage_routes.py
git commit -m "feat(pipeline): add a /storage page with preview-first reclaim

Sub-project 1 wrote the retention rules; this makes them visible without a
terminal. GET only previews, the apply is a separate POST behind a
confirmation, and it runs off-request with a self-terminating htmx poll —
a multi-GB rmtree blocking a WKWebView request looks exactly like a freeze.
The plan is recomputed inside the thread, so a run that started after the
preview keeps its working dirs.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Walking mode gets an entrance

**Files:**
- Modify: `pipeline/src/autosplat/webui/app.py:94-100` (mounts)
- Modify: `pipeline/src/autosplat/webui/routes/captures.py` (add `/{capture_id}/walk`)
- Modify: `pipeline/src/autosplat/webui/templates/capture/detail.html` (action)
- Create: `pipeline/tests/webui/test_walk_route.py`

**Interfaces:**
- Consumes: `resources.bundled_path("viewer")` (Task 1); `viewer/vendor/` (Task 3);
  `get_capture(...) -> Capture` with `.has_ply: bool` and `.path: Path` (existing, from
  `webui/state.py`)
- Produces: route `GET /captures/{capture_id}/walk`, static mount `/viewer`

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/webui/test_walk_route.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient


def _capture_with_ply(tmp_path: Path, capture_id: str = "2026-07-19_lgs") -> Path:
    capture_dir = tmp_path / capture_id
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 1000)
    return capture_dir


def test_walk_serves_the_viewer_pointed_at_the_capture(app: FastAPI, tmp_path: Path) -> None:
    _capture_with_ply(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.get("/captures/2026-07-19_lgs/walk", follow_redirects=False)

    assert r.status_code == 307
    assert r.headers["location"] == (
        "/viewer/viewer.html?src=/captures/2026-07-19_lgs/scene.ply"
    )


def test_walk_404s_for_an_unknown_capture(app: FastAPI, tmp_path: Path) -> None:
    app.state.cfg.paths.captures_dir = tmp_path
    with TestClient(app) as client:
        assert client.get("/captures/nope/walk").status_code == 404


def test_walk_409s_without_a_ply(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-07-19_empty"
    (capture_dir / "output").mkdir(parents=True)
    app.state.cfg.paths.captures_dir = tmp_path
    with TestClient(app) as client:
        assert client.get("/captures/2026-07-19_empty/walk").status_code == 409


def test_viewer_runtime_is_served(app: FastAPI) -> None:
    """A mount that silently isn't there is the bug this whole branch is about."""
    with TestClient(app) as client:
        r = client.get("/viewer/viewer.html")
    assert r.status_code == 200
    assert "walk" in r.text.lower()


def test_detail_page_offers_walking(app: FastAPI, tmp_path: Path) -> None:
    _capture_with_ply(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path
    with TestClient(app) as client:
        body = client.get("/captures/2026-07-19_lgs").text
    assert "/walk" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && uv run pytest tests/webui/test_walk_route.py -v`
Expected: all FAIL — no `/viewer` mount, no `/walk` route.

- [ ] **Step 3: Mount the viewer runtime**

In `pipeline/src/autosplat/webui/app.py`, replace the SuperSplat mount block with both
mounts, resolved through `resources` and recorded when absent:

```python
    # Bundled viewer runtimes, mounted from the same status list /system
    # renders — so the page can never claim a viewer the app did not mount.
    # The old code mounted SuperSplat if a cwd-relative path happened to
    # exist and said nothing when it didn't, which is why the shipped app's
    # review gate looked empty rather than broken.
    for status in resources.viewer_status(cfg):
        if status.name == "embed":
            continue  # copied into share bundles, never served from here
        if status.present:
            app.mount(
                f"/{status.name}",
                StaticFiles(directory=str(status.path)),
                name=status.name,
            )
        else:
            logger.warning(
                "webui.viewer_missing", viewer=status.name, path=str(status.path)
            )
```

Import `resources` and `get_logger` if `app.py` does not already have them. Note the mount
paths are now derived from the names — `/supersplat` and `/viewer` — which is what
`_supersplat_embed_context` (`captures.py:277`) already looks for by route name, so the
review iframe keeps working unchanged.

- [ ] **Step 4: Add the walk route**

In `pipeline/src/autosplat/webui/routes/captures.py`, after `capture_view`:

```python
@router.get("/{capture_id}/walk")
async def capture_walk(request: Request, capture_id: str) -> RedirectResponse:
    """Open the walking viewer on this capture.

    A redirect rather than a rendered template: viewer.html is served from the
    /viewer mount and resolves its own relative js/, css/ and vendor/ paths.
    Walking mode itself is entered by a click inside the viewer — pointer lock
    requires a user gesture, so no query parameter can start it.
    """
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    if not capture.has_ply:
        raise HTTPException(status_code=409, detail="Capture has no PLY to walk through")
    return RedirectResponse(
        url=f"/viewer/viewer.html?src=/captures/{capture_id}/scene.ply",
        status_code=307,
    )
```

`/captures/{capture_id}/scene.ply` already exists (`captures.py:321`) and is served with a
`.ply` suffix so a viewer can detect the format from the URL — the same reason the
SuperSplat iframe uses it.

- [ ] **Step 5: Add the detail-page action**

In `templates/capture/detail.html`, beside the existing "View splat" action, and gated the
same way:

```html
      {% if capture.has_ply %}
      <a class="as-btn" href="/captures/{{ capture.id }}/walk">Walk through</a>
      {% endif %}
```

Match the surrounding markup — copy the "View splat" anchor's classes rather than
inventing new ones.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd pipeline && uv run pytest tests/webui/test_walk_route.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Verify against a real capture**

```bash
cd /Users/Shared/code/autosplat/pipeline && uv run autosplat webui --port 8080
```

Open a finished capture, click **Walk through**, enter walking mode, move with WASD. This
is the step that proves the mount serves a viewer that actually runs — a 200 on
`viewer.html` says nothing about whether the engine loaded.

- [ ] **Step 8: Run the full suite and commit**

```bash
cd /Users/Shared/code/autosplat/pipeline
uv run pytest -q && uv run mypy src && uv run ruff check src tests
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/webui/app.py \
        pipeline/src/autosplat/webui/routes/captures.py \
        pipeline/src/autosplat/webui/templates/capture/detail.html \
        pipeline/tests/webui/test_walk_route.py
git commit -m "feat(pipeline): give walking mode an entrance from the app

The walking viewer existed since v1.x and was reachable only by dragging a
PLY onto the Pages site — at 1,8 GB per scene, never. A Walk-through action
on the capture detail page now points the bundled viewer at the capture's
own PLY. Both viewer mounts record their absence for /system instead of
disappearing quietly.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: `review` and `share` on the command line — with the gate moved down

**Files:**
- Modify: `pipeline/src/autosplat/lifecycle.py` (add `write_review_marker`)
- Modify: `pipeline/src/autosplat/webui/share_runner.py` (add `UnreviewedCapture`, `build_share_bundle`; thin `_run`)
- Modify: `pipeline/src/autosplat/webui/routes/captures.py:490-506` (use `write_review_marker`)
- Modify: `pipeline/src/autosplat/cli.py` (add `review`, `share`)
- Create: `pipeline/tests/test_cli_review.py`, `pipeline/tests/test_cli_share.py`

**Interfaces:**
- Consumes: `lifecycle.review_status(capture_dir) -> Literal["unreviewed", "reviewed"]`,
  `lifecycle.resolve_publish_ply`, `share.make_share_token`, `share.assemble_bundle`,
  `share.share_link`, `compress.compress_ply`
- Produces:
  - `lifecycle.write_review_marker(capture_dir: Path) -> None`
  - `share_runner.UnreviewedCapture(Exception)`
  - `share_runner.ShareResult` — frozen dataclass: `token: str`, `zip_path: Path`,
    `output_bytes: int`, `input_bytes: int`, `link: str | None`
  - `share_runner.build_share_bundle(cfg, capture_dir, capture_id, *, compressor=compress_ply) -> ShareResult`

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/test_cli_review.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from autosplat.cli import app
from autosplat.lifecycle import review_marker_path, review_status

runner = CliRunner()


def _capture(tmp_path: Path) -> Path:
    capture = tmp_path / "2026-07-19_lgs"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 100)
    return capture


def test_confirm_unchanged_marks_the_capture_reviewed(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    result = runner.invoke(app, ["review", str(capture), "--confirm-unchanged"])
    assert result.exit_code == 0, result.output
    assert review_status(capture) == "reviewed"
    data = json.loads(review_marker_path(capture).read_text())
    assert data["source_ply_mtime"] == (capture / "output" / "scene.ply").stat().st_mtime


def test_upload_stores_the_cleaned_ply(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    cleaned = tmp_path / "cleaned.ply"
    cleaned.write_bytes(b"ply\n" + b"y" * 50)
    result = runner.invoke(app, ["review", str(capture), "--upload", str(cleaned)])
    assert result.exit_code == 0, result.output
    assert (capture / "output" / "scene_reviewed.ply").read_bytes() == cleaned.read_bytes()
    assert review_status(capture) == "reviewed"


def test_confirm_unchanged_removes_a_stale_reviewed_ply(tmp_path: Path) -> None:
    """Same trap the WebUI route documents: a leftover scene_reviewed.ply
    would keep being published after a rebuild."""
    capture = _capture(tmp_path)
    (capture / "output" / "scene_reviewed.ply").write_bytes(b"ply\nstale")
    runner.invoke(app, ["review", str(capture), "--confirm-unchanged"])
    assert not (capture / "output" / "scene_reviewed.ply").exists()


def test_both_flags_is_an_error(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    cleaned = tmp_path / "c.ply"
    cleaned.write_bytes(b"ply\n")
    result = runner.invoke(
        app, ["review", str(capture), "--confirm-unchanged", "--upload", str(cleaned)]
    )
    assert result.exit_code != 0


def test_neither_flag_is_an_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["review", str(_capture(tmp_path))])
    assert result.exit_code != 0


def test_non_ply_upload_is_rejected(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    bad = tmp_path / "notaply.ply"
    bad.write_bytes(b"this is not a ply")
    result = runner.invoke(app, ["review", str(capture), "--upload", str(bad)])
    assert result.exit_code != 0
    assert review_status(capture) == "unreviewed"
```

Create `pipeline/tests/test_cli_share.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from autosplat.cli import app

runner = CliRunner()


def _capture(tmp_path: Path) -> Path:
    capture = tmp_path / "2026-07-19_lgs"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 100)
    return capture


def test_share_refuses_an_unreviewed_capture(tmp_path: Path) -> None:
    """The gate is the point. Today it lives in the route, so a CLI command
    calling the runner directly would have walked straight past it."""
    result = runner.invoke(app, ["share", str(_capture(tmp_path))])
    assert result.exit_code != 0
    assert "review" in result.output.lower()


def test_build_share_bundle_raises_on_an_unreviewed_capture(tmp_path: Path) -> None:
    from autosplat.config import load_config
    from autosplat.webui.share_runner import UnreviewedCapture, build_share_bundle

    capture = _capture(tmp_path)
    cfg = load_config(include_xdg=False)
    with pytest.raises(UnreviewedCapture):
        build_share_bundle(cfg, capture, capture.name)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && uv run pytest tests/test_cli_review.py tests/test_cli_share.py -v`
Expected: FAIL — no such commands; `ImportError` for `build_share_bundle`.

- [ ] **Step 3: Move the marker writer into `lifecycle.py`**

Add to `pipeline/src/autosplat/lifecycle.py`, next to `review_status`:

```python
def write_review_marker(capture_dir: Path) -> None:
    """Record a human sign-off for `capture_dir`'s current output/scene.ply.

    Stores the PLY's mtime so a later rebuild invalidates the sign-off with no
    cooperation from the rebuild path (see `review_status`). Callers that
    publish scene.ply as-is must remove a leftover scene_reviewed.ply first —
    `resolve_publish_ply` would otherwise keep serving the stale one.
    """
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
```

`lifecycle.py` already imports `json`; add `from datetime import UTC, datetime` if only
`datetime` is imported.

Then in `webui/routes/captures.py`, delete the local `_write_review_marker`
(lines ~490-506) and import `write_review_marker` from `autosplat.lifecycle`, updating its
two call sites. The `scene_reviewed.ply` unlink in `capture_review_confirm` **stays in the
route** — it is specific to the confirm-unchanged path, and the CLI will do the same.

- [ ] **Step 4: Extract the share body and put the gate underneath it**

In `pipeline/src/autosplat/webui/share_runner.py`, add above `ShareJobRunner`:

```python
class UnreviewedCapture(Exception):
    """Raised when a capture is asked to be shared before it was reviewed.

    The publish quality gate used to live only in `capture_share`, while this
    module would bundle an unreviewed capture without complaint. That was
    survivable while the WebUI was the only caller; it stops being survivable
    the moment a CLI command exists.
    """


@dataclass(frozen=True)
class ShareResult:
    token: str
    zip_path: Path
    output_bytes: int
    input_bytes: int
    link: str | None


def build_share_bundle(
    cfg: Config,
    capture_dir: Path,
    capture_id: str,
    *,
    compressor: Compressor = compress_ply,
) -> ShareResult:
    """Compress to SOG and assemble a share bundle. Synchronous; raises.

    Refuses an unreviewed capture — the gate lives here so that every
    surface inherits it instead of re-implementing it.
    """
    status = review_status(capture_dir)
    if status == "unreviewed":
        raise UnreviewedCapture(
            f"{capture_dir.name} has not been reviewed — review it before sharing"
        )
    ply = resolve_publish_ply(capture_dir, status)
    if ply is None or not ply.exists():
        raise FileNotFoundError(f"No output/scene.ply in {capture_dir}")

    # The SOG is a durable artifact under output/, kept per the retention
    # policy and reused by later shares — a repeat share becomes seconds.
    sog = capture_dir / "output" / "scene.sog"
    if sog.exists() and sog.stat().st_mtime >= ply.stat().st_mtime:
        logger.info("share.sog_reused", capture_id=capture_id)
    else:
        result = compressor(ply, capture_dir / "output", fmt="sog", quality=cfg.compress.quality)
        # compress_ply names its output after the input stem, so a reviewed
        # capture would yield scene_reviewed.sog. The canonical name is
        # scene.sog regardless of which PLY was published.
        if result.output_path != sog:
            result.output_path.replace(sog)

    token = make_share_token(capture_id)
    embed_src = cfg.share.embed_src_path
    if not embed_src.is_absolute():
        embed_src = resources.REPO_ROOT / embed_src
    paths = assemble_bundle(sog, embed_src, capture_dir / "share", token)
    shutil.rmtree(capture_dir / "share" / "_tmp", ignore_errors=True)

    return ShareResult(
        token=token,
        zip_path=paths.zip_path,
        output_bytes=sog.stat().st_size,
        input_bytes=ply.stat().st_size,
        link=share_link(cfg.share.base_url, token),
    )
```

Import `review_status` from `autosplat.lifecycle` (replacing `_review_status` from
`webui.state`), plus `dataclass`, `resources`. Then `_run` becomes:

```python
    def _run(self, job: ShareJob, capture_dir: Path) -> None:
        try:
            result = build_share_bundle(
                self._cfg, capture_dir, job.capture_id, compressor=self._compress
            )
        except Exception as e:  # surfaced on the job, not raised
            job.status = "failed"
            job.error = str(e)
            logger.error("share.failed", capture_id=job.capture_id, error=str(e))
            return
        job.token = result.token
        job.zip_path = result.zip_path
        job.output_bytes = result.output_bytes
        job.input_bytes = result.input_bytes
        job.link = result.link
        job.status = "done"
        logger.info("share.done", capture_id=job.capture_id, token=result.token)
```

Delete `_resolve_embed_src`. `capture_share`'s existing redirect for unreviewed captures
stays — it is better UX than a 500 — but it is no longer the only thing preventing an
unreviewed share.

- [ ] **Step 5: Add the two CLI commands**

In `pipeline/src/autosplat/cli.py`, before `webui`:

```python
@app.command()
def review(
    capture_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Capture directory to sign off."
    ),
    confirm_unchanged: bool = typer.Option(
        False,
        "--confirm-unchanged",
        help="Publish output/scene.ply as-is, without a cleaned upload.",
    ),
    upload: Path | None = typer.Option(
        None,
        "--upload",
        exists=True,
        dir_okay=False,
        help="A cleaned PLY exported from SuperSplat to publish instead.",
    ),
) -> None:
    """Sign a capture off for publication (publish quality gate).

    The same marker the WebUI writes, through the same function — so a
    capture reviewed here can be shared there, and vice versa. Exactly one of
    --confirm-unchanged / --upload is required.
    """
    from autosplat.lifecycle import write_review_marker

    if confirm_unchanged == (upload is not None):
        console.print("[red]Pass exactly one of --confirm-unchanged / --upload.[/red]")
        raise typer.Exit(EXIT_USER_ERROR)

    scene_ply = capture_dir / "output" / "scene.ply"
    if not scene_ply.exists():
        console.print(f"[red]No output/scene.ply in {capture_dir}[/red]")
        raise typer.Exit(EXIT_USER_ERROR)

    reviewed_ply = capture_dir / "output" / "scene_reviewed.ply"
    if upload is not None:
        content = upload.read_bytes()
        if not content.startswith(b"ply\n"):
            console.print(f"[red]{upload} does not look like a PLY (no 'ply' header).[/red]")
            raise typer.Exit(EXIT_USER_ERROR)
        reviewed_ply.write_bytes(content)
    else:
        # A leftover from a previous review cycle would keep being published
        # by resolve_publish_ply — the WebUI route documents the same trap.
        reviewed_ply.unlink(missing_ok=True)

    write_review_marker(capture_dir)
    console.print(f"[green]Reviewed:[/green] {capture_dir.name}")


@app.command()
def share(
    capture_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Reviewed capture directory to share."
    ),
    config: Path | None = typer.Option(None, "--config", "-c", help="Override config file."),
) -> None:
    """Build a self-hostable share bundle (requires a review first)."""
    from autosplat.webui.share_runner import UnreviewedCapture, build_share_bundle

    cfg = _load_or_die(config)
    try:
        result = build_share_bundle(cfg, capture_dir, capture_dir.name)
    except UnreviewedCapture as e:
        console.print(f"[red]{e}[/red]")
        console.print("Run: autosplat review <capture> --confirm-unchanged")
        raise typer.Exit(EXIT_USER_ERROR) from e
    except Exception as e:
        console.print(f"[red]Share failed:[/red] {e}")
        raise typer.Exit(EXIT_PIPELINE_FAILURE) from e

    console.print(f"[green]Bundle:[/green] {result.zip_path}")
    console.print(f"Token: {result.token}")
    if result.link:
        console.print(f"Link:  {result.link}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd pipeline && uv run pytest tests/test_cli_review.py tests/test_cli_share.py -v`
Expected: PASS (8 tests)

- [ ] **Step 7: Verify nothing regressed in the WebUI paths**

Run: `cd pipeline && uv run pytest tests/webui/ -q`
Expected: PASS. `test_share_runner.py` exercises `_run` through the runner; if it patched
`_resolve_embed_src`, point it at `cfg.share.embed_src_path` instead.

- [ ] **Step 8: Run the full suite and commit**

```bash
cd /Users/Shared/code/autosplat/pipeline
uv run pytest -q && uv run mypy src && uv run ruff check src tests
cd /Users/Shared/code/autosplat
git add pipeline/src/autosplat/lifecycle.py \
        pipeline/src/autosplat/webui/share_runner.py \
        pipeline/src/autosplat/webui/routes/captures.py \
        pipeline/src/autosplat/cli.py \
        pipeline/tests/test_cli_review.py pipeline/tests/test_cli_share.py
git commit -m "feat(pipeline): add review and share CLI commands, gate them underneath

The publish path was GUI-only, so a scripted capture could not be published.
Both commands share the WebUI's code: write_review_marker moves into
lifecycle, and the compress-and-assemble body moves out of ShareJobRunner._run
into build_share_bundle.

That extraction also moves the review gate down a layer. It lived in
capture_share alone, while the runner would bundle an unreviewed capture
without complaint — a CLI command on top of the runner would have walked
straight past it. build_share_bundle now raises UnreviewedCapture, so both
surfaces inherit the refusal, and it is finally testable without HTTP.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Write the charter down, then ship

**Files:**
- Modify: `AGENTS.md:13-23` (component table + a charter section)
- Modify: `viewer/AGENTS.md` (drop "geparkt")
- Modify: `CHANGELOG.md` (Unreleased section)
- Modify: `pipeline/docs/` — whichever page documents the CLI surface

**Interfaces:** none (documentation).

- [ ] **Step 1: Correct the component table in the root `AGENTS.md`**

Replace the `viewer/` row's description. It currently reads "geparkt als
Entwicklungsviewer", which is what hid a unique feature for months:

```markdown
| `viewer/` | Splat-Viewer mit **Walking-Mode** (First-Person + Kollision) und die Projekt-Website auf Codeberg Pages (Vanilla HTML/CSS/JS, kein Build-Step) | `viewer/AGENTS.md` |
```

- [ ] **Step 2: Add the charter section**

After the component table in `AGENTS.md`:

```markdown
## Rollen-Charta (ratifiziert 2026-07-29, nicht neu diskutieren)

**AutoSplat.app ist die kanonische Tür.** Jeder Schritt von Import bis Veröffentlichung
muss dort klickbar sein. Die CLI ist gleichwertig für Automatisierung und Batch, darf aber
**nie der einzige Weg** zu einem Schritt sein — und umgekehrt.

Die drei Viewer überlappen sich nur beim reinen Anschauen. Jeder hat genau eine Rolle:

| Artefakt | Rolle |
|---|---|
| SuperSplat (`pipeline/target/supersplat/dist`, gebündelt) | **bereinigen** — der Editor des Review-Gates |
| `embed/` | **teilen** — zero-external Runtime in Share-Bundles |
| `viewer/` | **begehen** — Walking-Mode; dazu die Projekt-Website |

Ein vierter Viewer ist eine Design-Entscheidung, kein Detail. Wer einen hinzufügt, trägt
ihn hier ein oder lässt es.

**Gebündelte Ressourcen** werden ausschließlich über `resources.bundled_path()` aufgelöst
— nie gegen `Path.cwd()`. Ein Finder-Start hat kein sinnvolles CWD; genau daran fehlte
jeder DMG bis v1.16.0 der Review-Viewer.
```

- [ ] **Step 3: Update `viewer/AGENTS.md`**

Remove any "geparkt" wording, state the two jobs (walking viewer + project website), and
add the vendoring rule:

```markdown
`vendor/playcanvas.mjs` muss **byte-identisch** zu `embed/vendor/playcanvas.mjs` bleiben —
`tests/unit/vendor.test.mjs` prüft das. Beide zusammen aktualisieren.
```

- [ ] **Step 4: Write the CHANGELOG entry**

Under `## [Unreleased]` in the root `CHANGELOG.md`:

```markdown
### Added
- `/system` page: external tool status (the launcher already ran `doctor` and discarded
  the result) plus which bundled viewer resolved, and its role.
- `/storage` page: disk usage and reclaimable space by lifecycle state, preview-first,
  with an explicit apply.
- "Walk through" on a capture: the walking viewer, previously reachable only by dragging
  a PLY onto the Pages site, now opens on the capture's own PLY.
- `autosplat review` and `autosplat share`: the publish path is scriptable.

### Fixed
- **AutoSplat.app had no review viewer.** `supersplat_dist_path` resolved against the
  process CWD and was never bundled, so a Finder launch silently rendered no viewer and
  the mandatory review gate degraded to blind "confirm unchanged". SuperSplat is now
  bundled (source maps stripped) and `build_app.sh` refuses to build without it.
- **The review gate could be bypassed below the route.** `ShareJobRunner` would bundle an
  unreviewed capture; the refusal now lives in `build_share_bundle`, beneath both surfaces.
- `viewer/` loaded the PlayCanvas engine from a CDN, which would have broken walking mode
  offline once bundled. The engine is vendored, with a drift test against `embed/vendor`.

### Changed
- `resources.bundled_path()` is the single resolver for bundled assets.
- The migrate-storage planner moved out of `cli.py` into `migration.py`; behaviour
  unchanged.
```

- [ ] **Step 5: Verify the docs match the code**

```bash
cd /Users/Shared/code/autosplat/pipeline
uv run autosplat --help          # review + share appear
grep -c "geparkt" ../AGENTS.md ../viewer/AGENTS.md   # expect 0 in both
python3 /Users/Shared/code/_docs/readme/readme_lint.py autosplat
```

- [ ] **Step 6: Build and verify the real app**

```bash
cd /Users/Shared/code/autosplat/pipeline
./scripts/build_app.sh
du -sh dist/AutoSplat.app     # expect ~180 MB
open dist/AutoSplat.app
```

In the launched app, confirm all four: `/system` lists three viewers as present, a
finished capture shows the SuperSplat review viewer (**this is the defect the branch
exists for**), "Walk through" enters walking mode, and `/storage` previews without
deleting.

- [ ] **Step 7: Commit**

```bash
cd /Users/Shared/code/autosplat
git add AGENTS.md viewer/AGENTS.md CHANGELOG.md
git commit -m "docs: write down the charter of doors and viewer roles

viewer/ was labelled 'geparkt' while holding the only walking mode in the
repo — the label is why it stayed unreachable. The charter names one role per
viewer and states that bundled resources resolve via resources.bundled_path,
never against CWD.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Verification before merge

- [ ] `cd pipeline && uv run pytest -q` — green, count above 597
- [ ] `cd pipeline && uv run mypy src` — clean
- [ ] `cd pipeline && uv run ruff check src tests` — clean
- [ ] `cd viewer && ./tests/run.sh` — green (unit + e2e)
- [ ] `cd embed && ./tests/run.sh` — green (`embed/` is untouched; it is now the source of
      truth that `viewer/vendor` copies from)
- [ ] `./scripts/build_app.sh` succeeds; bundle ≈ 180 MB
- [ ] In the built app: review viewer present, walk works, `/system` and `/storage` render
- [ ] `autosplat migrate-storage` (no `--apply`) still reports the real backlog correctly
- [ ] No test references a path under the real `$HOME`

Then: `superpowers:finishing-a-development-branch`.
