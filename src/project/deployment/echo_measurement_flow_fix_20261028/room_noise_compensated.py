"""PL microcode for an explicitly supplied, onset-trimmed mono room IR.

No onset/RIR extraction, octave filtering, stationary-tail subtraction or certified
RT measurement is implied. A stationary terminal energy floor rejects the fits
and clarity (conservative substitute for the reference's tail-noise correction).
PS installs instructions/metadata; all signal arithmetic executes in scalar PL.
"""
import math
import numpy as np
from programs import Code, PRIVATE


def room_ir(samples, sample_rate=48000):
    if not isinstance(samples, int) or not 32 <= samples <= 60000:
        raise ValueError('IR length must be 32..60000')
    if not math.isfinite(sample_rate) or not 8000 <= sample_rate <= 192000:
        raise ValueError('invalid sample rate')
    n=samples; ir=32; decay=ir+n
    c=Code(); c.u(3,0); c.u(2,1)
    # Summaries cleared atomically only at program END publication by caller.
    c.f(0,0)
    for i in range(32): c.store(0,3,i)
    c.f(1,1); c.f(2,1e-30); c.f(3,10/math.log(10)); c.f(4,1/sample_rate)
    # Tail stationarity: four disjoint blocks from final20%, each mean power.
    tail=max(8,n//5); bounds=np.linspace(n-tail,n,5,dtype=int)
    c.f(18,1e30); c.f(19,0); c.f(30,0); c.f(31,0)
    for lo,hi in zip(bounds[:-1],bounds[1:]):
        c.u(0,int(lo)); c.f(5,0); start=len(c.words)
        c.history(6,0,ir); c.emit(6,6,6,6); c.emit(4,5,5,6)
        c.addi(0,0,1); c.loop(0,int(hi),start)
        c.f(6,int(hi-lo)); c.emit(7,5,5,6)
        c.emit(11,18,18,5); c.emit(12,19,19,5); c.emit(4,31,31,5)
    c.f(6,3); c.emit(6,18,18,6); c.f(20,1)
    # Reject a nonzero approximately stationary terminal tail.
    jzero=c.emit(19,a=19,b=2,target=0)
    jstationary=c.emit(19,a=19,b=18,target=0)
    skip=c.emit(17,imm=0)
    c.words[jstationary][2]=len(c.words); c.f(6,.25); c.emit(6,30,31,6)
    c.words[jzero][2]=len(c.words); c.words[skip][1]=len(c.words)
    c.f(6,.25); c.emit(6,19,31,6)
    c.store(20,3,4); c.store(30,3,9)
    # Exact reverse integration (uint decrement opcode24); raw cumulative energy.
    c.u(0,n-1); c.f(5,0); start=len(c.words)
    c.history(6,0,ir); c.emit(6,6,6,6); c.emit(4,5,5,6)
    c.emit(18,6,0); c.f(7,n); c.emit(5,6,7,6); c.emit(6,6,6,30)
    c.emit(5,6,5,6); c.emit(12,6,6,2); c.store(6,0,decay)
    exit_reverse=c.emit(16,a=0,imm=1,target=0)
    c.emit(24,0,0,2); c.emit(17,imm=start)
    c.words[exit_reverse][2]=len(c.words)
    c.u(0,0); c.history(5,0,decay); c.store(5,3,0)
    # Silence leaves all result valid bits zero.
    silent=c.emit(19,a=5,b=2,target=0)
    # Conservative integrated-noise uncertainty limit: five sigma, Gaussian-tail
    # approximation. Fits must reach their full lower threshold above this limit.
    c.f(6,5*math.sqrt(2*n)); c.emit(6,6,6,30); c.emit(7,6,6,5)
    c.emit(12,6,6,2); c.emit(9,31,6); c.emit(6,31,31,3); c.store(31,3,28)
    # Energy decay in dB, with floor solely preventing LOG(0).
    c.u(0,0); start=len(c.words); c.history(6,0,decay)
    c.emit(7,6,6,5); c.emit(12,6,6,2); c.emit(9,6,6); c.emit(6,6,6,3)
    c.store(6,0,decay); c.addi(0,0,1); c.loop(0,n,start)
    # Relative clarity: actual early/late energy, not dB SPL or separated sources.
    c.f(21,0); c.f(22,0); c.u(0,0); start=len(c.words)
    c.history(6,0,ir); c.emit(6,6,6,6)
    to50=c.emit(16,a=0,imm=min(n,int(.05*sample_rate)),target=0)
    skip50=c.emit(17,imm=0); c.words[to50][2]=len(c.words); c.emit(4,21,21,6)
    c.words[skip50][1]=len(c.words)
    to80=c.emit(16,a=0,imm=min(n,int(.08*sample_rate)),target=0)
    skip80=c.emit(17,imm=0); c.words[to80][2]=len(c.words); c.emit(4,22,22,6)
    c.words[skip80][1]=len(c.words)
    c.addi(0,0,1); c.loop(0,n,start)
    c.f(6,min(n,int(.05*sample_rate))); c.emit(6,6,6,30); c.emit(5,21,21,6); c.emit(12,21,21,2)
    c.f(6,min(n,int(.08*sample_rate))); c.emit(6,6,6,30); c.emit(5,22,22,6); c.emit(12,22,22,2)
    c.f(6,min(n,int(.05*sample_rate)));c.emit(7,6,21,6);c.f(7,4);c.emit(6,7,19,7)
    quiet=c.emit(19,a=6,b=7,target=0);good=c.emit(17,imm=0);c.words[quiet][2]=len(c.words);c.f(20,0);c.words[good][1]=len(c.words);c.store(20,3,4)
    c.store(21,3,1); c.store(22,3,2)
    c.emit(7,6,21,5); c.f(7,100); c.emit(6,6,6,7); c.store(6,3,3)
    if n/sample_rate >= .1:
        for early,off in [(21,5),(22,7)]:
            c.emit(5,7,5,early)
            bad1=c.emit(19,a=early,b=2,target=0); bad2=c.emit(19,a=7,b=2,target=0)
            c.emit(7,6,early,7); c.emit(9,6,6); c.emit(6,6,6,3)
            c.store(6,3,off); c.store(20,3,off+1)
            c.words[bad1][2]=len(c.words); c.words[bad2][2]=len(c.words)
    # Regression: sums count,t,y,t²,ty,y² and first/last selected times.
    for upper,lower,offset in [(0,-10,10),(-5,-25,16),(-5,-35,22)]:
        for r in range(7,15): c.f(r,0)
        c.f(15,upper); c.f(16,lower); c.f(29,upper); c.f(28,lower); c.u(0,0)
        start=len(c.words); c.history(6,0,decay)
        high=c.emit(19,a=15,b=6,target=0); low=c.emit(19,a=6,b=16,target=0)
        c.emit(18,17,0); c.emit(6,17,17,4)
        first=c.emit(19,a=7,b=1,target=0); skipfirst=c.emit(17,imm=0)
        c.words[first][2]=len(c.words); c.emit(4,13,17,0)
        c.words[skipfirst][1]=len(c.words); c.emit(4,14,17,0)
        c.emit(11,29,29,6);c.emit(12,28,28,6)
        c.emit(4,7,7,1); c.emit(4,8,8,17); c.emit(4,9,9,6)
        c.emit(6,23,17,17); c.emit(4,10,10,23)
        c.emit(6,23,17,6); c.emit(4,11,11,23)
        c.emit(6,23,6,6); c.emit(4,12,12,23)
        c.words[high][2]=len(c.words); c.words[low][2]=len(c.words)
        c.addi(0,0,1); c.loop(0,n,start)
        exits=[]
        def reject(a,b): exits.append(c.emit(19,a=a,b=b,target=0))
        c.f(23,lower+.5);reject(23,29);c.f(23,upper-.5);reject(28,23)
        c.f(23,lower); reject(23,31)
        c.f(23,max(16,int(.001*sample_rate))); reject(7,23)
        c.emit(5,24,14,13); c.f(23,.005); reject(24,23)
        # Last decay must reach lower fit threshold (not only selected points).
        c.u(0,n-1); c.history(6,0,decay); reject(16,6)
        c.emit(6,24,7,10); c.emit(6,25,8,8); c.emit(5,24,24,25); reject(24,2)
        c.emit(6,25,7,11); c.emit(6,26,8,9); c.emit(5,25,25,26)
        c.f(26,-1e-30); exits.append(c.emit(19,a=26,b=25,target=0))
        c.emit(6,26,7,12); c.emit(6,27,9,9); c.emit(5,26,26,27); reject(26,2)
        c.emit(6,27,25,25); c.emit(6,28,24,26); c.emit(7,27,27,28)
        c.emit(11,27,27,1); c.f(28,.9); reject(27,28)
        c.emit(7,28,25,24); c.f(29,-60); c.emit(7,29,29,28)
        c.store(29,3,offset); c.store(27,3,offset+1); c.store(20,3,offset+2)
        c.store(7,3,offset+3); c.store(13,3,offset+4); c.store(14,3,offset+5)
        for j in exits: c.words[j][2]=len(c.words)
    c.words[silent][2]=len(c.words); c.emit(0)
    assert len(c.words)<=1024
    return c,decay+n,dict(service='room_ir_unfiltered',ir_offset=ir,decay_offset=decay,
        samples=n,sample_rate=sample_rate,summary_words=32,
        validity='explicit impulse; early energy exceeds tail; stationary noise compensation; full fit dB interval covered above noise uncertainty',
        fields={'energy':0,'early50':1,'early80':2,'D50_percent':3,'tail_valid':4,'noise_power_FS2':9,'noise_limit_db':28,
                'C50_db':5,'C50_valid':6,'C80_db':7,'C80_valid':8,
                'EDT':[10,11,12,13,14,15],'T20':[16,17,18,19,20,21],
                'T30':[22,23,24,25,26,27]},certified=False,
        exclusions=['onset/RIR extraction','multiband filtering','certified RT/STIPA/isolation'])


def install_room(memory, specification, base=1000000, ir=None):
    c,n,meta=specification
    output=base+8192; size=max(16384,n)
    if base<PRIVATE or base+8192+size>len(memory) or memory.dtype!=np.float32:
        raise ValueError('private room allocation outside arena')
    u=memory.view(np.uint32); code=base+128; ctx=base+4352
    u[code:code+4*len(c.words)]=np.asarray(c.words,np.uint32).ravel()
    memory[ctx:ctx+320]=0; memory[output:output+size]=0
    if ir is not None:
        x=np.asarray(ir,np.float32)
        if x.shape!=(meta['samples'],) or not np.isfinite(x).all(): raise ValueError('invalid IR')
        memory[output+32:output+32+len(x)]=x
    for slot in range(4):
        u[base+16*slot:base+16*(slot+1)]=[0x414c5531,1,code,len(c.words),ctx+slot*80,
            262144+slot*65536,49152,output,size,64,2,1,1,1,1,0]
    return dict(descriptor=base,output=output,output_words=size,metadata=meta,
                bytecode_instructions=len(c.words))
