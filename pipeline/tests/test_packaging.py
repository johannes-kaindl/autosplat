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


def _expand_datas(datas: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Expand directory entries in a `datas` list into their individual files.

    `datas` pairs a source path with a bundle-relative dest directory; when
    the source is a directory (as `viewer/js` is), PyInstaller stages every
    file under it, but the plan itself never names them. An assertion like
    `"landing.js" not in sources` against the unexpanded list can never see
    inside `viewer/js` — it isn't testing what ships, only what the plan's
    top-level entries are literally named. Expanding here makes filename
    assertions actually reflect the files PyInstaller would stage.
    """
    expanded: list[tuple[str, str]] = []
    for src, dest in datas:
        path = Path(src)
        if path.is_dir():
            for file in sorted(path.rglob("*")):
                if file.is_file():
                    expanded.append((str(file), dest))
        else:
            expanded.append((src, dest))
    return expanded


def _spec_datas() -> list[tuple[str, str]]:
    """Execute the spec's `datas` construction in isolation.

    The spec references PyInstaller globals (SPECPATH, Analysis, ...) that
    only exist under pyinstaller, so we exec only up to the datas list by
    providing SPECPATH and stopping at the first PyInstaller call.
    """
    source = SPEC.read_text(encoding="utf-8")
    head = source.split("# uvicorn[standard]")[0]
    namespace: dict[str, object] = {"SPECPATH": str(SPEC.parent)}
    exec(compile(head, str(SPEC), "exec"), namespace)
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
    """Round-2 review finding: `"landing.js" not in sources` against the
    unexpanded `datas` list can never fail — `viewer/js/landing.js` lives
    *inside* the `js` directory entry, and `_spec_datas()` never looks
    inside directory sources. `_expand_datas` fixes that by walking
    directory entries down to their files, which also makes the assertion's
    outcome flip: landing.js does ship (see AutoSplat.spec's comment) as an
    accepted consequence of taking `js/` whole. `assets` and `index.html`
    stay genuinely excluded — they are their own top-level allowlist
    entries, never taken, so they are absent even after expansion.
    """
    datas = _spec_datas()
    dests = [d[1] for d in datas]
    assert "viewer" in dests or any(x.startswith("viewer/") for x in dests)
    viewer_files = _expand_datas(datas)
    names = [Path(src).name for src, dest in viewer_files if dest.startswith("viewer")]
    # The 17 MB marketing assets and the landing page's own top-level entry
    # (viewer/index.html) stay out — only viewer.html, js/, css/, icons/,
    # vendor/ are allowlisted (see AutoSplat.spec).
    #
    # Checked on `dests`, not `names`: `assets/` is itself a directory entry,
    # so `_expand_datas` would expand it into its individual files (hero.png,
    # etc.) — none of which is literally named "assets". An assertion like
    # `"assets" not in names` can therefore never see an allowlisted
    # `viewer/assets` entry; it would keep passing even after the plan starts
    # shipping the 17 MB marketing folder. Asserting on the unexpanded dest
    # path catches that regardless of what's inside the directory.
    assert not [d for d in dests if d.startswith("viewer/assets")]
    assert "index.html" not in names
    # landing.js DOES ship: it lives inside js/, taken whole because app.js
    # imports dropzone.js — see AutoSplat.spec's comment for why cherry-
    # picking modules out of js/ is not an option.
    assert "landing.js" in names


def test_embed_is_still_bundled() -> None:
    """Share bundles are assembled from it — a regression here breaks sharing."""
    datas = _spec_datas()
    assert [d for d in datas if d[1].startswith("embed")]
