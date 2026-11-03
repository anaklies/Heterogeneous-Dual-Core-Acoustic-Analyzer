"""Selected-pair Welch-like cross spectra executed entirely by shared PL VM.

One invocation consumes ONE pinned FFT snapshot. Caller must submit distinct
frame IDs, preferably non-overlapping windows, and reset history on pair/config
changes. This program cannot establish temporal independence from FFT values.
No claim of calibrated SPL, all-pair parallelism, or measured PL throughput.
"""
import math
import numpy as np
from programs import Code, PRIVATE


def cross_spectra(channel_i=0, channel_j=1, first=0, count=1025,
                  sample_rate=48000., window_energy=768., floor=1e-30):
    if not (0 <= channel_i < 6 and 0 <= channel_j < 6 and channel_i != channel_j):
        raise ValueError('two distinct channels required')
    if first < 0 or count < 1 or first+count > 1025:
        raise ValueError('invalid single-sided bin range')
    if not all(math.isfinite(x) and x>0 for x in (sample_rate,window_energy,floor)):
        raise ValueError('invalid density scale or floor')
    c=Code(); c.u(3,0); c.f(27,0); c.f(28,1); c.f(26,floor)
    c.history(31,3,0); c.emit(4,31,31,28); c.store(31,3,0)
    c.emit(7,30,28,31)
    c.u(0,0); c.u(1,channel_i*8192+first*2); c.u(2,channel_j*8192+first*2)
    c.u(4,1); c.u(5,first)
    loop=len(c.words)
    c.load(0,1); c.load(1,1,1); c.load(2,2); c.load(3,2,1)
    # conj(X_i)*X_j; Sxx, Syy, cross-real, cross-imag.
    for dst,a,b,d,e,subtract in ((4,0,0,1,1,False),(5,2,2,3,3,False),
                                 (6,0,2,1,3,False),(7,0,3,1,2,True)):
        c.emit(6,8,a,b); c.emit(6,9,d,e); c.emit(5 if subtract else 4,dst,8,9)
    for k in range(4):
        c.history(8,4,k); c.emit(4,4+k,4+k,8); c.store(4+k,4,k)
    # Single-sided PSD/CSD normalization; DC/Nyquist are NOT doubled.
    c.f(20,2/(sample_rate*window_energy))
    # u5<1 => DC, 1023<u5 => Nyquist (branch via float comparison).
    c.emit(18,21,5); c.f(22,0.5)
    dc=c.emit(19,a=21,b=22,target=0)
    c.f(22,1023.5); ny=c.emit(19,a=22,b=21,target=0)
    skip=c.emit(17,imm=0)
    c.words[dc][2]=c.words[ny][2]=len(c.words); c.f(20,1/(sample_rate*window_energy))
    c.words[skip][1]=len(c.words)
    c.emit(6,20,20,30)
    for k in range(4):
        c.emit(6,8,4+k,20); c.store(8,4,4+k)
    # Coherence is only valid after >=2 distinct input windows with nonzero powers.
    c.f(23,0); c.f(24,0); c.f(22,1.5)
    early=[c.emit(19,a=31,b=22,target=0), c.emit(19,a=4,b=26,target=0),
           c.emit(19,a=5,b=26,target=0)]
    # Normalize BEFORE squaring: power products can underflow for weak bins.
    c.emit(8,8,4); c.emit(8,9,5); c.emit(6,9,8,9)
    c.emit(7,8,6,9); c.emit(7,9,7,9)
    c.emit(6,8,8,8); c.emit(6,9,9,9); c.emit(4,23,8,9)
    c.emit(11,23,23,28); c.emit(12,23,23,27); c.f(24,1)
    for p in early:c.words[p][2]=len(c.words)
    c.store(23,4,8); c.store(24,4,10)
    # Existing project atan2 approximation, with explicit zero and quadrant paths.
    c.f(14,0); c.emit(13,10,6); c.emit(13,11,7)
    c.emit(12,15,10,11)
    phasezero=c.emit(19,a=15,b=26,target=0)
    c.emit(11,12,10,11); c.emit(7,12,12,15); c.emit(6,13,12,12)
    c.f(14,-.01172120)
    for coeff in (.05265332,-.11643287,.19354346,-.33262347,.99997726):
        c.emit(6,14,14,13); c.f(16,coeff); c.emit(4,14,14,16)
    c.emit(6,14,14,12)
    p=c.emit(19,a=10,b=11,target=0); q=c.emit(17,imm=0)
    c.words[p][2]=len(c.words); c.f(16,math.pi/2); c.emit(5,14,16,14)
    c.words[q][1]=len(c.words)
    p=c.emit(19,a=6,b=27,target=0); q=c.emit(17,imm=0)
    c.words[p][2]=len(c.words); c.f(16,math.pi); c.emit(5,14,16,14)
    c.words[q][1]=len(c.words)
    p=c.emit(19,a=7,b=27,target=0); q=c.emit(17,imm=0)
    c.words[p][2]=len(c.words); c.emit(5,14,27,14)
    c.words[q][1]=len(c.words)
    c.words[phasezero][2]=len(c.words); c.store(14,4,9)
    c.addi(0,0,1);c.addi(1,1,2);c.addi(2,2,2);c.addi(4,4,11);c.addi(5,5,1)
    c.loop(0,count,loop);c.emit(0)
    return c,1+11*count,dict(service='selected_pair_cross_spectra',pair=[channel_i,channel_j],
       first_bin=first,bins=count,sample_rate=sample_rate,window_energy=window_energy,
       convention='conj(X_i)*X_j',count_word=0,stride=11,
       fields=['sum_xx','sum_yy','sum_real','sum_imag','Sxx','Syy','CSD_real','CSD_imag','coherence','phase_rad','valid'],
       units='PSD/CSD FS squared per Hz; phase radians; coherence dimensionless',
       history_reset_required='pair/config/source session changes',
       validity='count >=2 AND nonzero powers; caller must guarantee distinct independent frame IDs',
       maximum_instruction_steps_per_bin=140,hardware='shared existing PL scalar engine; no new arithmetic datapath')


def install_cross(memory, specification, base=600000, session=1, config=1,generation=1):
    """Four descriptors, shared private accumulation, four checkpoint contexts.

    All descriptors use one program and one accumulation region. Single scalar
    owner executes them serially. Caller MUST reset before float count reaches
    2**24, invalidate on partial/error, and not expose output until done fence.
    """
    c,n,meta=specification
    if memory.dtype!=np.float32 or memory.ndim!=1 or not memory.flags.c_contiguous:
        raise ValueError('contiguous float32 arena required')
    if base<PRIVATE or base+24576>len(memory) or n>16384 or len(c.words)>1024:
        raise ValueError('allocation bounds')
    u=memory.view(np.uint32); code=base+128;context=base+4352;output=base+8192
    u[code:code+4*len(c.words)]=np.asarray(c.words,np.uint32).ravel()
    memory[context:context+320]=0;memory[output:output+n]=0
    for slot in range(4):
        u[base+slot*16:base+(slot+1)*16]=[0x414c5531,1,code,len(c.words),context+80*slot,
            262144+slot*65536,49152,output,n,64,2,session,config,1,generation,0]
    return dict(descriptor=base,output=output,output_words=n,program_instructions=len(c.words),
                bytecode_bytes=16*len(c.words),slot_count=4,metadata=meta)
