"""Pack the changed registry files as registry/... for extraction at /opt/echo."""
from pathlib import Path
import hashlib, io, json, tarfile

R = Path(__file__).resolve().parent
REG = R / 'registry'
OUT = R / 'registry_update.tar.gz'
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode='w:gz', compresslevel=6) as tf:
    files = sorted(p for p in REG.rglob('*') if p.is_file())
    for p in files:
        data = p.read_bytes()
        info = tarfile.TarInfo('registry/' + p.relative_to(REG).as_posix())
        info.size = len(data); info.mtime = 0; info.mode = 0o644; info.uid = info.gid = 0
        tf.addfile(info, io.BytesIO(data))
payload = buf.getvalue()
OUT.write_bytes(payload)
report = {'tar': str(OUT), 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload),
          'files': [p.relative_to(REG).as_posix() for p in files]}
(R / 'REGISTRY_TAR.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in report.items() if k != 'files'}))
