"""PyInstaller runtime hook (packaging-owned, opt-in log capture only).

Why
---
The product bundle is built windowed (console=False): a frozen Windows GUI
subsystem process normally has sys.stdout/sys.stderr = None and Qt/QML warnings
go nowhere a CI script can read. build_desktop.ps1 and smoke_test_installer.ps1
need real evidence that the packaged GUI starts without QML errors.

When the environment variable SIXMIC_PACKAGING_GUI_LOG is set to a file path,
this hook appends Python stdout/stderr, uncaught exceptions and Qt messages
(including QML warnings) to that file. Nothing is redirected when the variable
is unset, so normal product launches behave exactly as before; this is a
packaging-owned diagnostic hook, not UI code.

The hook never imports the Qt GUI stack: only QtCore (for the message handler),
which the application imports anyway.
"""
from __future__ import annotations

import os
import sys
import traceback

_LOG_PATH = os.environ.get("SIXMIC_PACKAGING_GUI_LOG")
if _LOG_PATH:
    try:
        _log = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)
        sys.stdout = _log
        sys.stderr = _log
        sys.__stdout__ = _log
        sys.__stderr__ = _log
        print("[gui-log] runtime hook active; pid=" + str(os.getpid()))

        def _excepthook(exc_type, exc, tb):  # pragma: no cover - diagnostic path
            traceback.print_exception(exc_type, exc, tb, file=_log)
            _log.flush()

        sys.excepthook = _excepthook

        try:
            from PySide6.QtCore import qInstallMessageHandler

            def _qt_message_handler(mode, context, message):  # pragma: no cover
                try:
                    _log.write("[qt] " + str(message) + "\n")
                    _log.flush()
                except Exception:
                    pass

            qInstallMessageHandler(_qt_message_handler)
            print("[gui-log] Qt message handler installed")
        except Exception as exc:  # noqa: BLE001 - diagnostic aid only
            print("[gui-log] Qt message handler NOT installed: " + repr(exc))

        try:
            import faulthandler

            faulthandler.enable(file=_log, all_threads=True)
        except Exception:
            pass
    except Exception:  # noqa: BLE001 - logging must never break the app
        pass
