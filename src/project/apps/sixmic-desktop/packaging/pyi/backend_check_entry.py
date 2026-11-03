"""PyInstaller entry wrapper for SixMic3D-BackendCheck.exe.

PyInstaller executes the given "script" as top-level __main__. backend_check.py
cannot be used directly because it uses package-relative imports such as
"from .. import __version__"; run as __main__ those fail with
"attempted relative import with no known parent package".

This wrapper is packaging-owned (apps/sixmic-desktop/packaging); it does not
change backend code. It imports the real module inside the sixmic_backend
package and calls its main(), preserving the documented contract:
exit code 0/1, final stdout line exactly "SELF-TEST PASS"/"SELF-TEST FAIL".
"""
from sixmic_backend.app.backend_check import main

if __name__ == "__main__":
    raise SystemExit(main())
