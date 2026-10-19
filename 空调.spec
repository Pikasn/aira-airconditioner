# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH)
resources = [(str(root / name), ".") for name in ("index.html", "setup.html", "setup.css", "setup.js", "desktop.css", "desktop.js", "floating.css", "floating.js")]
resources.append((str(root / "assets"), "assets"))
resources += collect_data_files("miio", includes=["**/*.yaml", "**/*.yml", "**/*.json"])
resources += copy_metadata("python-miio")

a = Analysis(
    [str(root / "desktop.py")], pathex=[str(root)], binaries=[], datas=resources,
    hiddenimports=[
        "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.on",
        "webview.platforms.winforms", "webview.platforms.edgechromium",
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter", "pytest", "httpx", "bleak",
              "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cocoa", "webview.platforms.cef"],
    noarchive=False, optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="空调", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    disable_windowed_traceback=False, icon=str(root / "assets" / "空调.ico"),
    version=str(root / "version-info.txt"), contents_directory="_internal",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="空调")
