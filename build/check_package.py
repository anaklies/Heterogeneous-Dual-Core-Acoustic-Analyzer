from pathlib import Path
import hashlib,json,zipfile
P=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
bad=[];rows=json.loads((P/'build/FILES_SHA256.json').read_text(encoding='utf-8'))
for r in rows:
 p=P/r['path']
 if not p.is_file() or sha(p)!=r['sha256']:bad.append(r['path'])
reg=json.loads((P/'src/project/deployment/echo_interface_guard_20261026/registry/INTERFACE_REGISTRY.json').read_text(encoding='utf-8'))
assert len(reg['features'])==45
assert not bad,bad
print('PACKAGE_INTEGRITY_PASS',len(rows),'files; active features=45')
