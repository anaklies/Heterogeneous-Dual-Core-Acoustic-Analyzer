"""Filesystem paths: user data must live under the user profile, never Program Files."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "SixMic3D"


def user_data_dir() -> Path:
    """Return the writable per-user data directory (created lazily)."""
    override = os.environ.get("SIXMIC_USER_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_DIR_NAME
        return Path.home() / "AppData" / "Local" / APP_DIR_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) / APP_DIR_NAME) if xdg else (Path.home() / ".local" / "share" / APP_DIR_NAME)


def ensure_user_dirs() -> dict[str, Path]:
    root = user_data_dir()
    layout = {
        "root": root,
        "logs": root / "logs",
        "data": root / "data",
        "recordings": root / "recordings",
        "events": root / "events",
        "exports": root / "exports",
        "evidence": root / "evidence",
    }
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    return layout


def _executable_dir() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def protocol_data_candidates(explicit: str | Path | None = None) -> list[Path]:
    """Protocol contract data search order (see UI_BACKEND_HANDOFF.md)."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    exe_dir = _executable_dir()
    if exe_dir is not None:
        candidates += [exe_dir / "protocol", exe_dir / "_internal" / "protocol"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "protocol")
    here = Path(__file__).resolve()
    # dev fallback: <repo>/interfaces/pc_backend_v1 (backend/ lives at apps/sixmic-desktop/backend)
    for parent in here.parents:
        candidate = parent / "interfaces" / "pc_backend_v1"
        if candidate.is_dir():
            candidates.append(candidate)
            break
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def protocol_dir(explicit: str | Path | None = None) -> Path | None:
    """First existing protocol data directory, or None for bundled defaults."""
    for candidate in protocol_data_candidates(explicit):
        if candidate.is_dir():
            return candidate
    return None


def append_path_to(*chunks: str) -> Path:
    return Path(*chunks).resolve()


def is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".sixmic_write_probe"
        probe.write_bytes(b"1")
        probe.unlink()
        return True
    except OSError:
        return False
