# SPDX-License-Identifier: AGPL-3.0-or-later

import zipfile
from pathlib import Path

from autosplat.webui.share import BundlePaths, assemble_bundle, make_share_token, share_link


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
