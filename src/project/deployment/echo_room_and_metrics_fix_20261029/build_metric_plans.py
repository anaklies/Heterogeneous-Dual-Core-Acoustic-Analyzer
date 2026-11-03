import json,sys,struct,hashlib,copy,shutil
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parent;ROOT=R.parents[1];S=ROOT/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/services';sys.path.insert(0,str(S))
import noise_services as noise
from recorded_time_trace import recorded_time_response,install
BASE=1048576;TABLE=525312;N=4194304;FS=49162010/1024
O=R/'registry';shutil.copytree(ROOT/'deployment/echo_measurement_flow_fix_20261028/registry',O,dirs_exist_ok=True);j=json.loads((O/'INTERFACE_REGISTRY.json').read_text(encoding='utf8'));f=next(x for x in j['features']if x['featureId']=='frequency_time_weighting')
def write(name,plan,m,c,extra=[]):
 u=m.view(np.uint32);u[TABLE:TABLE+64]=u[BASE:BASE+64];ranges=[(TABLE,64),(BASE,64),(BASE+128,len(c.words)*4),(BASE+4352,320)]+extra
 rec=[{'wordOffset':a,'wordCount':n,'words':u[a:a+n].tolist()}for a,n in ranges];plan['patchRecords']=rec;data=bytearray()
 for a,n in ranges:data+=struct.pack('<II',a,n)+u[a:a+n].astype('<u4').tobytes()
 data+=struct.pack('<II',0,0);plan['patchFile']='plans/'+name+'.smp';plan['patchSHA256']=hashlib.sha256(data).hexdigest();(O/plan['patchFile']).write_bytes(data);(O/'plans'/f'{name}.json').write_text(json.dumps(plan,separators=(',',':')),encoding='utf8')
from room_noise_reference import room_ir,install_room
from room_producers import impulse_capture_prepare
import room_services as old_room
import p2_chains as chains
from programs import Code
samples=48000
for fid in ['room_decay','room_clarity','spectral_decay']:
 template=json.loads((O/'plans'/f'{fid}.json').read_text());c,count,meta=room_ir(samples,FS,background_reference=fid!='spectral_decay')
 if fid=='spectral_decay':
  original=json.loads((ROOT/'deployment/echo_interface_guard_20261026/registry/plans/spectral_decay.json').read_text());old_count=len(old_room.room_ir(24000,FS)[0].words);prefix=original['service']['bytecode_instructions']-old_count
  mm=np.zeros(N,np.float32);uu=mm.view(np.uint32)
  for rec in original['patchRecords']:uu[rec['wordOffset']:rec['wordOffset']+rec['wordCount']]=rec['words']
  merged=Code();merged.words=uu[BASE+128:BASE+128+prefix*4].reshape(-1,4).tolist()
  for v in merged.words:
   if v[0]&255==16 and v[1]==24000:v[1]=samples
  for row in c.words:
   v=row.copy();op=v[0]&255
   if op in (16,19):v[2]+=prefix
   elif op==17:v[1]+=prefix
   merged.words.append(v)
  c=merged;meta=dict(original['service']['metadata'],**{k:v for k,v in meta.items() if k in ['samples','decay_offset','fields','validity','background_reference_input']})
 m=np.zeros(N,np.float32);service=install_room(m,(c,count,meta),base=BASE);template.update(service=service,outputWordOffset=service['output'],outputWordCount=count)
 template['privateClearRanges']=[{'wordOffset':BASE,'wordCount':service['output']+32+3*samples-BASE}];write(fid,template,m,c)
 template=json.loads((O/'plans'/f'{fid}_prepare_impulse.json').read_text());pc,pm=impulse_capture_prepare(samples,stimulus_confirmed=True);m=np.zeros(N,np.float32);ps=chains.install(m,(pc,pm),base=BASE);workspace=32+3*samples
 for slot in range(4):m.view(np.uint32)[BASE+slot*16+8]=workspace
 ps['output_words']=workspace;template.update(service=ps,inputWords=3*samples);write(fid+'_prepare_impulse',template,m,pc)
 for e in j['features']:
  if e['featureId']==fid:
   e['params']['samples']['default']=samples
   e['params']['channel']={'default':0,'runtimeInput':True,'range':[0,5]}
   e['experimentalImpulsePreparationPlan'].update(captureSamples=3*samples,searchSamples=2*samples,summary=pm['summary'],onsetPolicy=pm['onsetPolicy'],inputWordOffset=ps['output']+32)
   e['schema']['validity']=meta['validity']
# Existing A routes remain unchanged. Add the missing C/Z × all six channels.
base=json.loads((ROOT/'deployment/echo_interface_guard_20261026/registry/plans/frequency_time_weighting.json').read_text());
for weighting in ['C','Z']:
 for ch in range(6):
  c,n,meta=noise.weighted_level(FS,weighting,ch);meta.update(weighting=weighting,channel=ch);m=np.zeros(N,np.float32);service=noise.install_noise(m,(c,n,meta),base=BASE);plan=copy.deepcopy(base);plan.update(service=service,outputWordOffset=service['output'],outputWordCount=n);name=f'frequency_time_weighting_{weighting}_channel{ch}';write(name,plan,m,c,[(service['output']+3,1025)])
  f['variants'].append({'completeParams':{'sample_rate':FS,'weighting':weighting,'channel':ch},'file':'plans/'+name+'.json','patchFile':'plans/'+name+'.smp'})
old=json.loads((ROOT/'deployment/echo_interface_guard_20261026/registry/plans/frequency_time_weighting_recorded.json').read_text());spec=recorded_time_response(48000,FS,True);m=np.zeros(N,np.float32);service=install(m,spec,base=BASE);old.update(service=service,outputWordOffset=service['output'],outputWordCount=service['output_words']);write('frequency_time_weighting_recorded',old,m,spec[0])
for e in j['features']:
 if e['featureId']in ['room_decay','room_clarity','spectral_decay']:e['params']['channel']={'default':0,'runtimeInput':True,'range':[0,5]}
j['metricFixRevision']='20261029-time-traces-auto-input';(O/'INTERFACE_REGISTRY.json').write_text(json.dumps(j,ensure_ascii=False,indent=2),encoding='utf8');print('METRIC_PLANS_BUILT',len(list((O/'plans').glob('*.smp'))))
