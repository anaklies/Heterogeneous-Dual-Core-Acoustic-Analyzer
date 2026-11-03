from pathlib import Path
import sys,urllib.request,gzip,hashlib,struct,zlib,json
R=Path(__file__).resolve().parent;ROOT=R.parents[1];sys.path.insert(0,str(ROOT/'deployment'))
from firmware_formats_20261012 import read_fdt,write_fdt,read_cpio,write_cpio
u=urllib.request.build_opener(urllib.request.ProxyHandler({}));old=R/'before/image.ub';print('Reading current SD image',flush=True)
with u.open('http://192.168.77.2:48093/image.ub',timeout=10) as r,old.open('wb') as f:
 while True:
  b=r.read(1024*1024)
  if not b:break
  f.write(b)
source=old.read_bytes();tree,res,cpu=read_fdt(source);images=tree.child('images');ram=next(n for n in images.children if n.properties.get('type')==b'ramdisk\0');entries=read_cpio(gzip.decompress(ram.properties['data']));unchanged={n.name:hashlib.sha256(n.properties.get('data',b'')).hexdigest() for n in images.children if n is not ram}
for p in (R/'registry').rglob('*'):
 if not p.is_file():continue
 name='opt/echo/registry/'+p.relative_to(R/'registry').as_posix();entries[name]={'fields':[0,0o100644,0,0,1,0,0,0,0,0,0,0,0],'data':p.read_bytes()}
ram.properties['data']=gzip.compress(write_cpio(entries),compresslevel=6,mtime=0)
for n in images.children:
 if 'data' in n.properties:
  for h in n.children:
   if h.name.startswith('hash'):
    a=h.properties['algo'].rstrip(b'\0').decode();b=n.properties['data'];h.properties['value']=struct.pack('>I',zlib.crc32(b)) if a=='crc32' else hashlib.new(a,b).digest()
output=write_fdt(tree,res,cpu);(R/'image.ub').write_bytes(output);assert unchanged=={n.name:hashlib.sha256(n.properties.get('data',b'')).hexdigest() for n in images.children if n is not ram}
report={'sourceSHA256':hashlib.sha256(source).hexdigest(),'imageSHA256':hashlib.sha256(output).hexdigest(),'bytes':len(output),'bitstreamChanged':False,'kernelAndDTBUnchanged':True,'registryFiles':len([p for p in (R/'registry').rglob('*') if p.is_file()])};(R/'SD_PATCH.json').write_text(json.dumps(report,indent=2));print(report,flush=True)
