"""P2 microcode for shared PL scalar + FFT; Python assembles, never runtime DSP.

All chains consume existing 2048-point Hann-windowed channel FFTs. Correlations
are circular correlations of those windowed records, not arbitrary-lag unbiased
estimators. Output[0:2048] holds real results; complex scratch is private.
"""
import numpy as np
from programs import Code, PRIVATE

N = 2048
FFT_INPUT = 4096
FFT_OUTPUT = 8192


def _init(channel):
    if not 0 <= channel < 6:
        raise ValueError('invalid channel')
    c = Code()
    c.u(0, 0); c.u(1, channel * 8192); c.u(2, FFT_INPUT)
    c.u(3, 0); c.f(20, 0); c.f(21, 1e-20)
    return c


def _advance(c, start):
    c.addi(0, 0, 1); c.addi(1, 1, 2); c.addi(2, 2, 2)
    c.loop(0, N, start)


def _inverse(c):
    c.emit(23, imm=2)


def _real_output(c):
    c.u(0, 0); c.u(2, FFT_OUTPUT)
    start = len(c.words)
    c.history(0, 2); c.store(0)
    c.addi(0, 0, 1); c.addi(2, 2, 2); c.loop(0, N, start)


def cepstrum(channel=0):
    """Real cepstrum IFFT(log(max(abs(X),1e-10))); no SPL interpretation."""
    c = _init(channel); start = len(c.words)
    c.load(0); c.load(1, 1, 1)
    c.emit(6, 0, 0, 0); c.emit(6, 1, 1, 1); c.emit(4, 0, 0, 1)
    c.emit(12, 0, 0, 21); c.emit(8, 0, 0); c.emit(9, 0, 0)
    c.store(0, 2); c.store(20, 2, 1); _advance(c, start)
    _inverse(c); _real_output(c); c.emit(0)
    return c, dict(service='real_cepstrum', output_count=N, units='log FS',
                   definition='IFFT(log(max(abs(windowed FFT),1e-10)))')


def correlation(channel=0, other=None, phat=False):
    """IFFT(X*conj(Y)); positive lag means channel X delayed relative to Y.

    PHAT zeros bins below the absolute cross-magnitude floor instead of creating
    arbitrary phase from zero-energy bins. No lag interpreted as DOA.
    """
    if other is not None and not 0 <= other < 6:
        raise ValueError('invalid second channel')
    c = _init(channel)
    if other is not None: c.u(4, other * 8192)
    start = len(c.words); c.load(0); c.load(1, 1, 1)
    if other is None:
        c.emit(6, 0, 0, 0); c.emit(6, 1, 1, 1)
        c.emit(4, 2, 0, 1); c.f(3, 0)
    else:
        c.load(2, 4); c.load(3, 4, 1)
        c.emit(6, 4, 0, 2); c.emit(6, 5, 1, 3); c.emit(4, 4, 4, 5)
        c.emit(6, 5, 1, 2); c.emit(6, 6, 0, 3); c.emit(5, 3, 5, 6)
        c.emit(4, 2, 4, 20); c.addi(4, 4, 2)
    if phat:
        c.emit(6, 4, 2, 2); c.emit(6, 5, 3, 3); c.emit(4, 4, 4, 5)
        c.emit(8, 4, 4); c.emit(12, 4, 4, 21)
        c.emit(7, 2, 2, 4); c.emit(7, 3, 3, 4)
    c.store(2, 2); c.store(3, 2, 1); _advance(c, start)
    _inverse(c); _real_output(c); c.emit(0)
    return c, dict(service='gcc_phat' if phat else 'cross_correlation' if other is not None else 'autocorrelation',
                   output_count=N, units='relative correlation' if phat else 'FS squared sum',
                   lag='circular: indices above 1024 map to index-2048',
                   definition='IFFT(X*conj(Y))' + (' / max(abs(X*conj(Y)),1e-20)' if phat else ''))


def envelope(channel=0, spectrum=False):
    """Analytic signal from existing windowed FFT, Hilbert magnitude.

    DC and Nyquist retained once; positive-frequency bins doubled, negative bins
    zeroed. Optional second complex FFT returns raw envelope FFT amplitude, not
    calibrated PSD. It deliberately retains the envelope DC component.
    """
    c = _init(channel); c.f(22, 2)
    # Four explicit ranges prevent doubling DC/Nyquist or leaking negative bins.
    for lo, hi, scale in ((0, 1, 1), (1, 1024, 2), (1024, 1025, 1), (1025, N, 0)):
        c.u(0, lo); c.u(1, channel*8192+2*lo); c.u(2, FFT_INPUT+2*lo)
        start = len(c.words)
        if scale:
            c.load(0); c.load(1, 1, 1)
            if scale == 2: c.emit(6, 0, 0, 22); c.emit(6, 1, 1, 22)
            c.store(0, 2); c.store(1, 2, 1)
        else: c.store(20, 2); c.store(20, 2, 1)
        c.addi(0, 0, 1); c.addi(1, 1, 2); c.addi(2, 2, 2); c.loop(0, hi, start)
    _inverse(c)
    c.u(0, 0); c.u(2, FFT_OUTPUT); c.u(5, FFT_INPUT)
    start=len(c.words); c.history(0, 2); c.history(1, 2, 1)
    c.emit(6, 0, 0, 0); c.emit(6, 1, 1, 1); c.emit(4, 0, 0, 1); c.emit(8, 0, 0)
    c.store(0); c.store(0, 5); c.store(20, 5, 1)
    c.addi(0, 0, 1); c.addi(2, 2, 2); c.addi(5, 5, 2); c.loop(0, N, start)
    if spectrum:
        c.emit(23, imm=1)
        c.u(0, 0); c.u(2, FFT_OUTPUT); start=len(c.words)
        c.history(0, 2); c.history(1, 2, 1)
        c.emit(6, 0, 0, 0); c.emit(6, 1, 1, 1); c.emit(4, 0, 0, 1); c.emit(8, 0, 0)
        c.store(0); c.addi(0, 0, 1); c.addi(2, 2, 2); c.loop(0, 1025, start)
    c.emit(0)
    return c, dict(service='envelope_spectrum' if spectrum else 'hilbert_envelope',
                   output_count=1025 if spectrum else N,
                   units='raw FFT magnitude' if spectrum else 'FS', window='existing Hann')


def install(memory, specification, base=589824, session=1, config=1, generation=1):
    c,meta=specification
    if memory.dtype != np.float32 or memory.ndim != 1 or not memory.flags.c_contiguous:
        raise ValueError('contiguous float32 arena required')
    if base % 4096 or base < PRIVATE or base+32768 > len(memory) or len(c.words)>1024:
        raise ValueError('invalid private 32768-word allocation')
    u=memory.view(np.uint32); code=base+128; context=base+4352; output=base+8192
    memory[base:base+32768]=0
    u[code:code+len(c.words)*4]=np.asarray(c.words,np.uint32).ravel()
    for slot in range(4):
        u[base+slot*16:base+(slot+1)*16]=[0x414c5531,1,code,len(c.words),context+80*slot,
            262144+slot*65536,49152,output,16384,64,2,session,config,1,generation,0]
    return dict(descriptor=base,output=output,output_words=16384,
                program_instructions=len(c.words),metadata=meta)
