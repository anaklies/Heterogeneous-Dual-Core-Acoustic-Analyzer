"""Fast static plan coverage, binary consistency and private-write checks."""
from pathlib import Path
import csv,hashlib,json,struct
HERE=Path(__file__).resolve().parent

def check():
 registry=json.loads((HERE/'REGISTRY.json').read_text(encoding='utf-8'))
 ids={r['id'] for r in csv.DictReader((HERE.parents[2]/'deployment/releases/SixMic3D_PL_Analysis_RC1_RecoveryFix_20261024/FUNCTION_EXECUTION_MAP.csv').open(encoding='utf-8-sig'))}-{'srpdnn_main'}
 assert ids=={r['featureId'] for r in registry['features']} and len(ids)==51
 binaries=0;instructions=0;weights={}
 for path in (HERE/'plans').glob('*.json'):
  plan=json.loads(path.read_text(encoding='utf-8'))
  if 'weightPage' in plan and plan['weightPage'].get('materialized'):
   w=plan['weightPage'];weight=path.parent/w['file'];assert weight.stat().st_size==4*w['wordCount'];assert hashlib.sha256(weight.read_bytes()).hexdigest()==w['sha256'];weights[w['file']]=weight.stat().st_size
  if 'patchFile' not in plan:continue
  data=(HERE/plan['patchFile']).read_bytes();assert hashlib.sha256(data).hexdigest()==plan['patchSHA256'];pos=0;actual=[]
  while True:
   a,n=struct.unpack_from('<II',data,pos);pos+=8
   if (a,n)==(0,0):break
   assert (a==525312 and n==64)or 1048576<=a<a+n<=4194304
   words=list(struct.unpack_from('<'+'I'*n,data,pos));pos+=n*4;actual.append(dict(wordOffset=a,wordCount=n,words=words))
  assert pos==len(data) and actual==plan['patchRecords'];binaries+=1
  table=next(r for r in actual if r['wordOffset']==525312)['words']
  assert len(table)==64 and all(table[i]==0x414c5531 for i in range(0,64,16))
  n=table[3];assert 1<=n<=1024;instructions+=n
  image={r['wordOffset']+i:v for r in actual for i,v in enumerate(r['words'])}
  code=[image.get(table[2]+i,0) for i in range(4*n)]
  if plan.get('producer')=='producers.noise_rating':
   meta=plan['service']['metadata'];assert all(0<=a<b<=1025 for a,b in meta['bin_ranges'])
   assert len(meta['bin_ranges'])==len(meta['centers_hz'])
   assert meta['runtimeInput']['referenceConfirmed']['default']==0
   assert meta['runtimeInput']['referenceOffsetDb']['wordOffsetRelativeToOutput']==31
   assert meta['calibratedSPL'] is False and meta['nominalEstimate'] is True
   assert any(code[4*k]&255==2 and (code[4*k]>>8)&31==2 and code[4*k+1:4*k+3]==[31,2] for k in range(n)),path
  if plan.get('producer')=='producers.managed_local_das':
   meta=plan['service']['metadata'];assert meta['noCpuTrig'] is True
   for off in (0,1):assert any(code[4*k]&255==2 and (code[4*k]>>13)&31==3 and code[4*k+1:4*k+3]==[off,2] for k in range(n)),(path,off)
   assert meta['first_bin']==1 and meta['bins']==128
  for k in range(n):
   op=code[4*k]&255
   if op in (16,19):assert code[4*k+2]<n,(path,k,'branch outside code')
   if op==17:assert code[4*k+1]<n,(path,k,'jump outside code')
  for clear in plan.get('privateClearRanges',[]):assert 1048576<=clear['wordOffset']<clear['wordOffset']+clear['wordCount']<=4194304
 for row in registry['features']:
  prep_ref=row.get('acquisitionPreparationPlan')
  if prep_ref:
   preparation=json.loads((HERE/prep_ref['file']).read_text(encoding='utf-8'))
   for key in ('inputWords','inputWordOffset'):
    assert isinstance(prep_ref.get(key),int) and prep_ref[key]>0,(row['featureId'],key,'required acquisition metadata')
    assert prep_ref[key]==preparation[key],(row['featureId'],key,'preparation reference mismatch')
  assert row['schema']['fields'] and row['schema']['axes'],row['featureId']
  assert (HERE/row['executionPlan']['file']).is_file()
 evidence=dict(features=len(ids),binaryPlans=binaries,staticInstructions=instructions,stipaWeightFiles=len(weights),stipaWeightBytes=sum(weights.values()),protectedP0AndP1Writes=0,allBranchesInBounds=True,noDspExecuted=True,hardwareAccepted=False)
 (HERE/'STATIC_CHECK.json').write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence))
 return evidence

if __name__=='__main__':check()
