# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for AutoSplat.app. Run via scripts/build_app.sh (from repo root).

import os
import re

from PyInstaller.utils.hooks import collect_submodules

# Paths in a spec resolve relative to the spec dir (SPECPATH); compute the repo
# root so the build works regardless of CWD.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))


def _p(*parts):
    return os.path.join(ROOT, *parts)


def _app_version():
    """Read __version__ from the package (regex, no import — keeps the spec
    dependency-free) so the bundle's Info.plist carries the real version
    instead of PyInstaller's 0.0.0 default."""
    with open(_p("src/autosplat/__init__.py"), encoding="utf-8") as f:
        match = re.search(r'__version__\s*=\s*"([^"]+)"', f.read())
    return match.group(1) if match else "0.0.0"


APP_VERSION = _app_version()


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

# uvicorn[standard] resolves its protocol/loop implementations dynamically, so
# they must be named explicitly; same for the route modules imported by string.
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "webview",
    "webview.platforms.cocoa",
    *collect_submodules("autosplat.webui.routes"),
]

a = Analysis(
    [_p("packaging/autosplat_app.py")],
    pathex=[_p("src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoSplat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AutoSplat",
)

app = BUNDLE(
    coll,
    name="AutoSplat.app",
    icon=_p("packaging/AutoSplat.icns"),
    bundle_identifier="org.codeberg.jkaindl.autosplat",
    info_plist={
        "CFBundleDisplayName": "AutoSplat",
        "CFBundleName": "AutoSplat",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        # Classic app: Dock icon + a real WebView window (no LSUIElement).
        "NSHighResolutionCapable": True,
    },
)
