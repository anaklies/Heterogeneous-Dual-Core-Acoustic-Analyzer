"""Freeze one accepted RC2, without changing the RC1 release."""
from pathlib import Path
import csv, hashlib, json, re, shutil, zipfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[4]
BASE=ROOT/'deployment/releases/SixMic3D_PL_Analysis_RC1_20261024'
OUT=ROOT/'deployment/releases/SixMic3D_PL_Analysis_RC2_20261024'
REPORTS=ROOT/'tmp/p27_area_board/reports'

def sha(p):
    d=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): d.update(b)
    return d.hexdigest()

def cp(a,b):
    b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(a,b)

def main():
    log=(HERE/'build_rc2.log').read_text(errors='replace')
    if '\nRC2_BIT_XSA_ARCHIVE_DONE\n' not in log.replace('\r',''):
        raise SystemExit('RC2 generation not complete; keep RC1')
    eq=(HERE/'equivalence.log').read_text();chain=(HERE/'event_chain.log').read_text()
    if 'FEATURE_EQ_PASS' not in eq or 'EVENT_CHAIN_PASS' not in chain or 'Fatal:' in eq+chain:
        raise SystemExit('Affected regression did not pass')
    u=(REPORTS/'utilization.rpt').read_text()
    def use(label):
        m=re.search(r'^\|\s*'+re.escape(label)+r'\s*\|\s*([\d.]+)',u,re.M)
        if not m:raise SystemExit('Missing utilization '+label)
        v=float(m[1]);return int(v) if v.is_integer() else v
    text=(REPORTS/'timing.rpt').read_text()
    m=re.search(r'WNS\(ns\).*?\n\s*-.*?\n\s*([\d.-]+)\s+([\d.-]+)\s+\d+\s+\d+\s+([\d.-]+)\s+([\d.-]+)',text,re.S)
    if not m:raise SystemExit('Missing timing')
    wns,tns,whs,ths=map(float,m.groups())
    c=[0,0,0,0]
    for line in (REPORTS/'cdc.rpt').read_text().splitlines():
        m=re.search(r'(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$',line)
        if m and line.startswith(('Warning','Info','Critical')):
            c=[a+int(b) for a,b in zip(c,m.groups()[:4])]
    if min(wns,whs)<0 or tns or ths or c[2] or c[3]:raise SystemExit('Timing/CDC gate failed')
    if use('Slice LUTs')>39137 or use('Slice')>13014:raise SystemExit('No significant gain')
    for folder in ['source','sdk','lcd','profiles']:
        shutil.copytree(BASE/folder,OUT/folder,dirs_exist_ok=True)
    shutil.copytree(BASE/'hardware/hls_ip',OUT/'hardware/hls_ip',dirs_exist_ok=True)
    shutil.copytree(BASE/'evidence',OUT/'evidence/inherited_rc1',dirs_exist_ok=True)
    # Keep the current implementation reports distinct from inherited RC1 evidence.
    for p in REPORTS.glob('*.rpt'):cp(p,OUT/'evidence/implementation'/p.name)
    cp(ROOT/'tmp/p27_area_board/routed.dcp',OUT/'hardware/routed.dcp')
    for p in HERE.iterdir():
        if p.is_file() and p.suffix in {'.sv','.py','.tcl','.md','.log','.dat'}:
            cp(p,OUT/'source'/p.relative_to(ROOT))
    canonical=OUT/'source'/HERE.parent.relative_to(ROOT)/'control/fft_event_features.sv'
    cp(HERE/'fft_event_features.sv',canonical)
    if sha(HERE/'stream_fft2048_HANN2048_ROM_AUTO_1R.dat')!='3f5f15dc763556adbb48be828365deb2a18f0bf030f23bf4c0bf5cb1c1e1c7e4':
        raise SystemExit('Hann coefficient fingerprint mismatch')
    for version in ['baseline','candidate']:
        cp(ROOT/f'tmp/p26_feature_area/{version}_utilization.rpt',OUT/'evidence/optimization'/f'{version}_utilization.rpt')
    for name in ['equivalence.log','event_chain.log','build_rc2.log','RESEARCH_AND_DECISION.md']:
        cp(HERE/name,OUT/'evidence/optimization'/name)
    m=json.loads((BASE/'RUNTIME_CANDIDATE.json').read_text(encoding='utf-8'))
    previous=dict(m['resources'])
    m.update(candidate='analysis-rc2-20261024',baselineRC1Resources=previous,
             engineeringBaselineFrozen=True,freezeDate='2026-10-24',s7Complete=False,
             releaseStatus='ENGINEERING_RC',physicalBoardTested=False)
    m['resources'].update(LUT=use('Slice LUTs'),LUTpercent=round(use('Slice LUTs')/53200*100,2),
       FF=use('Slice Registers'),Slice=use('Slice'),SlicePercent=round(use('Slice')/13300*100,2),
       DSP=use('DSPs'),BRAM36Equivalent=use('Block RAM Tile'),controlSets=use('Unique Control Sets'),
       WNSns=wns,TNSns=tns,WHSns=whs,THSns=ths,CDCendpoints=c[0],CDCsafe=c[1],CDCunsafe=c[2],CDCunknown=c[3])
    m['optimization']={'baseline':'frozen RC1','changedModule':'fft_event_features',
        'technique':'bounded band time multiplexing, exact 45-bit accumulation, distributed storage',
        'LUTsaved':40137-use('Slice LUTs'),'FFsaved':42117-use('Slice Registers'),
        'SliceSaved':13114-use('Slice'),'precisionReduced':False,'otherAlgorithmsChanged':False,
        'directiveSearch':False,'furtherOptimization':False}
    m['validation']['featureDifferentialCases']=8
    m['validation']['featureMaxMeasuredModelCycles']=84688
    m['validation']['featureBudgetModelCycles']=200000
    m['validation']['eventRecorderJointRTL_AfterOptimization']=True
    (OUT/'RUNTIME_CANDIDATE.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    cp(BASE/'DATA_AND_SCHEDULING.md',OUT/'DATA_AND_SCHEDULING.md')
    p=BASE/'FUNCTION_EXECUTION_MAP.csv'
    with p.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
    for row in rows:row['integrationStatus']=row['integrationStatus'].replace('RC1','RC2')
    with (OUT/p.name).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    readme=(BASE/'README_交付说明.md').read_text(encoding='utf-8').split('## 本次实际验收结果')[0]
    readme=readme.replace('RC1','RC2').replace('_rc1.','_rc2.')
    readme+=f'''## 本次RC2实际结果

仅事件特征处理改用时间复用；全部算法、单位、接口及结果舍入规则不变。8项新旧直接差分及受影响事件联合测试通过，其余继承RC1证据，没有逐帧长仿真。

|项目|RC1|RC2|
|---|---:|---:|
|LUT|40137|{use('Slice LUTs')}|
|FF|42117|{use('Slice Registers')}|
|Slice|13114|{use('Slice')}|
|DSP|88|{use('DSPs')}|
|BRAM36等价|57.5|{use('Block RAM Tile')}|
|WNS(ns)|0.149|{wns}|
|WHS(ns)|0.036|{whs}|

TNS/THS为0；CDC Unsafe/Unknown为0。新XSA内嵌bit与独立bit核对一致。外部电气时序边界、实物测试与Linux适配限制保持不变，不因优化而宣称通过。研究依据与复现细节见evidence/optimization/RESEARCH_AND_DECISION.md。旧RC1保留不变。
'''
    (OUT/'README_交付说明.md').write_text(readme,encoding='utf-8')
    with zipfile.ZipFile(OUT/'hardware/sixmic_analysis_rc2.xsa') as z:
        bits=[n for n in z.namelist() if n.endswith('.bit')]
        if len(bits)!=1 or hashlib.sha256(z.read(bits[0])).hexdigest()!=sha(OUT/'hardware/sixmic_analysis_rc2.bit'):
            raise SystemExit('XSA bit mismatch')
        if z.testzip():raise SystemExit('XSA corruption')
    with zipfile.ZipFile(OUT/'hardware/recoverable_project.zip') as z:
        names=[n for n in z.namelist() if n.endswith('/fft_event_features.sv')]
        expected=sha(HERE/'fft_event_features.sv')
        if not any(hashlib.sha256(z.read(n)).hexdigest()==expected for n in names):
            raise SystemExit('New source absent from recovery archive')
        dats=[n for n in z.namelist() if n.endswith('/stream_fft2048_HANN2048_ROM_AUTO_1R.dat')
              and n[:-4]+'.v' in z.namelist()]
        if not dats or not any(hashlib.sha256(z.read(n)).hexdigest()==sha(HERE/'stream_fft2048_HANN2048_ROM_AUTO_1R.dat') for n in dats):
            raise SystemExit('Hann initialization absent beside actual ROM source in recoverable project')
        if z.testzip():raise SystemExit('Project archive corruption')
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name!='SHA256SUMS.txt')
    (OUT/'SHA256SUMS.txt').write_text(''.join(f'{sha(p)}  {p.relative_to(OUT).as_posix()}\n' for p in files),encoding='utf-8')
    for line in (OUT/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        checksum,name=line.split('  ',1)
        if sha(OUT/name)!=checksum:raise SystemExit('Hash verification failed '+name)
    print('RC2_FREEZE_PASS',len(files),json.dumps(m['resources']))

if __name__=='__main__':main()
