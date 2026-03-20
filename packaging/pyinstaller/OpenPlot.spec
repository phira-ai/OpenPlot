# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


def _existing_path(path: Path) -> str | None:
    resolved = path.resolve()
    if resolved.is_file():
        return str(resolved)
    return None


def _asset_path_from_env(env_name: str, default_rel_path: str, *, base_dir: Path) -> Path:
    raw = os.environ.get(env_name, default_rel_path)
    path = Path(raw)
    if not path.is_absolute():
        path = base_dir / path
    return path


project_root = Path(SPECPATH).resolve().parent.parent
src_root = project_root / "src"
static_dir = src_root / "openplot" / "static"

if not (static_dir / "index.html").is_file():
    raise SystemExit(
        "Frontend assets are missing. Run `npm run build --prefix frontend` before packaging."
    )

datas, binaries, hiddenimports = collect_all("webview")
datas.append((str(static_dir), "openplot/static"))

matplotlib_datas, matplotlib_binaries, matplotlib_hiddenimports = collect_all("matplotlib")
datas.extend(matplotlib_datas)
binaries.extend(matplotlib_binaries)
hiddenimports.extend(matplotlib_hiddenimports)
hiddenimports.extend(
    [
        "matplotlib.backends.backend_agg",
        "matplotlib.backends.backend_pdf",
    ]
)

if sys.platform == "linux":
    import PyQt6

    pyqt6_root = Path(PyQt6.__file__).resolve().parent
    for src_rel, dest_rel in (
        ("Qt6/plugins/platforms/libqxcb.so", "Qt6/plugins/platforms/libqxcb.so"),
        (
            "Qt6/plugins/xcbglintegrations/libqxcb-glx-integration.so",
            "Qt6/plugins/xcbglintegrations/libqxcb-glx-integration.so",
        ),
        (
            "Qt6/plugins/xcbglintegrations/libqxcb-egl-integration.so",
            "Qt6/plugins/xcbglintegrations/libqxcb-egl-integration.so",
        ),
        ("Qt6/resources", "Qt6/resources"),
        ("Qt6/libexec", "Qt6/libexec"),
    ):
        asset_path = pyqt6_root / src_rel
        dest_path = Path(dest_rel)
        if asset_path.is_dir():
            datas.append((str(asset_path), f"PyQt6/{dest_path.as_posix()}"))
        elif asset_path.is_file():
            datas.append((str(asset_path), f"PyQt6/{dest_path.parent.as_posix()}"))

hiddenimports.extend(
    [
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
    ]
)

if sys.platform == "linux":
    hiddenimports.extend(
        [
            "qtpy",
            "qtpy.QtCore",
            "qtpy.QtGui",
            "qtpy.QtWidgets",
            "qtpy.QtNetwork",
            "qtpy.QtWebChannel",
            "qtpy.QtWebEngineCore",
            "qtpy.QtWebEngineWidgets",
            "PyQt6.QtCore",
            "PyQt6.QtGui",
            "PyQt6.QtWidgets",
            "PyQt6.QtNetwork",
            "PyQt6.QtWebChannel",
            "PyQt6.QtWebEngineCore",
            "PyQt6.QtWebEngineWidgets",
        ]
    )
hiddenimports = sorted(set(hiddenimports))

macos_icon = _asset_path_from_env(
    "OPENPLOT_MACOS_ICON", "packaging/macos/openplot.icns", base_dir=project_root
)
windows_icon = _asset_path_from_env(
    "OPENPLOT_WINDOWS_ICON", "packaging/windows/openplot.ico", base_dir=project_root
)

icon_file = None
if sys.platform == "darwin":
    icon_file = _existing_path(macos_icon)
elif sys.platform == "win32":
    icon_file = _existing_path(windows_icon)

a = Analysis(
    [str(src_root / "openplot" / "desktop.py")],
    pathex=[str(src_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_root / "packaging" / "pyinstaller" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenPlot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OpenPlot",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="OpenPlot.app",
        icon=icon_file,
        bundle_identifier="io.github.phira-ai.openplot",
        version="0.1.0",
    )
