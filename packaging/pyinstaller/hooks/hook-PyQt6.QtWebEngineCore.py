from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyqt6_library_info


if pyqt6_library_info.version is not None:
    if pyqt6_library_info.version < [6, 2, 2]:
        raise SystemExit(
            "ERROR: PyInstaller's QtWebEngine support requires Qt6 6.2.2 or later!"
        )

    hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
    webengine_binaries, webengine_datas = pyqt6_library_info.collect_qtwebengine_files()

    binaries += [entry for entry in webengine_binaries if Path(entry[0]).exists()]
    datas += [entry for entry in webengine_datas if Path(entry[0]).exists()]
