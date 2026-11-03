import sys,ctypes,json,math
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parent;S=R.parents[1]/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/services';sys.path.insert(0,str(S))
import room_noise_reference as room
import room_producers as prep
import p2_chains as chains
import recorded_time_trace as timing
fn=ctypes.CDLL(str(R.parents[1]/'deployment/echo_measurement_flow_fix_20261028/room_native.dll')).scalar_native;fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
def execute(m,sp):
 for _ in range(500000):
  st=ctypes.c_uint();fn(m.ctypes.data,sp['descriptor'],len(m),0,ctypes.byref(st));assert st.value&255==0,hex(st.value)
  if st.value&0x80000000:return m[sp['output']:sp['output']+sp['output_words']].copy()
 raise AssertionError('VM did not finish')
rng=np.random.default_rng(2902);n=48000;fs=48000;rows=[]
x=.15*rng.normal(size=n)*np.exp(-math.log(1000)*np.arange(n)/fs/.4)+rng.normal(0,.0001,n);m=np.zeros(1500000,np.float32);sp=room.install_room(m,room.room_ir(n,fs),base=1048576,ir=x);m[sp['output']+29]=.0001;m.view(np.uint32)[sp['output']+30]=0x4e4f4953;a=execute(m,sp);fits=[float(a[i])if a[i+2] else None for i in [10,16,22]];assert fits[1] and abs(fits[1]-.4)<.04;rows.append({'case':'room_noise_reference','fits':fits,'noise_power':float(a[9])})
# A narrow late pulse must be accepted, not discarded as a six-sample spike.
x=rng.normal(0,.00005,3*n);x[72000:72002]+=[.2,-.1];c,meta=prep.impulse_capture_prepare(n,stimulus_confirmed=True);m=np.zeros(1600000,np.float32);sp=chains.install(m,(c,meta),base=1048576);u=m.view(np.uint32);u[sp['output']+32:sp['output']+32+len(x)]=np.rint(x*8388608).astype(np.int32).view(np.uint32)
for slot in range(4):u[1048576+slot*16+8]=32+len(x)
sp['output_words']=32+len(x);a=execute(m,sp);assert a[30]==1 and abs(int(a[:32].view(np.uint32)[28])-72000)<3;rows.append({'case':'late_narrow_pulse','onset':int(a[:32].view(np.uint32)[28]),'valid':bool(a[30])})
spec=timing.recorded_time_response(n,fs,True);m=np.zeros(1500000,np.float32);sp=timing.install(m,spec,base=1048576);x=.1*np.sin(2*np.pi*1500*np.arange(n)/fs);m.view(np.uint32)[sp['output']+32:sp['output']+32+n]=np.rint(x*8388608).astype(np.int32).view(np.uint32);a=execute(m,sp);trace=a[32+n:].reshape(-1,3);assert len(trace)==100;np.testing.assert_allclose(trace[-1],a[[1,3,4]],atol=1e-6);assert a[4]<0 and a[6]==1;rows.append({'case':'PL_time_traces','trace_points':len(trace),'final_dbfs':trace[-1].tolist(),'summary_dbfs':a[[1,3,4]].tolist()})
(R/'NATIVE_NEW_PROGRAMS.json').write_text(json.dumps(rows,indent=2));print(rows)
