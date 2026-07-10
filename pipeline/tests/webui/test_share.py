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
