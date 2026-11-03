"""Packaging override of PyInstaller's built-in PySide6.QtQml hook.

The built-in hook calls pyside6_library_info.collect_qtqml_files(), which
collects *every* QML module directory found in the PySide6 wheel (QtWebEngine,
QtQuick3D, Qt3D, QtCharts, multimedia, ...). This bundle must contain only the
Qt modules the SixMic3D UI actually imports (frontend handoff brief: "only
collect the Qt modules actually needed; no WebEngine, models, toolchains or
historical audio").

The spec resolves the required QML module closure from the application's own
.qml sources (packaging/tools/qt_qml.py), copies those modules as datas, and
adds the required Qt 6 runtime DLLs explicitly (packaging/tools/qt_runtime.py).
This hook therefore only keeps the normal QtQml module dependencies from
PyInstaller's Qt hook utilities and deliberately skips the QML tree.

Custom hooks in the spec's hookspath take precedence over PyInstaller's
built-in hooks (PyInstaller build_main.py: "Prepend directories in hookspath
(-additional-hooks-dir) to take precedence over those from the entry").
"""
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

# Deliberately NOT: qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()
# The selective collection lives in sixmic_desktop.spec / tools/qt_qml.py.
