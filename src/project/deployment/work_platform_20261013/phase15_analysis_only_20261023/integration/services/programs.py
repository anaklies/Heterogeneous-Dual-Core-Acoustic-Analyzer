"""Host-side PL microcode assembly only; all signal arithmetic executes in PL.

Input layout is stream_fft2048: 4096 complex words then 1025
[amplitude, PSD, binPower] triplets, channel stride 8192 float words.
No CPU/PS DSP fallback. Descriptors must be submitted through the pinned-slot
scheduler. Programs share output/history across slots; one scalar engine owns it.
"""
import math
import numpy as np

PRIVATE = 524288

def bits(x):
    return int(np.array([x], np.float32).view(np.uint32)[0])

class Code:
    def __init__(self):
        self.words = []
    def emit(self, op, d=0, a=0, b=0, imm=0, target=0):
        self.words.append([op | d << 8 | a << 13 | b << 18, imm, target, 0])
        return len(self.words) - 1
    def f(self, d, value): self.emit(1, d, imm=bits(value))
    def u(self, d, value): self.emit(14, d, imm=value)
    def addi(self, d, a, value): self.emit(15, d, a, imm=value)
    def load(self, d, index=1, offset=0): self.emit(2, d, index, imm=offset, target=1)
    def history(self, d, index=0, offset=0): self.emit(2, d, index, imm=offset, target=2)
    def store(self, d, index=0, offset=0): self.emit(3, d, index, imm=offset, target=1)
    def loop(self, a, limit, target): self.emit(16, a=a, imm=limit, target=target)

def _start(channel, first, count, component):
    if not 0 <= channel < 6 or first < 0 or count < 1 or first + count > 1025:
        raise ValueError('invalid channel/bin range')
    c = Code()
    c.u(0, 0); c.u(1, channel * 8192 + 4096 + first * 3 + component); c.u(3, 0)
    return c

def _step(c, count, start):
    c.addi(0, 0, 1); c.addi(1, 1, 3); c.loop(0, count, start)

def vector(kind, channel=0, first=0, count=1025, alpha=0.2):
    """copy/freeze snapshot, peak hold or EMA of single-sided bin power.

    EMA starts with zero history. Freeze means finish copy then stop submitting
    its descriptor; it does not stop acquisition or other services.
    """
    if kind not in ('copy', 'peak_hold', 'ema'): raise ValueError('unknown vector service')
    if not 0 < alpha <= 1: raise ValueError('alpha must be in (0,1]')
    c = _start(channel, first, count, 2)
    if kind == 'ema': c.f(2, alpha); c.f(3, 1-alpha)
    start = len(c.words); c.load(0)
    if kind == 'peak_hold': c.history(1); c.emit(12, 0, 0, 1)
    if kind == 'ema':
        c.history(1); c.emit(6, 0, 0, 2); c.emit(6, 1, 1, 3); c.emit(4, 0, 0, 1)
    c.store(0); _step(c, count, start); c.emit(0)
    return c, count, dict(service=kind, units='FS squared per bin', first_bin=first, bins=count)

def smoothing(channel=0, count=1025):
    """Three-bin [1,2,1]/4 bin-power smoothing; endpoints copied unchanged."""
    if count < 3: raise ValueError('need at least three bins')
    c = _start(channel, 0, count, 2)
    c.load(0); c.store(0); c.addi(0, 0, 1); c.addi(1, 1, 3)
    c.f(3, 2); c.f(4, 0.25)
    # u2 tracks previous-bin input; use positive offsets (no unsigned underflow).
    c.u(2, channel*8192+4098)
    start = len(c.words)
    c.load(0, 2); c.load(1, 2, 3); c.load(2, 2, 6)
    c.emit(6, 1, 1, 3); c.emit(4, 0, 0, 1); c.emit(4, 0, 0, 2); c.emit(6, 0, 0, 4); c.store(0)
    c.addi(2, 2, 3); c.addi(0, 0, 1); c.addi(1, 1, 3); c.loop(0, count-1, start)
    c.load(0); c.store(0); c.emit(0)
    return c, count, dict(service='triangular_smoothing', units='FS squared per bin', bins=count)

def band_sums(sample_rate, fraction=3, channel=0, low=31.25, high=16000):
    """Base-2 octave/third-octave relative power, inclusive lower/exclusive upper.

    Not IEC-certified filters: sums of rectangular FFT-bin PSD integration.
    """
    if fraction not in (1, 3) or not math.isfinite(sample_rate) or sample_rate <= 0:
        raise ValueError('invalid fraction or sample rate')
    if not 0 <= channel < 6 or not 0 < low <= high < sample_rate/2: raise ValueError('invalid bands')
    centers = [1000*2**(k/fraction) for k in range(-40, 41) if low <= 1000*2**(k/fraction) <= high]
    c = Code(); c.u(3, 0); c.f(2, sample_rate/2048)
    ranges=[]
    for out, fc in enumerate(centers):
        lo=fc*2**(-1/(2*fraction)); hi=fc*2**(1/(2*fraction))
        first=max(0,math.ceil(lo*2048/sample_rate)); end=min(1025,math.ceil(hi*2048/sample_rate))
        c.f(0,0)
        if first < end:
            c.u(0,first); c.u(1,channel*8192+4097+first*3)
            start=len(c.words); c.load(1); c.emit(6,1,1,2); c.emit(4,0,0,1)
            c.addi(1,1,3); c.addi(0,0,1); c.loop(0,end,start)
        c.store(0,3,out); ranges.append([first,end])
    c.emit(0)
    return c,len(centers),dict(service='relative_octave_energy',fraction=fraction,centers_hz=centers,bin_ranges=ranges,units='FS squared')

def shape(sample_rate, channel=0, first=1, count=1024, floor=1e-20):
    """Power-weighted centroid, flatness, maximum bin power and peak frequency."""
    if sample_rate <= 0 or floor <= 0: raise ValueError('invalid scale')
    c=_start(channel,first,count,2)
    c.f(0,0); c.f(1,0); c.f(2,0); c.f(3,0); c.f(4,0)
    c.f(5,floor); c.f(6,sample_rate/2048); c.f(7,count); c.f(8,first); c.f(13,1)
    start=len(c.words); c.load(9); c.emit(12,10,9,5)
    c.emit(9,11,10); c.emit(4,2,2,11); c.emit(4,0,0,9)
    c.emit(18,10,0); c.emit(4,10,10,8); c.emit(6,10,10,6)
    c.emit(6,11,9,10); c.emit(4,1,1,11)
    branch=c.emit(19,a=3,b=9,target=0); skip=c.emit(17,imm=0)
    c.words[branch][2]=len(c.words); c.emit(4,3,9,4); c.emit(4,12,10,4)
    c.words[skip][1]=len(c.words)
    _step(c,count,start)
    c.emit(12,0,0,5); c.emit(7,1,1,0); c.store(1,3,0)
    c.emit(7,2,2,7); c.emit(10,2,2); c.emit(7,0,0,7); c.emit(12,0,0,5); c.emit(7,2,2,0)
    c.emit(11,2,2,13); c.store(2,3,1) # mathematical [0,1] bound despite accumulated float roundoff
    c.store(3,3,2); c.store(12,3,3); c.emit(0)
    return c,4,dict(service='spectral_shape',fields=['centroid_hz','flatness','peak_bin_power','peak_hz'],floor=floor,bins=count,first_bin=first)

def difference(channel=0, count=1025):
    """Positive spectral flux, L1 delta and RMS delta; history after 3 summaries.

    First result compares zero-initialized history and must be marked warm-up.
    A/B is the same operation with the caller preloading fixed B and discarding
    updated history after each invocation. No event decision is implied.
    """
    c=_start(channel,0,count,2); c.f(0,0); c.f(1,0); c.f(2,0); c.f(3,0); c.f(4,count)
    start=len(c.words); c.load(5); c.history(6,0,3); c.emit(5,7,5,6)
    c.emit(12,8,7,3); c.emit(4,0,0,8); c.emit(13,8,7); c.emit(4,1,1,8)
    c.emit(6,8,7,7); c.emit(4,2,2,8); c.store(5,0,3); _step(c,count,start)
    c.store(0,3,0); c.store(1,3,1); c.emit(7,2,2,4); c.emit(8,2,2); c.store(2,3,2); c.emit(0)
    return c,count+3,dict(service='flux_delta',fields=['positive_flux','absolute_delta_sum','rms_delta'],history_offset=3,warmup_frames=1)

def install(memory, specification, base=600000, session=1, config=1, generation=1):
    """Return 4-slot descriptor family for one scheduled service.

    Distinct services require non-overlapping 24576-word allocations. Installation
    resets output history; do it only while descriptor is not active. Session,
    config, generation identify a complete program/data transaction.
    """
    c,n,meta=specification
    if memory.dtype!=np.float32 or memory.ndim!=1 or not memory.flags.c_contiguous:
        raise ValueError('arena must be a contiguous float32 vector')
    if base<PRIVATE or base+24576>len(memory) or len(c.words)>1024 or n>4096:
        raise ValueError('program/allocation bounds exceeded')
    u=memory.view(np.uint32); code=base+128; context=base+4352; output=base+8192
    u[code:code+len(c.words)*4]=np.asarray(c.words,np.uint32).ravel()
    memory[context:context+320]=0; memory[output:output+n]=0
    for slot in range(4):
        u[base+slot*16:base+(slot+1)*16]=[0x414c5531,1,code,len(c.words),context+80*slot,
            262144+slot*65536,49152,output,n,64,2,session,config,1,generation,0]
    return dict(descriptor=base,output=output,output_words=n,program_instructions=len(c.words),
                bytecode_bytes=len(c.words)*16,slot_count=4,metadata=meta)
