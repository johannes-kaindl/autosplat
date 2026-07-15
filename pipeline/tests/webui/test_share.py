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
