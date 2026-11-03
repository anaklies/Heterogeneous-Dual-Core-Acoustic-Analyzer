"""Frontend test fixtures (Qt offscreen; test-fixture data only)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SIXMIC_USER_DATA_DIR",
                      str(Path(__file__).resolve().parent / "_userdata"))

import pytest

# Must run before pytest creates its 0700 tmp dirs (see module docstring).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sandbox_compat  # noqa: E402

_sandbox_compat.apply()

# Leftover sandbox-denied scratch directories from earlier harness runs must not
# be collected as test modules.
collect_ignore = ["_tmp", "_userdata", "_userdata2"]
collect_ignore_glob = ["_tmp/*", "_userdata/*", "_userdata2/*"]

APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APP_ROOT.parents[1]
PROTOCOL_ROOT = REPO_ROOT / "interfaces" / "pc_backend_v1"
for extra in (str(APP_ROOT), str(APP_ROOT / "backend")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from PySide6.QtGui import QGuiApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    application = QGuiApplication.instance() or QGuiApplication([])
    yield application


def pump(application, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        application.processEvents()
        time.sleep(0.01)


@pytest.fixture()
def protocol_root() -> Path:
    assert PROTOCOL_ROOT.is_dir()
    return PROTOCOL_ROOT


@pytest.fixture()
def user_dirs(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "userdata"
    for name in ("logs", "data", "recordings", "events", "exports", "ui", "evidence"):
        (root / name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SIXMIC_USER_DATA_DIR", str(root))
    yield root


@pytest.fixture(scope="session")
def demo_recording() -> Path:
    target = APP_ROOT / "tests" / "frontend" / "fixtures" / "demo-recording"
    if not (target / "manifest.json").is_file():
        sys.path.insert(0, str(APP_ROOT / "ui" / "tools"))
        import make_demo_recording
        make_demo_recording.build(target)
    return target
