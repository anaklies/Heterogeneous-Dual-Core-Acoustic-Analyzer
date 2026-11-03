from pathlib import Path
import ctypes,json,subprocess
import numpy as np
from scipy import signal
P=Path(__file__).resolve().parents[1];H=P/'hls'
subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-shared',str(H/'analysis_math.cpp'),'-o',str(H/'analysis_math.dll')],check=True)
fn=ctypes.CDLL(str(H/'analysis_math.dll')).analysis_math
fn.argtypes=[ctypes.c_void_p]*3+[ctypes.c_uint]*3+[ctypes.c_float]*2+[ctypes.c_void_p]
rows=[]
def run(op,a,b=(),n=None,frames=0,df=1,parameter=0,size=262144,expected_status=0):
    a=np.array(a,np.float32).reshape(-1);b=np.array(b,np.float32).reshape(-1);out=np.zeros(size,np.float32);status=ctypes.c_uint(0)
    fn(a.ctypes.data,b.ctypes.data,out.ctypes.data,len(a) if n is None else n,frames,op,df,parameter,ctypes.byref(status))
    assert status.value==expected_status,(op,status.value,expected_status)
    return out
def check(name,out,expected,atol=1e-5,rtol=2e-4):
    out=np.array(out);expected=np.asarray(expected)
    assert np.allclose(out,expected,atol=atol,rtol=rtol),(name,np.max(abs(out-expected)))
    rows.append(dict(test=name,values=int(out.size),maximumAbsoluteError=float(np.max(abs(out-expected)))))
rng=np.random.default_rng(1331)
x=rng.normal(0,.02,(2048,6)).astype(np.float32)
r=run(1,x,n=len(x))[:48].reshape(6,8)
check('levels_rms',r[:,0],np.sqrt(np.mean(x.astype(float)**2,axis=0)))
check('levels_peak',r[:,1],abs(x).max(0));check('levels_p2p',r[:,2],np.ptp(x,axis=0))
check('levels_dbfs',r[:,4],20*np.log10(np.sqrt(np.mean(x.astype(float)**2,axis=0))))
w=signal.windows.hann(2048,sym=False);z=np.fft.rfft(x[:,0]*w);packed=np.column_stack([z.real,z.imag]).astype(np.float32)
r=run(2,packed,n=2048,df=48000/2048)[:3075].reshape(-1,3)
f,p=signal.periodogram(x[:,0],fs=48000,window=w,detrend=False,scaling='density')
check('PSD_vs_Scipy',r[:,1],p,atol=1e-10);check('binPower_PSD_df',r[:,2],p*(48000/2048),atol=1e-8)
p=rng.uniform(.01,2,257).astype(np.float32);r=run(3,p,df=93.75)
check('centroid',r[1],(p*np.arange(257)*93.75).sum()/p.sum(),atol=.003)
check('flatness',r[2],np.exp(np.log(p).mean())/p.mean())
r=run(4,p,parameter=5)[:len(p)];check('edgeNormalizedSmoothing',r,np.convolve(p,np.ones(5),'same')/np.convolve(np.ones_like(p),np.ones(5),'same'))
X=rng.normal(size=(20,33))+1j*rng.normal(size=(20,33));Y=X*np.exp(.6j)+.2*(rng.normal(size=X.shape)+1j*rng.normal(size=X.shape))
a=np.stack([X.real,X.imag],-1);b=np.stack([Y.real,Y.imag],-1)
r=run(5,a,b,n=33,frames=20,parameter=.001)[:231].reshape(33,7)
cs=np.mean(X.conj()*Y,axis=0);px=np.mean(abs(X)**2,axis=0);py=np.mean(abs(Y)**2,axis=0)
check('CSD_conjugate_real',r[:,0],cs.real*.001);check('CSD_conjugate_imag',r[:,1],cs.imag*.001)
check('coherence',r[:,4],abs(cs)**2/(px*py));check('relativePhase_j_minus_i',r[:,5],np.angle(cs))
p0=rng.uniform(size=65);p1=rng.uniform(size=65);r=run(6,p0,p1,n=65)
check('temporalEnergyChangeFlux',r[:3],[p1.sum(),p1.sum()-p0.sum(),np.linalg.norm(np.maximum(p1/p1.sum()-p0/p0.sum(),0))])
fp=rng.exponential(size=(20,33));r=run(7,fp,n=33,frames=20)[:66].reshape(33,2)
sk=21/19*(20*np.sum(fp*fp,axis=0)/np.sum(fp,axis=0)**2-1)-1
check('spectralKurtosisFiniteM',r[:,0],sk)
bands=np.array([[100,1000],[1000,5000]])
r=run(8,p,bands,n=257,frames=2,df=93.75)[:6].reshape(2,3)
check('bandIntegration',r[:,0],[p[(np.arange(257)*93.75>=lo)&(np.arange(257)*93.75<hi)].sum()*93.75 for lo,hi in bands],atol=.001)
sig=np.sin(np.arange(1024)*.2);r=run(9,sig,n=1024,frames=100)[:101]
g=signal.correlate(sig-sig.mean(),sig-sig.mean(),method='fft')[1023:1124];g/=g[0]
check('autocorrelation_vs_fft',r,g)
obs=rng.normal(size=(10,17,6))+1j*rng.normal(size=(10,17,6));steer=np.exp(1j*rng.uniform(-np.pi,np.pi,(17,6)))/6
r=run(10,np.stack([obs.real,obs.imag],-1),np.stack([steer.real,steer.imag],-1),n=17,frames=10,parameter=.001)[:17]
gold=np.mean(abs(np.sum(steer.conj()[None]*obs,axis=-1))**2,axis=0)*.001
check('DAS_knownWeights',r,gold,atol=1e-9)
r=run(11,p,p*2,n=257)[:514].reshape(-1,2);check('relative_reference_dB',r[:,0],np.full(257,10*np.log10(2)))
r=run(12,p,np.r_[p*.1,p*.2],n=257,frames=20)[:514].reshape(-1,2);check('slidingAverageUpdate',r[:,1],p*.9/20)
r=run(13,np.array([[3,4],[5,12]]),n=2)[:2];check('analyticMagnitude',r,[5,13])
run(1,np.full(6,np.nan),n=1,expected_status=15)
run(10,[],[],n=32768,frames=1024,expected_status=14)
run(255,[],n=1,expected_status=255)
(P/'tests/analysis_math_numeric.json').write_text(json.dumps(dict(tests=len(rows),valuesCompared=sum(r['values'] for r in rows),rows=rows,invalidInputTests=3,hardwareRTLValidated=False),indent=2))
print('ANALYSIS_MATH_C_PASS',len(rows),'tests',sum(r['values'] for r in rows),'values')
