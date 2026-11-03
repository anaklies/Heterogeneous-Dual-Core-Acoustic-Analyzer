"""Exact sample-recursive FAST/SLOW on a captured contiguous mono PCM record.
This is a P2 recorded-data service, not sparse live-window time weighting.
"""
import math
from programs import Code
from p2_chains import install as _install

def recorded_time_response(samples,sample_rate=48009.775390625,contiguous=False):
 if not isinstance(samples,int)or not 1<=samples<=1000000 or not math.isfinite(sample_rate)or sample_rate<=0:raise ValueError('record/rate')
 c=Code();c.u(3,0);c.f(0,0)
 for i in range(9):c.store(0,3,i)
 if not contiguous:c.emit(0)
 else:
  c.u(0,0);c.u(1,32);c.f(1,0);c.f(2,0)
  a=math.exp(-1/(sample_rate*.125));b=math.exp(-1/sample_rate)
  for r,v in [(3,a),(4,1-a),(5,b),(6,1-b),(7,1/8388608),(8,1e-20),(9,10/math.log(10))]:c.f(r,v)
  loop=len(c.words);c.emit(20,2,1,target=2);c.emit(22,10,2);c.emit(6,10,10,7);c.emit(6,10,10,10);c.emit(4,2,2,10)
  c.emit(6,0,0,3);c.emit(6,11,10,4);c.emit(4,0,0,11);c.emit(6,1,1,5);c.emit(6,11,10,6);c.emit(4,1,1,11)
  c.addi(0,0,1);c.addi(1,1,1);c.loop(0,samples,loop)
  for field,reg in [(0,0),(2,1)]:
   c.store(reg,3,field);c.emit(12,12,reg,8);c.emit(9,12,12);c.emit(6,12,12,9);c.store(12,3,field+1)
  c.f(11,samples);c.emit(7,2,2,11);c.emit(12,2,2,8);c.emit(9,2,2);c.emit(6,2,2,9);c.store(2,3,4)
  c.u(0,samples);c.emit(21,0,3,imm=5,target=1);c.f(0,1);c.store(0,3,6)
  c.f(0,int(samples/sample_rate>=.625));c.store(0,3,7);c.f(0,int(samples/sample_rate>=5));c.store(0,3,8);c.emit(0)
 return c,dict(service='captured_exact_FAST_SLOW_LeqFS',output_count=9,workspace_words=32+samples,input_offset=32,
  input_format='mono sign-extended PCM24 LE32 copied from a trace with verified continuity',contiguous=bool(contiguous),sample_rate=sample_rate,samples=samples,
  fields=['FAST_power_FS2','FAST_dBFS','SLOW_power_FS2','SLOW_dBFS','LeqFS','samples_uint32','valid','FAST_settled','SLOW_settled'],
  scope='P2 captured-data exact recurrence; zero-start settling explicit, no live-continuity or IEC-certified claim')

def install(memory,specification,**kwargs):
 c,meta=specification;s=_install(memory,(c,meta),**kwargs);u=memory.view('uint32');n=max(16384,meta['workspace_words']);out=s['output']
 if out+n>len(memory):raise ValueError('record outside private arena')
 memory[out:out+n]=0
 for slot in range(4):u[s['descriptor']+16*slot+8]=n
 s['output_words']=n;return s
