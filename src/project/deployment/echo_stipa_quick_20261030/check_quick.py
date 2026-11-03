import ctypes,json,sys
from pathlib import Path
import numpy as np
import quick_program as q
O=Path(__file__).resolve().parent
fn=ctypes.CDLL(str(q.ROOT/'deployment/echo_measurement_flow_fix_20261028/room_native.dll')).scalar_native;fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
def execute(m,c):
 sp=q.old.install_stage(m,c,q.old.layout(q.N),base=q.BASE);m.view(np.uint32)[q.BASE+9]=512
 for i in range(10000):
  status=ctypes.c_uint();fn(m.ctypes.data,sp['descriptor'],len(m),0,ctypes.byref(status));assert status.value&255==0,hex(status.value)
  if status.value&0x80000000:return
 raise AssertionError('bounded unit test exhausted')
rows=[];m=np.zeros(q.ARENA,np.float32);layout=q.old.layout(q.N);out=q.OUT;t=(np.arange(q.N//q.DEC)+.5)/200
for b in q.BANDS:
 X=np.column_stack([np.ones(len(t)),t-t[60:-60].mean(),*[v for f in q.old.PAIRS[b] for v in (np.sin(2*np.pi*f*t),np.cos(2*np.pi*f*t))]])
 coeff=np.array([.1,.001,.04,.01,.02,.01]);m[out+2*q.N:out+2*q.N+len(t)]=(X@coeff).astype(np.float32);w=q.weights(b).ravel();m[out+3*q.N:out+3*q.N+len(w)]=w;execute(m,q.joint(b,0));a=m[out+layout['result']+48+b*6:out+layout['result']+54+b*6];np.testing.assert_allclose(a,coeff,atol=2e-6)
 rows.append({'unit':'joint_fit','band':b,'maxAbsoluteError':float(np.max(abs(a-coeff)))})
for ratio in [1.,.5]:
 m.fill(0);m[out+layout['result']+31]=1
 for b in q.BANDS:
  for tr in [0,1]:
   m[out+layout['result']+32+2*b+tr]=.01
   a=out+layout['result']+48+tr*42+b*6;m[a]=.1;m[a+2]=.05*(ratio if tr else 1);m[a+4]=.05*(ratio if tr else 1)
 execute(m,q.final());assert m[out+1]==1;assert abs(float(m[out])-ratio)<1e-5
 rows.append({'unit':'quick_index','inputMTF':ratio,'index':float(m[out]),'valid':bool(m[out+1])})
m[out+layout['result']+31]=0;execute(m,q.final());assert m[out+1]==0;rows.append({'unit':'invalid_capture_rejected','valid':False})
g=json.loads((O/'registry/plans/stipa_quick.json').read_text());assert len(g['stages'])==15
import hashlib
for stage in g['stages']:
 p=json.loads((O/'registry'/stage['plan']).read_text());assert hashlib.sha256((O/'registry'/p['patchFile']).read_bytes()).hexdigest()==p['patchSHA256'];assert p['service']['output']+p['workspace']['words']<=q.ARENA
 if stage['weightPage']:
  wp=stage['weightPage'];raw=(O/'registry/plans'/wp['file']).read_bytes();assert len(raw)==4*wp['wordCount'] and hashlib.sha256(raw).hexdigest()==wp['sha256']
rows.append({'unit':'all15_plans_load_and_hash','pass':True})
(O/'QUICK_SOFTWARE_CHECK.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows,indent=2))
