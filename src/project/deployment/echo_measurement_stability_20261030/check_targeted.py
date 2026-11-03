from pathlib import Path
import sys,json,ctypes,struct
import numpy as np
O=Path(__file__).resolve().parent;ROOT=O.parents[1];A=ROOT/'apps/sixmic-desktop';sys.path.insert(0,str(A/'tests/frontend'))
from test_feature_runtime import Harness,words
from ui.features import load_spec
from ui.features.decoder import decode_result
from limit_program import limit_program,install,BASE,OUT,ARENA
spec=load_spec();rows=[]
# The mode selector schedules exactly the selected job, including the time variant.
for fid,count in [('frequency_time_weighting',4),('noise_rating',2)]:
 for i in range(count):
  h=Harness(spec,instrument_mode=True);h.rt.open(fid);assert len(h.workspace()['variants'])==count;h.rt.confirm(fid,'variantIndex',i);h.rt.run(fid);call=h.gw.take('start');p=call['args']['params'];assert call['args']['featureId']==fid
  if fid=='frequency_time_weighting':assert p.get('timeResponse') if i==3 else p['weighting']==['A','C','Z'][i]
  else:assert p['family']==['NR','NC'][i] and p['referenceOffsetDb']==123.01
  assert not h.rt._variant_pending[fid];rows.append({'selectedOnly':fid,'index':i})
h=Harness(spec);h.rt.open('stipa_experimental');h.rt.confirm('stipa_experimental','measurementMode','quick');h.rt.action('stipa_experimental','reference');assert h.gw.take('start')['args']['params']['samples']==144000;rows.append({'quickReferenceButtonSamples':144000})
# New relative-limit ISA runs on the unmodified shared scalar native reference.
fn=ctypes.CDLL(str(ROOT/'deployment/echo_measurement_flow_fix_20261028/room_native.dll')).scalar_native;fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
m=np.zeros(ARENA,np.float32);c,n,meta=limit_program();sp=install(m,(c,n,meta),base=BASE);u=m.view(np.uint32)
for slot in range(4):u[BASE+16*slot+5:BASE+16*slot+7]=[OUT+4096,2050]
u[BASE+9]=512;m[OUT+4096:OUT+4096+1025]=1e-5;m[OUT+4096+1025:OUT+4096+2050]=1e-5;m[OUT+4097]=4e-5;m[OUT+4098]=2.5e-6;m[OUT+4099]=1e-14;m[OUT+4096+1028]=1e-14
for i in range(2000):
 status=ctypes.c_uint();fn(m.ctypes.data,sp['descriptor'],len(m),0,ctypes.byref(status));assert status.value&255==0
 if status.value&0x80000000:break
else:raise AssertionError('limit VM stuck')
a=m[OUT:OUT+n];np.testing.assert_allclose(a[1025:1029],[0,6.0206,-6.0206,0],atol=1e-4);assert list(a[2050:2054])==[0,1,1,0]
basepowers=[struct.unpack('<I',struct.pack('<f',1e-5))[0]]*1025
ref={'words':basepowers};payload={'schema':{'producerLayout':meta},'state':'completed'};chart=decode_result(spec['features']['relative_limit'],payload,u[OUT:OUT+n].tolist(),reference=ref);assert chart['kind']=='statistics';assert chart['panels'][0]['yAxis']['unit']=='dB';assert chart['panels'][1]['yAxis']['label']=='越限状态'
freeze=decode_result(spec['features']['spectrum_freeze'],{'schema':{},'state':'completed'},u[OUT:OUT+3075].tolist(),reference=ref);assert freeze['yAxis']['label']=='功率谱' and freeze['deltaYAxis']['label']!='功率谱';assert len(freeze['series'])==3
capture=decode_result(spec['features']['spectrum_freeze'],{'schema':{},'state':'completed'},basepowers);assert capture['series'][0]['role']=='reference'
rows.append({'limitDbAndFlagsCorrect':True,'noiseFloorNoFalseFlag':True,'freezePowerAndDeltaAxesSeparate':True})
# Compare family curves and displayed levels in the same nominal reference unit.
reg=json.loads((ROOT/'deployment/echo_stipa_quick_20261030/registry/INTERFACE_REGISTRY.json').read_text());nf=next(v for v in reg['features']if v['featureId']=='noise_rating')
for family in ['NC','NR']:
 variant=next(v for v in nf['variants']if v['completeParams']['family']==family and v['completeParams']['channel']==0);plan=json.loads((ROOT/'deployment/echo_interface_guard_20261026/registry'/variant['file']).read_text());meta=plan['service']['metadata'];n=plan['outputWordCount'];a=np.zeros(n,np.float32);a[:3]=[40,1,1];a[31]=123.01;a[32:32+len(meta['centers_hz'])]=-80
 chart=decode_result(spec['features']['noise_rating'],{'schema':{'producerLayout':meta}},a.view(np.uint32).tolist());measured=next(v for v in chart['series']if v['role']=='levels');assert all(abs(y-43.01)<1e-4 for x,y in measured['points']);assert len(chart['series'])==2
 rows.append({'sameNominalUnit':family,'displayLevel':43.01})
(O/'TARGETED_CHECK.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');print('PASS',len(rows),'bounded software checks')
