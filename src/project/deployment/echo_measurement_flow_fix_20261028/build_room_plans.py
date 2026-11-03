import sys,json,struct,hashlib,copy
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parent;ROOT=R.parents[1];S=ROOT/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/services';sys.path.insert(0,str(S))
import room_services as old
from room_noise_compensated import room_ir,install_room
from impulse_producers import impulse_capture_prepare
import p2_chains as chains
BASE=1048576;TABLE=525312;N=4194304;FS=49162010/1024
O=R/'registry';(O/'plans').mkdir(parents=True,exist_ok=True);catalog=json.loads((ROOT/'deployment/echo_interface_guard_20261026/registry/INTERFACE_REGISTRY.json').read_text(encoding='utf-8'));rows=catalog.get('features',[])
def write(fid,plan,m,code,workspace=None):
 u=m.view(np.uint32);u[TABLE:TABLE+64]=u[BASE:BASE+64]
 if workspace:
  for slot in range(4):u[BASE+slot*16+8]=workspace
  u[TABLE:TABLE+64]=u[BASE:BASE+64]
 ranges=[(TABLE,64),(BASE,64),(BASE+128,len(code.words)*4),(BASE+4352,320)]
 records=[{'wordOffset':a,'wordCount':n,'words':u[a:a+n].tolist()} for a,n in ranges];plan['patchRecords']=records
 data=bytearray()
 for a,n in ranges:data+=struct.pack('<II',a,n)+u[a:a+n].astype('<u4').tobytes()
 data+=struct.pack('<II',0,0);name=f'plans/{fid}.smp';(O/name).write_bytes(data);plan['patchFile']=name;plan['patchSHA256']=hashlib.sha256(data).hexdigest();(O/f'plans/{fid}.json').write_text(json.dumps(plan,separators=(',',':')),encoding='utf-8');return plan
for fid in ['room_decay','room_clarity','spectral_decay']:
 oldplan=json.loads((ROOT/f'deployment/echo_interface_guard_20261026/registry/plans/{fid}.json').read_text());spec=room_ir(24000,FS);c,count,meta=spec
 if fid=='spectral_decay':
  from programs import Code
  total=oldplan['service']['bytecode_instructions'];oldn=len(old.room_ir(24000,FS)[0].words);prefix=total-oldn
  mem=np.zeros(N,np.float32);u=mem.view(np.uint32)
  for rec in oldplan['patchRecords']:u[rec['wordOffset']:rec['wordOffset']+rec['wordCount']]=rec['words']
  merged=Code();merged.words=u[BASE+128:BASE+128+prefix*4].reshape(-1,4).tolist()
  for row in c.words:
   v=row.copy();op=v[0]&255
   if op in (16,19):v[2]+=prefix
   elif op==17:v[1]+=prefix
   merged.words.append(v)
  c=merged;meta=dict(oldplan['service']['metadata'],**{k:v for k,v in meta.items() if k in ['fields','validity']})
 mem=np.zeros(N,np.float32);service=install_room(mem,(c,count,meta),base=BASE);plan=copy.deepcopy(oldplan);plan['service']=service;plan['outputWordCount']=count;plan['outputWordOffset']=service['output'];write(fid,plan,mem,c)
 prepold=json.loads((ROOT/f'deployment/echo_interface_guard_20261026/registry/plans/{fid}_prepare_impulse.json').read_text());pc,pm=impulse_capture_prepare(24000,stimulus_confirmed=True);mem=np.zeros(N,np.float32);ps=chains.install(mem,(pc,pm),base=BASE);ps['output_words']=48032;prepold['service']=ps;write(fid+'_prepare_impulse',prepold,mem,pc,48032)
 for e in rows:
  if e.get('featureId')==fid:
   e['schema'].pop('actualProducerLayout',None);e['schema']['validity']=meta['validity']
   if e.get('experimentalImpulsePreparationPlan'):e['experimentalImpulsePreparationPlan'].update(peakMinimumFS=1e-4,blockSamples=96,blockMeanRatio=8,minimumEffectiveSamples=6,summary=pm['summary'],onsetPolicy=pm['onsetPolicy'],limitations=pm['limitations'])
   e['experimentalImpulsePreparationPlan'].pop('minimumCrest',None);e['experimentalImpulsePreparationPlan'].pop('thresholdFraction',None);e['experimentalImpulsePreparationPlan']['thresholdParameterPolicy']='fixed concentrated block gate, not a single sample crossing'
(O/'INTERFACE_REGISTRY.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8');print('ROOM_PLANS_BUILT',len(list((O/'plans').glob('*.smp'))))
