"""Sandbox compatibility for pytest tmp dirs on this Windows host.

The DSH workspace sandbox maps POSIX mkdir(mode=0o700) onto a Windows DACL that
denies even the creating process any directory listing.  Pytest creates its
per-test temporary directories with mode 0700, so every tmp_path fixture fails
with PermissionError: [WinError 5] on this host.

On Windows the POSIX mode has no meaningful filesystem effect outside this
sandbox, so normalising it to the default 0o777 restores standard behaviour.
This module is test infrastructure only; it never loads in the product app.
"""
from __future__ import annotations

import itertools
import os
import tempfile
from pathlib import Path

_APPLIED = False


def apply() -> None:
    global _APPLIED
    if _APPLIED or os.name != "nt":
        _APPLIED = True
        return
    original = Path.mkdir

    def mkdir(self, mode=0o777, parents=False, exist_ok=False):  # noqa: ANN001
        # Windows ignores mode for ACLs; passing the sandbox-triggering 0700
        # value through would create an unusable directory.
        return original(self, 0o777, parents=parents, exist_ok=exist_ok)

    Path.mkdir = mkdir

    # tempfile.mkdtemp/libc create directories with mode 0700 directly through
    # os.mkdir, bypassing Path.mkdir; reproduce with the default mode instead.
    def mkdtemp(suffix=None, prefix=None, dir=None):  # noqa: ANN001
        prefix, suffix, directory = tempfile._sanitize_params(  # type: ignore[attr-defined]
            prefix, suffix, dir)[:3]
        for _ in range(tempfile.TMP_MAX):
            name = next(tempfile._get_candidate_names())  # type: ignore[attr-defined]
            path = os.path.join(directory, prefix + name + suffix)
            try:
                os.mkdir(path)
            except FileExistsError:
                continue
            return path
        raise FileExistsError("no usable temporary directory name found")

    tempfile.mkdtemp = mkdtemp  # type: ignore[assignment]
    tempfile.TemporaryDirectory._mkdtemp = staticmethod(mkdtemp)  # type: ignore[attr-defined]
    _APPLIED = True
