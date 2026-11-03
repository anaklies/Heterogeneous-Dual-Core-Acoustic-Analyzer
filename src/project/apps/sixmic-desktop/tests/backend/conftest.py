"""Backend test fixtures. All simulated data is explicitly marked test-fixture."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Must run before pytest creates its 0700 tmp dirs (see module docstring).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sandbox_compat  # noqa: E402

_sandbox_compat.apply()

collect_ignore = ["_tmp"]
collect_ignore_glob = ["_tmp/*"]

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = REPO_ROOT / "apps" / "sixmic-desktop" / "backend"
PROTOCOL_ROOT = REPO_ROOT / "interfaces" / "pc_backend_v1"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sixmic_backend.diagnostics import close_backend_logging  # noqa: E402
from sixmic_backend.testing.mock_ps_server import MockPsServer  # noqa: E402


@pytest.fixture(scope="session")
def protocol_root() -> Path:
    assert PROTOCOL_ROOT.is_dir(), f"missing protocol contracts: {PROTOCOL_ROOT}"
    return PROTOCOL_ROOT


@pytest.fixture()
def user_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    root = tmp_path / "userdata"
    dirs = {name: root / name for name in
            ("root", "logs", "data", "recordings", "events", "exports", "evidence")}
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SIXMIC_USER_DATA_DIR", str(root))
    yield dirs
    close_backend_logging()


@pytest.fixture()
def mock_server():
    servers: list[MockPsServer] = []

    def start(**kwargs) -> dict:
        server = MockPsServer(**kwargs)
        info = server.start()
        servers.append(server)
        return {"server": server, **info}

    yield start
    for server in servers:
        server.stop()
    close_backend_logging()


@pytest.fixture()
def device_session_factory(mock_server, user_dirs, protocol_root):
    from sixmic_backend.session import DeviceSession

    sessions: list[DeviceSession] = []

    def build(**mock_kwargs) -> tuple:
        fixture = mock_server(**mock_kwargs)
        session = DeviceSession(host="127.0.0.1",
                                control_port=fixture["controlPort"],
                                binary_port=fixture["binaryPort"],
                                protocol_root=protocol_root,
                                user_dirs=user_dirs, auto_reconnect=False)
        sessions.append(session)
        return session, fixture["server"]

    yield build
    for session in sessions:
        session.close()
    close_backend_logging()
