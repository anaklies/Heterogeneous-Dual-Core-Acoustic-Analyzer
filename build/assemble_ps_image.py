"""Reassemble an explicit FIT baseline. No board writes; delivered baseline is immutable."""
from pathlib import Path, PurePosixPath
import argparse,sys,json,gzip,hashlib,struct,zlib
P=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(P/'src/project/deployment'))
from firmware_formats_20261012 import read_fdt,write_fdt,read_cpio,write_cpio
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
    a=argparse.ArgumentParser();a.add_argument('--baseline',type=Path,default=P/'board/sd/image.ub');a.add_argument('--output',type=Path);a.add_argument('--replace',action='append',default=[],metavar='CPIO_PATH=LOCAL_FILE');a.add_argument('--inspect',action='store_true');n=a.parse_args()
    source=n.baseline.read_bytes();tree,res,cpu=read_fdt(source);images=tree.child('images')
    if images is None:raise ValueError('not a FIT image')
    if any(c.name.startswith('signature') for c in tree.children+images.children):raise ValueError('signed FIT needs the original signing process')
    rams=[x for x in images.children if x.properties.get('type',b'').rstrip(b'\0')==b'ramdisk']
    if len(rams)!=1:raise ValueError('expected one ramdisk')
    ram=rams[0]
    if any(c.name.startswith('signature') for node in images.children for c in node.children):raise ValueError('signed FIT unsupported')
    entries=read_cpio(gzip.decompress(ram.properties['data']))
    before={k:sha(v['data']) for k,v in entries.items()};other={x.name:sha(x.properties.get('data',b'')) for x in images.children if x is not ram}
    report={'baselineSHA256':sha(source),'ramdiskEntries':len(entries),'otherImageSHA256':other,'changedEntries':[]}
    if n.inspect:
        if n.replace or n.output:raise ValueError('inspect is read-only')
        print(json.dumps(report,indent=2));return
    if not n.output or not n.replace:raise ValueError('output and at least one explicit replacement required')
    if n.output.resolve()==n.baseline.resolve() or n.output.exists():raise ValueError('choose a new output path')
    changed=set()
    for spec in n.replace:
        key,sep,path=spec.partition('=');q=PurePosixPath(key)
        if not sep or q.is_absolute() or '..' in q.parts or not key.startswith('opt/echo/') or key not in entries or key in changed:raise ValueError('invalid/duplicate existing opt/echo entry: '+key)
        body=Path(path).read_bytes()
        if key.startswith('opt/echo/bin/') and (body[:5]!=b'\x7fELF\x01' or len(body)<20 or struct.unpack_from('<H',body,18)[0]!=40):raise ValueError('expected ELF32 ARM binary')
        if key.endswith('INTERFACE_REGISTRY.json'):
            reg=json.loads(body);features=reg.get('features',[])
            if len(features)!=45:raise ValueError('final registry must contain 45 features')
        entries[key]={'fields':list(entries[key]['fields']),'data':body};changed.add(key)
    ram.properties['data']=gzip.compress(write_cpio(entries),compresslevel=6,mtime=0)
    for node in images.children:
        if 'data' not in node.properties:continue
        for h in node.children:
            if h.name.startswith('hash'):
                algo=h.properties['algo'].rstrip(b'\0').decode();body=node.properties['data']
                h.properties['value']=struct.pack('>I',zlib.crc32(body)) if algo=='crc32' else hashlib.new(algo,body).digest()
    output=write_fdt(tree,res,cpu);tree2,_,_=read_fdt(output);im2=tree2.child('images')
    assert other=={x.name:sha(x.properties.get('data',b'')) for x in im2.children if x.name!=ram.name}
    r2=next(x for x in im2.children if x.name==ram.name);e2=read_cpio(gzip.decompress(r2.properties['data']))
    assert set(e2)==set(entries)
    assert all(sha(e2[k]['data'])==(sha(entries[k]['data']) if k in changed else v) for k,v in before.items())
    report.update({'outputSHA256':sha(output),'changedEntries':sorted(changed),'kernelAndOtherImagesUnchanged':True,'untouchedCpioEntriesUnchanged':True})
    n.output.parent.mkdir(parents=True,exist_ok=True);n.output.write_bytes(output)
    n.output.with_suffix(n.output.suffix+'.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
