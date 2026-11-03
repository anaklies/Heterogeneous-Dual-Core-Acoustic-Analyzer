from pathlib import Path
import argparse, json, math, hashlib, re

def compare(a,b,atol=0.0,rtol=0.0,path='$'):
    if isinstance(a,list) or isinstance(b,list):
        if not isinstance(a,list) or not isinstance(b,list) or len(a)!=len(b):
            raise ValueError(f'{path}: shape mismatch')
        for i,(x,y) in enumerate(zip(a,b)):compare(x,y,atol,rtol,f'{path}[{i}]')
        return
    if type(a) not in (int,float) or type(b) not in (int,float):raise ValueError(f'{path}: nonnumeric')
    if isinstance(a,int) and isinstance(b,int):
        if a!=b:raise ValueError(f'{path}: integer mismatch')
        return
    if not math.isfinite(a) or not math.isfinite(b):raise ValueError(f'{path}: nonfinite')
    if abs(a-b)>atol+rtol*abs(b):raise ValueError(f'{path}: numeric mismatch')

def words(p):
    tokens=p.read_text(encoding='utf-8-sig').split()
    if not tokens:raise ValueError('empty word file')
    if any(not re.fullmatch(r'(?:0[xX])?[0-9a-fA-F]{1,8}',s) for s in tokens):raise ValueError('invalid 32-bit hex word')
    return [int(s,16) for s in tokens]

def manifest(root,rows):
    root=root.resolve();seen=set()
    for r in rows:
        p=Path(r['path']);q=(root/p).resolve()
        if p.is_absolute() or not q.is_relative_to(root) or q==root:raise ValueError('unsafe path')
        if q in seen:raise ValueError('duplicate path')
        seen.add(q)
        if not re.fullmatch('[0-9a-fA-F]{64}',r['sha256']):raise ValueError('invalid SHA256')
        h=hashlib.sha256()
        with q.open('rb') as f:
            for block in iter(lambda:f.read(1048576),b''):h.update(block)
        if h.hexdigest()!=r['sha256'].lower():raise ValueError(f'hash mismatch: {p}')
    if not seen:raise ValueError('empty manifest')
    return len(seen)

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True)
    c=s.add_parser('compare');c.add_argument('--actual',type=Path,required=True);c.add_argument('--reference',type=Path,required=True);c.add_argument('--format',choices=['json','hex'],default='json');c.add_argument('--atol',type=float,default=0);c.add_argument('--rtol',type=float,default=0)
    m=s.add_parser('manifest');m.add_argument('--root',type=Path,required=True);m.add_argument('--manifest',type=Path,required=True)
    a=p.parse_args()
    try:
        if a.cmd=='manifest':n=manifest(a.root,json.loads(a.manifest.read_text(encoding='utf-8-sig')));print('MANIFEST_PASS',n)
        else:
            if not math.isfinite(a.atol) or not math.isfinite(a.rtol) or a.atol<0 or a.rtol<0:raise ValueError('invalid tolerance')
            if a.format=='hex' and (a.atol or a.rtol):raise ValueError('hex comparison is exact')
            read=words if a.format=='hex' else lambda q:json.loads(q.read_text(encoding='utf-8-sig'))
            compare(read(a.actual),read(a.reference),a.atol,a.rtol);print('COMPARE_PASS')
    except (ValueError,OSError,KeyError,TypeError,OverflowError) as e:
        print('FAIL:',str(e));return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
