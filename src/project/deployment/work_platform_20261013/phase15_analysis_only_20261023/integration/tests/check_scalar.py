from pathlib import Path
import ctypes,subprocess,json
import numpy as np
P=Path(__file__).resolve().parents[1]
subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-shared','-DSIXMIC_NATIVE',str(P/'shared_backend/scalar_engine.cpp'),'-o',str(P/'shared_backend/scalar.dll')],check=True)
fn=ctypes.CDLL(str(P/'shared_backend/scalar.dll')).scalar_native
fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
def bits(x):return np.array([x],np.float32).view(np.uint32)[0].item()
def ins(op,rd=0,ra=0,rb=0,imm=0,target=0):return [op|(rd<<8)|(ra<<13)|(rb<<18),imm,target,0]
B=524288
def setup(program,budget=17):
 m=np.zeros(B+16384,np.float32);u=m.view(np.uint32)
 u[B:B+16]=[0x414c5531,1,B+128,len(program),B+2048,B+4096,4096,B+8192,4096,budget,1,3,7,1,44,0]
 code=np.array(program,np.uint32).copy()
 code[np.isin(code[:,0]&255,[2,3,20,21])&(code[:,2]==0),1]+=B
 u[B+128:B+128+4*len(program)]=code.reshape(-1)
 return m
def run(m,expected=0,source_slot=0):
 s=ctypes.c_uint();fn(m.ctypes.data,B,len(m),source_slot,ctypes.byref(s));assert (s.value&255)==expected,(s.value,expected)
 return m.view(np.uint32)[B+2048:B+2128]
checks=[]
# Sum-of-squares uses a genuinely shared ALU, integer loop and cross-job context.
program=[ins(14,0,imm=0),ins(1,0,imm=bits(0)),ins(2,1,ra=0,imm=4096),ins(6,2,1,1),ins(4,0,0,2),ins(15,0,0,imm=1),ins(16,ra=0,imm=257,target=2),ins(3,0,ra=1,imm=8192),ins(0)]
m=setup(program);x=np.linspace(-.5,.5,257,dtype=np.float32);m[B+4096:B+4353]=x
chunks=0
while True:
 c=run(m);chunks+=1
 if c[12]:break
 m.view(np.uint32)[B+10]=0
 assert chunks<200
assert np.isclose(m[B+8192],np.dot(x.astype(float),x),rtol=2e-6)
checks.append(dict(name='sum_squares_preemption',chunks=chunks,value=float(m[B+8192])))
# Same-address LOAD after STORE must see the new value, not reader cache data.
p=[ins(1,0,imm=bits(3)),ins(3,0,imm=8192),ins(2,1,imm=8192),ins(6,2,1,1),ins(3,2,imm=8193),ins(0)]
m=setup(p);m.view(np.uint32)[B+5:B+7]=[B+8192,4096];run(m);assert m[B+8193]==9
checks.append(dict(name='read_after_write',value=float(m[B+8193])))
# Automatic restart/resume uses the same descriptor; no PS loop changes DSP data.
m=setup(program,budget=23);m[B+4096:B+4353]=x;m.view(np.uint32)[B+10]=2
for i in range(100):
 c=run(m)
 if c[12]:break
else:raise AssertionError('auto context did not finish')
assert np.isclose(m[B+8192],np.dot(x.astype(float),x),rtol=2e-6)
c=run(m);assert not c[12]
checks.append(dict(name='automatic_context_resume_restart',chunks=i+1))
# Integer load and signed conversion preserve sign-extended PCM bits.
m=setup([ins(20,2,imm=4096),ins(22,1,ra=2),ins(3,1,imm=8192),ins(0)])
m.view(np.uint32)[B+4096]=0xff800000;run(m);assert m[B+8192]==-8388608
checks.append(dict(name='integer_PCM_load',value=float(m[B+8192])))
for op,a,b,gold in [(4,.3,.7,1),(5,3,2,1),(6,3,2,6),(7,3,2,1.5),(8,9,0,3),(9,np.e,0,1),(10,1,0,np.e),(11,3,2,2),(12,3,2,3),(13,-3,0,3)]:
 m=setup([ins(1,0,imm=bits(a)),ins(1,1,imm=bits(b)),ins(op,2,0,1),ins(3,2,imm=8192),ins(0)],64)
 run(m);assert np.isclose(m[B+8192],gold,rtol=2e-6);checks.append(dict(name=f'op{op}',value=float(m[B+8192])))
# Division/domain/bounds/program/config changes must not masquerade as success.
m=setup([ins(1,0,imm=bits(1)),ins(7,2,0,1)]);run(m,6)
m=setup([ins(2,0,imm=16384)]);run(m,5)
m=setup([ins(17,imm=100)]);run(m,4)
m=setup(program,budget=2);run(m);m.view(np.uint32)[B+10]=0;m.view(np.uint32)[B+12]=8;run(m,3)
m=setup(program);m.view(np.uint32)[B+7]=128;run(m,2)
m=setup(program,budget=2);run(m);m.view(np.uint32)[B+10]=0;m.view(np.uint32)[B+14]=45;run(m,3)
m=setup([ins(2,1,imm=0,target=1),ins(3,1,imm=8192),ins(0)])
m.view(np.uint32)[B+5:B+7]=[262144,49152];m[262144]=.375;run(m);assert m[B+8192]==.375
checks.append(dict(name='relative_live_FFT_read',value=float(m[B+8192])))
m=setup(program);m.view(np.uint32)[B+5:B+7]=[262144,49152];run(m,2,source_slot=1)
report=dict(checks=checks,invalidCases=7,HLSRTLValidated=False)
(P/'results/scalar_math.json').write_text(json.dumps(report,indent=2))
print('SCALAR_C_PASS',len(checks),'math/control cases; 7 invalid cases; chunks',chunks)
