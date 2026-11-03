from pathlib import Path
import ctypes,sys,json,time
import numpy as np
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'))
from deployment_profiles import build_profile,P1_TABLE,P2_TABLE
fn=ctypes.CDLL(str(p/'shared_backend/scalar.dll')).scalar_native_meta;fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*8+[ctypes.c_void_p]
raw=np.array([int(x,16)for x in(p/'tests/pcm_window.hex').read_text().split()],np.uint32)
g=np.loadtxt(p/'tests/stream_golden.txt').astype(np.float32).reshape(6,7179)
rows=[]
def populate(m):
 for slot in range(4):
  m.view(np.uint32)[slot*16384:slot*16384+12288]=raw
  for ch in range(6):m[262144+slot*65536+ch*8192:262144+slot*65536+ch*8192+7179]=g[ch]
def run(m,descriptor,spec,name,slot=0,frame=321):
 started=time.perf_counter();requests=[]
 for k in range(60000):
  s=ctypes.c_uint();fn(m.ctypes.data,descriptor+16*slot,len(m),slot,3,7,frame,frame*2048,0,ctypes.byref(s));v=s.value
  assert not v&255,(name,hex(v),k)
  if v&0x40000000:
   mode=(v>>28)&3;out=((v>>18)&1023)<<12;z=m[out+4096:out+8192:2].astype(float)+1j*m[out+4097:out+8192:2]
   assert mode in (1,2),(name,mode)
   z=np.fft.fft(z) if mode==1 else np.fft.ifft(z);m[out+8192:out+12288:2]=z.real;m[out+8193:out+12288:2]=z.imag;requests.append(mode)
  if v>>31:break
 else:raise AssertionError((name,'bounded invocation timeout'))
 out=spec['output'];h=m.view(np.uint32)[out-16:out]
 assert h[0]==0x52534c54 and h[2]==3 and h[3]==7 and h[6]==frame and h[9]==slot and h[11]==descriptor+16*slot and h[14]==1,(name,h)
 rows.append(dict(service=name,chunks=k+1,publicationHeaderVerified=True,FFTsyscallsReferenceOnly=requests,nativeSeconds=time.perf_counter()-started))
m,info=build_profile(session=3,config=7);populate(m)
for idx,(name,spec)in enumerate(info['p1_services'].items()):run(m,P1_TABLE+64*idx,spec,name)
for name,args in [('cepstrum',{}),('autocorrelation',{}),('cross_correlation',{}),('gcc_phat',{}),('fundamental',{}),('envelope',{}),('envelope_spectrum',{}),('manual_das',{'count':8}),('das_map',{'points':[(0,0),(90,0),(0,90)],'count':4}),('harmonics',{'f0':500,'orders':4}),('sidebands',{'carrier':2000,'spacing':300,'half_width':30}),('spectral_kurtosis',{'count':16}),('weighting',{}),('level_statistics',{}),('relative_insulation',{}),('noise_curve',{}),('FAST',{}),('SLOW',{}),('AB_limit',{'count':16}),('room_decay',{'samples':2048}),('room_band_decay',{'samples':2048})]:
 m,info=build_profile(name,args,session=3,config=7);populate(m);run(m,P2_TABLE,info['p2'],name)
result=dict(status='PASS',verification='canonical descriptor installation and Native production VM invocation; FFT syscalls served by numerical reference, not full-system RTL',cases=rows,totalInvocations=len(rows),scope='normal P1/P2 dispatch, safe invalid/initial states are valid outcomes; old mathematical tests inherited',notCovered=['physical board','live continuous FAST/SLOW cadence','full captured-data Zoom and full 101-stage STIPA walltime'])
(p/'results/final_invocation_native.json').write_text(json.dumps(result,indent=2));print('CANONICAL_INVOCATION_PASS',len(rows),'services, source/session/frame/publication verified',flush=True)
