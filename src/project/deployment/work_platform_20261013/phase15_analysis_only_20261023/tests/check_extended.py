"""Only new shared stages. Historical 13 operations are not replayed."""
from pathlib import Path
import ctypes, json, subprocess
import numpy as np
from scipy import signal
P=Path(__file__).resolve().parents[1]
subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-shared','-DSIXMIC_NATIVE',str(P/'analysis/analysis_dma.cpp'),'-o',str(P/'analysis/analysis.dll')],check=True)
fn=ctypes.CDLL(str(P/'analysis/analysis.dll')).analysis_dma
fn.argtypes=[ctypes.c_void_p]*3+[ctypes.c_uint]*3+[ctypes.c_float]*2+[ctypes.c_void_p]
rows=[]
def run(op,a,b=(),frames=0,df=1,parameter=0,status=0):
    a=np.array(a,np.float32).reshape(-1);b=np.array(b,np.float32).reshape(-1)
    out=np.full(262144,-123.,np.float32);code=ctypes.c_uint()
    fn(a.ctypes.data,b.ctypes.data,out.ctypes.data,len(a),frames,op,df,parameter,ctypes.byref(code))
    assert code.value==status,(op,code.value,status)
    return out
def check(name,actual,expected,atol=1e-5,rtol=2e-4):
    actual=np.asarray(actual);expected=np.asarray(expected)
    assert np.allclose(actual,expected,atol=atol,rtol=rtol),(name,actual,expected)
    rows.append(dict(test=name,values=actual.size,maximumAbsoluteError=float(np.max(abs(actual-expected)))))
rng=np.random.default_rng(231025)
a=rng.random(257);b=rng.random(257)
check('peak_hold',run(14,a,b)[:257],np.maximum(a,b))
times=[0,.1,.3,.7];freq=[100,101,105,103]
r=run(15,freq,times)[:8].reshape(4,2)
check('frequency_drift',r[:,0],[0,10,20,-5]);check('first_drift_invalid',r[:,1],[0,1,1,1])
p=np.zeros(1025);p[100]=2;p[200]=.08;p[300]=.02
r=run(16,p,[1000,2000,3000],frames=3,df=10,parameter=15)
check('harmonic_band_energy',r[:9].reshape(3,3)[:,1],[20,.8,.2]);check('finite_THD',r[9],np.sqrt(.05));assert r[10]==1
fs=48000;n=12000;ir=np.exp(-np.arange(n)/1200)
r=run(17,ir,df=fs);gold=np.cumsum(ir[::-1]**2)[::-1]
check('Schroeder_energy',r[:2*n:2],gold,atol=.002)
check('Schroeder_usable_decay',r[:2*n:2][1:1000],gold[1:1000],atol=.002)
ir=np.zeros(6000);ir[0]=1;ir[1000]=.5;ir[3000]=.25;ir[5000]=.125
r=run(18,ir,df=fs)
check('clarity_C50_C80_D50',r[:3],[10*np.log10(1.25/.078125),10*np.log10(1.3125/.015625),1.25/1.328125])
quiet=np.zeros(6000);quiet[0]=1;quiet[5000]=1e-4
r=run(18,quiet,df=fs)
check('clarity_preserves_80dB_late_tail',r[:2],[80,80],atol=.0001);assert r[3]==r[4]==1
curve=-60*np.arange(6000)/fs/.12
r=run(19,curve,[-5,-25],df=fs,parameter=.90)
check('T20_fit_RT60',r[0],.12,atol=1e-5);assert r[4]==1
r=run(19,np.linspace(0,-10,1000),[-5,-25],df=fs,parameter=.9);assert r[4]==0
t=np.arange(4096)/fs;x=np.sin(2*np.pi*200*t)
ac=signal.correlate(x-x.mean(),x-x.mean(),method='fft')[4095:]
ac/=ac[0]
r=run(20,ac[:700],[80,2000,.7],df=fs)
check('F0_from_correlation',r[0],200,atol=.3);assert r[3]==1
run(20,ac[:700],[1e-38,2000,.7],df=fs,status=20)
run(15,[1,2,3],[0,.1,.1],status=15)
run(16,[-1,2],[1],frames=1,parameter=1,status=16)
run(17,np.zeros(32),df=fs,status=17)
run(18,np.ones(20),df=fs,status=18)
run(14,[np.nan],[1],status=15)
# The public native API must reject alias before writing any sample.
alias=np.arange(128,dtype=np.float32);before=alias.copy();other=np.ones(128,np.float32);code=ctypes.c_uint()
fn(alias.ctypes.data,other.ctypes.data,alias[1:].ctypes.data,17,0,14,1,0,ctypes.byref(code))
assert code.value==14 and np.array_equal(alias,before)
# Verify inherited formula body unchanged except the new dispatch at its entry.
old=(P.parent/'phase14_room_and_pl_20261021/pl_system/analysis_dma/analysis_dma.cpp').read_text()
new=(P/'analysis/analysis_dma.cpp').read_text()
dispatch='    if(operation>=14){extended_compute(a,b,out,n,frames,operation,df,parameter,status);return;}\n'
assert new[new.index('static float phase_angle'):new.index('\n#ifdef SIXMIC_NATIVE')].replace(dispatch,'',1)==old[old.index('static float phase_angle'):old.index('\n#ifdef SIXMIC_NATIVE')]
report=dict(tests=len(rows),valuesCompared=sum(x['values'] for x in rows),invalidCases=7,invalidFitCases=1,
            original13FormulaBodyUnchanged=True,rows=rows,RTLValidated=False)
(P/'results/extended_math.json').write_text(json.dumps(report,indent=2))
print('EXTENDED_MATH_PASS',len(rows),'comparisons; original 13 unchanged')
