"""Native production scalar engine vs independent float64 room-IR math."""
from pathlib import Path
import ctypes,json,subprocess,time,tempfile,os
import numpy as np
from room_services import room_ir,install_room

HERE=Path(__file__).resolve().parent
dll=Path(tempfile.gettempdir())/('sixmic_room_services_'+str(os.getpid())+'.dll')
subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-shared','-DSIXMIC_NATIVE',
                str(HERE.parent/'shared_backend/scalar_engine.cpp'),'-o',str(dll)],check=True)
fn=ctypes.CDLL(str(dll)).scalar_native
fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
rows=[]
def golden(x,fs):
    p=np.asarray(x,np.float64)**2; total=p.sum()
    if not total:return None
    db=10*np.log10(np.maximum(np.cumsum(p[::-1])[::-1]/total,1e-30))
    t=np.arange(len(x))/fs; fits=[]
    for hi,lo in [(0,-10),(-5,-25),(-5,-35)]:
        use=(db<=hi)&(db>=lo); ids=np.flatnonzero(use)
        if not np.any(db<=lo) or len(ids)<max(16,int(.001*fs)) or np.ptp(t[ids])<.005:
            fits.append(None);continue
        a,b=np.polyfit(t[use],db[use],1)
        r2=1-((db[use]-(a*t[use]+b))**2).sum()/((db[use]-db[use].mean())**2).sum()
        fits.append((-60/a,r2) if a<0 and r2>=.9 else None)
    early=[p[:int(c*fs)].sum() for c in [.05,.08]]
    clarity=[10*np.log10(e/(total-e)) if e>0 and total>e else None for e in early]
    return dict(db=db,fits=fits,energy=total,early=early,clarity=clarity,d50=100*early[0]/total)

def run(name,x,fs,expected_valid):
    mem=np.zeros(1200000,np.float32)
    spec=install_room(mem,room_ir(len(x),fs),ir=x)
    begin=time.perf_counter()
    for chunks in range(1,200000):
        status=ctypes.c_uint()
        fn(mem.ctypes.data,spec['descriptor'],len(mem),0,ctypes.byref(status))
        assert status.value&255==0,(name,hex(status.value))
        if status.value&0x80000000: break
    else:raise AssertionError('room program failed to terminate')
    a=mem[spec['output']:spec['output']+spec['output_words']]
    assert np.isfinite(a).all()
    g=golden(x,fs); errors={}
    if g:
        np.testing.assert_allclose(a[:4],[g['energy'],*g['early'],g['d50']],rtol=8e-5,atol=1e-6)
        errors['energy']=abs(float(a[0])-g['energy'])
        d=a[spec['metadata']['decay_offset']:spec['metadata']['decay_offset']+len(x)]
        np.testing.assert_allclose(d,g['db'],atol=8e-4,rtol=1e-5)
        errors['decay_db']=float(np.max(np.abs(d-g['db'])))
    for j,off in enumerate([10,16,22]):
        assert bool(a[off+2])==expected_valid[j],(name,j,a[:28])
        if expected_valid[j]:
            assert g['fits'][j] is not None
            np.testing.assert_allclose(a[off:off+2],g['fits'][j],rtol=3e-3,atol=3e-4)
    if g and expected_valid[0] and len(x)/fs>=.1:
        for j,off in enumerate([5,7]):
            assert a[off+1]==1
            np.testing.assert_allclose(a[off],g['clarity'][j],rtol=1e-3,atol=1e-3)
    rows.append(dict(case=name,samples=len(x),fs=fs,chunks=chunks,
        program_instructions=spec['bytecode_instructions'],seconds=time.perf_counter()-begin,
        fits_valid=[bool(a[o+2]) for o in [10,16,22]],max_errors=errors))

fs=48000;n=24000;t=np.arange(n)/fs
run('exponential_rt_0p25',np.exp(-np.log(1000)*t/.25).astype(np.float32),fs,[True]*3)
run('gain_scaled_decay',(.002*np.exp(-np.log(1000)*t/.35)).astype(np.float32),fs,[True]*3)
run('nondefault_rate',np.exp(-np.log(1000)*np.arange(12000)/24000/.3).astype(np.float32),24000,[True]*3)
run('silence',np.zeros(4800,np.float32),fs,[False]*3)
run('stationary_tail_insufficient_decay',np.ones(4800,np.float32)*.2,fs,[False]*3)
x=np.zeros(4800,np.float32);x[0]=1
run('impulse_near_step',x,fs,[False]*3)
for n,fs in [(0,48000),(60001,48000),(32,0),(32,float('nan'))]:
    try:room_ir(n,fs)
    except ValueError:pass
    else:raise AssertionError('invalid configuration accepted')
result=dict(status='NATIVE_PASS',cases=rows,
    implementation='Production scalar C; opcode24 decrement; <=64 instructions/command',
    scope='unfiltered onset-trimmed explicit IR; no automatic RIR acquisition or multiband room service',
    limitations=['stationary terminal tail rejected, no Lundeby/noise correction',
                 'no RTL/HLS throughput or board acceptance claimed','not certified room measurements'])
(HERE/'ROOM_RESULTS.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('ROOM_SERVICES_NATIVE_PASS cases=',len(rows))
