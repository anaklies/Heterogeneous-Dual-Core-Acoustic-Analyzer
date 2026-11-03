"""Offline captured-data STIPA frontend recipes for shared PL scalar ISA.
Configuration only runs on host: filter coefficients and exact finite-record
regression weights. Host MUST NOT filter audio or evaluate signal statistics.
This is a research reference-ratio estimator, not certified IEC STIPA.
"""
import math
import numpy as np
from scipy import signal
from programs import Code

FS=48000
CENTERS=[125,250,500,1000,2000,4000,8000]
PAIRS=[(1.6,8),(1,5),(.63,3.15),(2,10),(1.25,6.25),(.8,4),(2.5,12.5)]

def layout(n):
    if not isinstance(n,int) or n<1 or 524288+8192+4*n+256>4194304:
        raise ValueError('bounded captured record required; about19seconds maximum')
    return dict(n=n,reference=0,observation=n,intensity=2*n,weight=3*n,result=4*n,words=4*n+256)

def filter_program(n,band,trace):
    """Exact frozen Butterworth topology; float32 DF2T (quantized coefficients).
    The shared intensity trace is overwritten only after its six fit passes.
    Output result+32+2*band+trace is frozen central band power.
    """
    q=layout(n)
    if band not in range(7) or trace not in (0,1):raise ValueError('band/trace')
    sos=signal.butter(9,[CENTERS[band]/math.sqrt(2),CENTERS[band]*math.sqrt(2)],fs=FS,btype='bandpass',output='sos')
    lp=signal.butter(4,40,fs=FS,output='sos'); sections=np.vstack((sos,lp))
    c=Code();c.u(0,trace*n);c.u(1,2*n);c.u(2,0);c.u(3,0)
    for r in range(2,24):c.f(r,0)
    c.f(30,0);c.f(31,0)
    start=len(c.words);c.history(0,0)
    for s,row in enumerate(sections):
        if s==9:
            c.emit(6,0,0,0)
            # Only central samples contribute to band power, same .3s trim.
            lo=c.emit(16,a=2,imm=14400,target=0)
            hi=c.emit(16,a=2,imm=max(14400,n-14400),target=0)
            skip=c.emit(17,imm=0);c.words[hi][2]=len(c.words)
            c.emit(4,30,30,0);c.words[lo][2]=len(c.words);c.words[skip][1]=len(c.words)
        b0,b1,b2,a0,a1,a2=row
        for reg,value in zip(range(24,29),[b0,b1,b2,a1,a2]):c.f(reg,value)
        z1,z2=2+2*s,3+2*s
        c.emit(6,1,0,24);c.emit(4,1,1,z1)
        c.emit(6,z1,0,25);c.emit(6,29,1,27);c.emit(5,z1,z1,29);c.emit(4,z1,z1,z2)
        c.emit(6,z2,0,26);c.emit(6,29,1,28);c.emit(5,z2,z2,29)
        c.emit(4,0,1,31)
    c.store(0,1);c.addi(0,0,1);c.addi(1,1,1);c.addi(2,2,1);c.loop(2,n,start)
    c.f(1,max(1,n-28800));c.emit(7,30,30,1);c.store(30,3,q['result']+32+2*band+trace);c.emit(0)
    return c,q,sections

def regression_weights(n,band,coefficient):
    """Configuration-only transpose of frozen resample_poly + joint LS.
    Finite record times start AFTER envelope[60:-60], exactly frozen behavior.
    No signal input is accepted by this function.
    """
    layout(n)
    m=(n+239)//240
    if m-120<20:raise ValueError('record too short for frozen envelope fit')
    t=np.arange(m-120)/200
    X=np.column_stack([np.ones(len(t)),t-t.mean(),*[v for f in PAIRS[band] for v in (np.sin(2*np.pi*f*t),np.cos(2*np.pi*f*t))]])
    if np.linalg.matrix_rank(X)!=6:raise ValueError('rank deficient configuration')
    p=np.linalg.pinv(X)[coefficient]
    # scipy resample_poly down240 has half_len2400, prepad240,
    # n_pre_remove11. This is its exact adjoint with zero extension.
    h=signal.firwin(4801,1/240,window=('kaiser',5.0))
    w=np.zeros(n)
    for j,v in enumerate(p):
        center=(j+60)*240
        lo=max(0,center-2400);hi=min(n,center+2401)
        w[lo:hi]+=v*h[2400+center-np.arange(lo,hi)]
    return w.astype(np.float32)

def fit_program(n,band,trace,coefficient):
    q=layout(n); c=Code();c.u(0,2*n);c.u(1,3*n);c.u(2,0);c.u(3,0);c.f(0,0);c.f(3,0);c.f(31,0)
    start=len(c.words);c.history(1,0);c.history(2,1);c.emit(6,1,1,2);c.emit(5,1,1,3);c.emit(4,4,0,1);c.emit(5,3,4,0);c.emit(5,3,3,1);c.emit(4,0,4,31)
    c.addi(0,0,1);c.addi(1,1,1);c.addi(2,2,1);c.loop(2,n,start)
    c.store(0,3,q['result']+48+trace*42+band*6+coefficient);c.emit(0)
    return c,q

def mtf_program(n,confirmed=False):
    """PL validation and depth ratios. Valid0 for short/unconfirmed records.
    Output result[0]=valid;[1]=reason(1configuration,2modulation);
    [2:16]=14 measured ratios. Caller may use existing PL MTF combiner.
    """
    q=layout(n); c=Code();c.u(3,0);c.f(0,0);c.f(1,1);c.store(0,3,q['result']);c.store(1,3,q['result']+1)
    if not confirmed or not 15*FS<=n<=60*FS:c.emit(0);return c,q
    exits=[];c.history(6,3,q['result']+31);ok=c.emit(19,a=0,b=6,target=0);exits.append(c.emit(17,imm=0));c.words[ok][2]=len(c.words);c.f(2,1e-18);c.f(3,.15);c.f(4,1.3);c.f(5,2)
    c.store(5,3,q['result']+1)
    for b in range(7):
        for tr in (0,1):
            c.history(6,3,q['result']+32+2*b+tr)
            ok=c.emit(19,a=2,b=6,target=0);exits.append(c.emit(17,imm=0));c.words[ok][2]=len(c.words)
            c.history(6,3,q['result']+48+tr*42+b*6)
            ok=c.emit(19,a=0,b=6,target=0);exits.append(c.emit(17,imm=0));c.words[ok][2]=len(c.words)
            for j in range(2):
                c.history(7,3,q['result']+48+tr*42+b*6+2+2*j);c.history(8,3,q['result']+48+tr*42+b*6+3+2*j)
                c.emit(6,7,7,7);c.emit(6,8,8,8);c.emit(4,7,7,8);c.emit(8,7,7);c.emit(7,7,7,6)
                c.store(7,3,q['result']+136+tr*14+2*b+j)
        for j in range(2):
            c.history(7,3,q['result']+136+2*b+j);c.history(8,3,q['result']+150+2*b+j)
            bad=c.emit(19,a=7,b=3,target=0);exits.append(bad)
            c.emit(7,8,8,7);bad=c.emit(19,a=4,b=8,target=0);exits.append(bad)
            c.store(8,3,q['result']+2+2*b+j)
    c.store(1,3,q['result']);c.store(0,3,q['result']+1)
    end=len(c.words);c.emit(0)
    for k in exits:
        if c.words[k][0]&255==17:c.words[k][1]=end
        else:c.words[k][2]=end
    assert len(c.words)<1024
    return c,q

def install_stage(memory,c,q,base=524288,generation=1):
    out=base+8192
    if out+q['words']>len(memory) or len(c.words)>1024:raise ValueError('arena/program bounds')
    u=memory.view(np.uint32);code=base+128;ctx=base+4352
    u[code:code+4*len(c.words)]=np.asarray(c.words,np.uint32).ravel();memory[ctx:ctx+80]=0
    u[base:base+16]=[0x414c5531,1,code,len(c.words),ctx,out,q['words'],out,q['words'],64,2,1,1,1,generation,0]
    return dict(descriptor=base,output=out,context=ctx)


def validation_program(n,confirmed=False):
    """PL scans both captures; finite-load fault never publishes valid.
    Run before any frontend stage. No valid publication without confirmation,
    duration bounds, no digital clipping, and complete traversal.
    """
    q=layout(n);c=Code();c.u(0,0);c.u(3,0);c.f(0,0);c.f(2,1)
    c.store(0,3,q['result']+31)
    if not confirmed or not 15*FS<=n<=60*FS:c.emit(0);return c,q
    start=len(c.words);c.history(1,0);c.emit(13,1,1)
    ok=c.emit(19,a=1,b=2,target=0);endjump=c.emit(17,imm=0);c.words[ok][2]=len(c.words)
    c.addi(0,0,1);c.loop(0,2*n,start);c.store(2,3,q['result']+31)
    c.words[endjump][1]=len(c.words);c.emit(0);return c,q
