"""Write probe used by build_backend_check.ps1 New-ScratchRoot.

The host sandbox may deny python-child writes outside the workspace; the build
wrapper calls this to pick a scratch/TEMP root that the frozen app can actually
write to. Usage: python scratch_write_probe.py <directory>
Exit 0 + "probe-ok" when writable.
"""
import pathlib
import sys

target = pathlib.Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
probe = target / "py-write-probe"
probe.write_text("ok", encoding="utf-8")
probe.unlink()
print("probe-ok")
