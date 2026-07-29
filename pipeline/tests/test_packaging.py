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
