"""Pack the spatial-off registry as registry/INTERFACE_REGISTRY.json for /opt/echo.

Deterministic tar.gz: tar mtime 0, gzip mtime 0, so registry_update.tar.gz has a
stable sha256 that deploy_board.sh can pin.
"""
from pathlib import Path
import gzip, hashlib, io, json, tarfile

R = Path(__file__).resolve().parent
REG = R / 'registry'
OUT = R / 'registry_update.tar.gz'


def main():
    files = sorted(p for p in REG.rglob('*') if p.is_file())
    if not files:
        raise SystemExit('registry directory is empty')
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for path in files:
            data = path.read_bytes()
            info = tarfile.TarInfo('registry/' + path.relative_to(REG).as_posix())
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            tar.addfile(info, io.BytesIO(data))
    payload = gzip.compress(buf.getvalue(), compresslevel=6, mtime=0)
    OUT.write_bytes(payload)
    report = {
        'tar': 'registry_update.tar.gz',
        'tarBytes': len(payload),
        'sha256': hashlib.sha256(payload).hexdigest(),
        'extractTo': '/opt/echo',
        'files': ['registry/' + p.relative_to(REG).as_posix() for p in files],
        'tarLayout': 'entries are registry/<path>, extract with tar -xzf ... -C /opt/echo',
        'boardTarget': '/opt/echo/registry/INTERFACE_REGISTRY.json',
        'boardTargetSHA256': hashlib.sha256(files[0].read_bytes()).hexdigest(),
    }
    (R / 'REGISTRY_TAR.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
