"""Bounded PL scalar programs; host selects bands, PL performs all signal math.

References: Phase11 sixmic_analysis/periodic.py and spectral.py. Fundamental
here is explicitly circular Hann-record periodicity, not the historical linear
zero-padded autocorrelation. No automatic DOA or physical fault diagnosis.
"""
import math
from programs import Code, _start, _step
from p2_chains import correlation, install


def harmonic_energy(fs, f0, orders=8, half_width=None, channel=0):
    if not math.isfinite(fs) or fs <= 0 or not math.isfinite(f0) or f0 <= 0 or not 1 <= orders <= 16 or not 0 <= channel < 6:
        raise ValueError('invalid harmonic configuration')
    width=fs/2048 if half_width is None else half_width
    if not 0 < width < f0/2 or orders*f0+width >= fs/2: raise ValueError('unresolved/out of range harmonics')
    bands=[(k*f0-width,k*f0+width) for k in range(1,orders+1)]
    c,ranges=_bands(fs,bands,channel); c.f(10,0);c.f(11,1e-20)
    for k in range(1,orders):
        c.history(0,3,k);c.emit(4,10,10,0)
    c.history(0,3,0);c.emit(12,0,0,11);c.emit(7,10,10,0);c.emit(8,10,10);c.store(10,3,orders)
    c.f(0,0);c.store(0,3,orders+1);c.history(0,3,0);branch=c.emit(19,a=0,b=11,target=0);c.f(0,1);c.store(0,3,orders+1);c.words[branch][2]=len(c.words)
    c.emit(0)
    return c,dict(service='selected_harmonic_energy',output_count=orders+2,bin_ranges=ranges,
        f0_hz=f0,fields=['harmonic_power_FS2']*orders+['THD_ratio','valid'],
        validity='THD requires measurable fundamental; floor-stabilized value at silence is not valid THD',
        definition='sqrt(sum(harmonic band powers order2..N)/fundamental band power)',
        scope='user selected fundamental, mixed audio; no automatic mechanical diagnosis')


def _bands(fs,bands,channel):
    c=Code();c.u(3,0); ranges=[]
    for k,(lo,hi) in enumerate(bands):
        start=max(0,math.ceil(lo*2048/fs));end=min(1025,math.floor(hi*2048/fs)+1)
        if start>=end:raise ValueError('band contains no FFT bins')
        ranges.append([start,end]);c.f(0,0);c.u(0,start);c.u(1,channel*8192+4098+3*start)
        loop=len(c.words);c.load(1);c.emit(4,0,0,1);c.addi(0,0,1);c.addi(1,1,3);c.loop(0,end,loop);c.store(0,3,k)
    return c,ranges


def sidebands(fs, carrier, spacing, half_width, channel=0):
    if not all(math.isfinite(x) for x in (fs,carrier,spacing,half_width)) or not 0<=channel<6 or fs<=0 or half_width<=0 or spacing<=2*half_width or carrier-spacing-half_width<0 or carrier+spacing+half_width>=fs/2:
        raise ValueError('resolved non-overlapping bands required')
    c,ranges=_bands(fs,[(f-half_width,f+half_width) for f in (carrier-spacing,carrier,carrier+spacing)],channel)
    c.f(3,1e-20);c.history(1,3,1);c.emit(12,1,1,3)
    for src,dst in ((0,3),(2,4)):
        c.history(0,3,src);c.emit(7,0,0,1);c.store(0,3,dst)
    c.f(0,0);c.store(0,3,5);c.history(0,3,1);branch=c.emit(19,a=0,b=3,target=0);c.f(0,1);c.store(0,3,5);c.words[branch][2]=len(c.words)
    c.emit(0)
    return c,dict(service='selected_sidebands',output_count=6,bin_ranges=ranges,
        fields=['lower_FS2','carrier_FS2','upper_FS2','lower_carrier_ratio','upper_carrier_ratio','valid'],
        validity='ratios valid only when carrier power > 1e-20',scope='integrated existing FFT bins, not peak-bin ratios')


def spectral_kurtosis(channel=0, first=0, count=1025):
    """Cumulative same-configuration frames; outputs count then [sum,sum2,K,valid].

    Caller MUST submit exactly once per new pinned frame and reset state on
    channel/window/sample-rate/config changes. Overlap bias is not corrected.
    """
    c=_start(channel,first,count,2); c.f(20,0);c.f(21,1);c.f(22,2);c.f(23,1e-20);c.f(24,3)
    c.history(10,3);c.emit(4,10,10,21);c.store(10,3);c.u(2,1)
    start=len(c.words);c.load(0);c.history(1,2);c.history(2,2,1)
    c.emit(4,1,1,0);c.emit(6,0,0,0);c.emit(4,2,2,0);c.store(1,2);c.store(2,2,1)
    c.emit(6,3,1,1);c.emit(12,3,3,23);c.emit(6,4,10,2);c.emit(7,4,4,3);c.emit(5,4,4,21)
    c.emit(4,5,10,21);c.emit(5,6,10,21);c.emit(12,6,6,21);c.emit(7,5,5,6);c.emit(6,4,4,5);c.emit(5,4,4,21)
    c.store(4,2,2);c.store(20,2,3)
    skip=c.emit(19,a=10,b=24,target=0)
    silent=c.emit(19,a=1,b=23,target=0)
    c.store(21,2,3)
    c.words[skip][2]=c.words[silent][2]=len(c.words)
    c.addi(2,2,4);_step(c,count,start);c.emit(0)
    return c,dict(service='cumulative_spectral_kurtosis',output_count=1+4*count,first_bin=first,bins=count,
        definition='(M+1)/(M-1)*(M*sum(P^2)/sum(P)^2-1)-1',
        validity='per bin valid flag: M>=3 and sum(P)>=1e-20; reset before M loses float32 integer precision',
        fresh_frame_contract='one call per unique frameId; context resume is not another frame; no host DSP',
        reset='zero whole service output on source/channel/config change',units='dimensionless')


def periodicity(fs, min_hz=100, max_hz=2000, min_correlation=.7, channel=0):
    if not math.isfinite(fs) or not 0 < min_hz < max_hz < fs/2 or not 0<min_correlation<1:raise ValueError('invalid limits')
    lo=max(1,math.ceil(fs/max_hz));hi=min(512,math.floor(fs/min_hz))
    if hi<=lo:raise ValueError('insufficient periods')
    c,_=correlation(channel);c.words.pop();c.u(3,0);c.u(2,lo);c.f(10,0);c.f(11,0);c.f(12,1e-20);c.f(13,fs);c.f(14,min_correlation)
    c.history(15,3);c.emit(12,15,15,12)
    start=len(c.words);c.history(0,2);c.emit(7,0,0,15)
    branch=c.emit(19,a=10,b=0,target=0);skip=c.emit(17,imm=0)
    c.words[branch][2]=len(c.words);c.emit(4,10,0,11);c.emit(18,16,2)
    c.words[skip][1]=len(c.words);c.addi(2,2,1);c.loop(2,hi+1,start)
    c.f(0,0);c.store(0,3,2);c.store(0,3,0);c.store(10,3,1)
    reject=c.emit(19,a=10,b=14,target=0)
    c.emit(12,16,16,12);c.emit(7,0,13,16);c.store(0,3,0);c.f(0,1);c.store(0,3,2)
    c.words[reject][2]=len(c.words);c.emit(0)
    return c,dict(service='circular_periodicity',output_count=3,fields=['frequency_hz','normalized_peak','valid'],
        lag_range=[lo,hi],min_correlation=min_correlation,
        definition='maximum normalized circular Hann-record autocorrelation in bounded lag interval',
        limitations='integer-lag, may select harmonics/subharmonics; not unique physical fundamental; differs historical linear estimator')


def zoom_spectrum(fs, center_hz, decimation=2, taps=65):
    """True captured-record heterodyne + FIR + decimation + 2048 complex FFT.

    Caller copies normalized recording into the private raw range BEFORE start.
    No host filtering: oscillator, FIR, decimation/window and FFT execute in PL.
    The record must remain immutable across all chunks. Not a realtime service.
    """
    import numpy as np
    if not math.isfinite(fs) or fs<=0 or decimation not in (2,4) or not isinstance(taps,int) or taps<17 or taps>129 or taps%2!=1:
        raise ValueError('invalid Zoom configuration')
    half=fs/(2*decimation)
    if not math.isfinite(center_hz) or not half<=center_hz<=fs/2-half:raise ValueError('complex output band exceeds original Nyquist')
    D=decimation;T=taps;L=2047*D+T;raw=12288;mixed=raw+L
    # Windowed sinc FIR, normalized DC response; host prepares coefficients only.
    t=np.arange(T)-(T-1)/2;fc=.4/D
    h=2*fc*np.sinc(2*fc*t)*np.hamming(T);h=h/h.sum()
    c=Code();c.u(0,0);c.u(1,raw);c.u(2,mixed);c.f(10,1);c.f(11,0)
    w=-2*math.pi*center_hz/fs;c.f(12,math.cos(w));c.f(13,math.sin(w))
    start=len(c.words);c.history(0,1);c.emit(6,1,0,10);c.emit(6,2,0,11);c.store(1,2);c.store(2,2,1)
    c.emit(6,3,10,12);c.emit(6,4,11,13);c.emit(5,3,3,4)
    c.emit(6,4,10,13);c.emit(6,5,11,12);c.emit(4,11,4,5);c.f(5,0);c.emit(4,10,3,5)
    c.addi(0,0,1);c.addi(1,1,1);c.addi(2,2,2);c.loop(0,L,start)
    # Direct FIR evaluated only on the selected decimation phase. Unrolling taps
    # would exceed code bounds; coefficients are sequentially walked in history.
    coefficients=mixed+2*L
    if coefficients+T>65536:raise ValueError('Zoom private area too small')
    c.u(0,0);c.u(1,mixed);c.u(2,4096);c.f(20,0)
    start=len(c.words);c.f(0,0);c.f(1,0);c.u(3,0);c.u(4,coefficients)
    # u5 starts at mixed+i*D*2 and moves forward across taps.
    c.addi(5,1,0);inner=len(c.words);c.history(2,5);c.history(3,5,1);c.history(4,4)
    c.emit(6,2,2,4);c.emit(6,3,3,4);c.emit(4,0,0,2);c.emit(4,1,1,3)
    c.addi(5,5,2);c.addi(4,4,1);c.addi(3,3,1);c.loop(3,T,inner)
    # Explicit periodic Hann coefficients prepared with filter constants, not data.
    window=coefficients+T;c.u(6,window);c.emit(24,7,0,0);c.addi(7,0,window)
    c.history(4,7);c.emit(6,0,0,4);c.emit(6,1,1,4);c.store(0,2);c.store(1,2,1)
    c.addi(0,0,1);c.addi(1,1,2*D);c.addi(2,2,2);c.loop(0,2048,start)
    c.emit(23,imm=1)
    # Return shifted complex FFT, normalized two-sided complex amplitude/power.
    c.u(0,0);c.u(1,8192);c.u(2,0);c.f(10,1/1024);c.f(11,1/(fs/D*768))
    start=len(c.words);c.history(0,1);c.history(1,1,1);c.emit(6,2,0,0);c.emit(6,3,1,1);c.emit(4,2,2,3)
    c.emit(8,3,2);c.emit(6,3,3,10);c.emit(6,2,2,11);c.store(3,2);c.store(2,2,1)
    c.addi(0,0,1);c.addi(1,1,2);c.addi(2,2,2);c.loop(0,2048,start);c.emit(0)
    return c,dict(service='heterodyne_fir_zoom',output_count=4096,raw_offset=raw,raw_samples=L,
        coefficient_offset=coefficients,coefficients=h.tolist(),window_offset=window,
        decimation=D,sample_rate=fs,center_hz=center_hz,fft_length=2048,
        frequency_axis='unshifted: center + fftfreq(2048, D/fs); caller fftshift for monotonic display',
        output_layout='2048 pairs: two-sided complex amplitude FS, PSD FS2/Hz; real-tone amplitude needs factor2',
        effective_sample_rate_hz=fs/D,resolution_hz=fs/D/2048,filter_delay_samples=(T-1)/2,
        first_output_time_samples=(T-1)/2,record_samples=L,private_output_words=65536,
        validity='record immutability; all samples finite; only central |f-center|<=0.30*fs/D recommended passband',
        limitations='finite FIR transition/stopband; filter start transient excluded using T real samples; no continuous stream claim')


def install_zoom(memory, specification, base=589824, **kwargs):
    import numpy as np
    if base+8192+65536>len(memory):raise ValueError('Zoom needs 73728-word private allocation')
    s=install(memory,specification,base=base,**kwargs)
    out=s['output'];memory[out:out+65536]=0
    u=memory.view(np.uint32)
    for slot in range(4):u[base+slot*16+8]=65536
    meta=s['metadata'];memory[out+meta['coefficient_offset']:out+meta['coefficient_offset']+len(meta['coefficients'])]=meta['coefficients']
    memory[out+meta['window_offset']:out+meta['window_offset']+2048]=np.hanning(2049)[:-1]
    s['output_words']=65536
    return s
