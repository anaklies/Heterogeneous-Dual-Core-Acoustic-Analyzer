"""PL scalar noise-metric programs; host computes configuration constants only.

No calibrated SPL, NC/NR or certified building/STIPA claim. Spectral A/C are
analog reference weighting of Hann PSD bins, not IEC time-domain filter banks.
Programs operate one explicitly selected microphone; no source separation.
"""
import math
import numpy as np
from programs import Code, install


def weighting_coefficients(sample_rate, weighting):
    if not math.isfinite(sample_rate) or sample_rate <= 0 or weighting not in ('A','C','Z'):
        raise ValueError('positive rate and A/C/Z required')
    f = np.arange(1025)*sample_rate/2048
    if weighting == 'Z': return np.ones(1025, np.float32)
    q=f*f
    denominator=(q+20.598997**2)*(q+12194.217**2)
    if weighting == 'A':
        denominator*=np.sqrt((q+107.65265**2)*(q+737.86223**2))
        amplitude=12194.217**2*q*q/denominator*10**(1.9997/20)
    else: amplitude=12194.217**2*q/denominator*10**(.0619/20)
    return (amplitude*amplitude).astype(np.float32)


def weighted_level(sample_rate, weighting='A', channel=0):
    """Output power, dBFS floored at -200, valid, then 1025 constant weights.

    Valid=0 for zero energy. Coefficients are immutable configuration owned by
    this service, placed at output+3. Scalar runtime integrates measured PSD.
    """
    if not 0<=channel<6: raise ValueError('channel')
    coefficients=weighting_coefficients(sample_rate,weighting)
    c=Code(); c.u(0,0); c.u(1,channel*8192+4097); c.u(3,0)
    c.f(0,0); c.f(3,sample_rate/2048); c.f(4,1e-20); c.f(5,10/math.log(10)); c.f(6,0); c.f(7,1)
    start=len(c.words); c.load(1); c.history(2,0,3); c.emit(6,1,1,2); c.emit(6,1,1,3); c.emit(4,0,0,1)
    c.addi(0,0,1); c.addi(1,1,3); c.loop(0,1025,start)
    c.store(0,3); c.emit(12,1,0,4); c.emit(9,1,1); c.emit(6,1,1,5); c.store(1,3,1)
    branch=c.emit(19,a=6,b=0,target=0); c.store(6,3,2); jump=c.emit(17,imm=0)
    c.words[branch][2]=len(c.words); c.store(7,3,2); c.words[jump][1]=len(c.words); c.emit(0)
    return (c,1028,dict(service='spectral_'+weighting+'_relative_level',units='FS2,dBFS,valid',
        calibratedSPL=False,coefficient_offset=3,coefficients=coefficients.tolist(),
        limits='Hann frame PSD integration; not IEC filterbank; no absolute noise rating'))


def time_response(sample_rate, response='FAST', channel=0, count=2048):
    """Exact sample-recursive unweighted response on last count PCM samples.

    Set descriptor readBegin to raw slot and readWords=12288. Submit each hop
    once in order; default2048 matches current nonoverlapping scheduler hop.
    Explicit count512 is only for a scheduler actually configured hop512.
    Output state power,
    dBFS, processed samples, block mean power, cumulative sum squares and LeqFS.
    Restart/reset state after gaps; zero start is not settled immediately.
    """
    if (response not in ('FAST','SLOW') or not 0<=channel<6 or not isinstance(count,int)
            or not 1<=count<=2048 or count&(count-1) or not math.isfinite(sample_rate) or sample_rate<=0):
        raise ValueError('time response configuration')
    c=Code(); c.u(0,0); c.u(1,channel*2048+2048-count); c.u(3,0)
    c.history(0,3,0); c.history(8,3,2); c.history(9,3,4); c.f(1,0)
    # Counter grows in exact multiples of count. Bound before float rounding
    # can make a repeated invocation invisible in cumulative duration.
    c.f(16,count*8388608); c.f(17,0); c.f(18,1)
    proceed=c.emit(19,a=8,b=16,target=0); c.store(17,3,7); c.emit(0)
    c.words[proceed][2]=len(c.words); c.store(18,3,7)
    alpha=math.exp(-1/(sample_rate*(.125 if response=='FAST' else 1)))
    c.f(2,alpha); c.f(3,1-alpha); c.f(4,1/8388608); c.f(5,1e-20); c.f(6,10/math.log(10)); c.f(7,count)
    start=len(c.words); c.emit(20,2,1,target=1); c.emit(22,10,2); c.emit(6,10,10,4); c.emit(6,10,10,10)
    c.emit(4,1,1,10); c.emit(6,0,0,2); c.emit(6,10,10,3); c.emit(4,0,0,10)
    c.addi(0,0,1); c.addi(1,1,1); c.loop(0,count,start)
    c.store(0,3); c.emit(12,10,0,5); c.emit(9,10,10); c.emit(6,10,10,6); c.store(10,3,1)
    c.emit(4,8,8,7); c.store(8,3,2); c.emit(7,10,1,7); c.store(10,3,3)
    c.emit(4,9,9,1); c.store(9,3,4); c.emit(7,10,9,8); c.emit(12,10,10,5); c.emit(9,10,10); c.emit(6,10,10,6); c.store(10,3,5); c.emit(0)
    return c,8,dict(service=response+'_Z_power_LeqFS',read_layout='raw_planar_pcm24',
        latest_samples=count,zero_initial=True,settle_seconds=5*(.125 if response=='FAST' else 1),
        max_sample_counter=count*8388608,validity_offset=7,
        limits='reset session on count validity=0 or data gap; no A/C time weighting')


def relative_band_difference(bands=9, metadata_matched=False):
    """Consume PL-generated reference/received band powers in private history.

    Input output[2*bands:4*bands] holds A then B. Output differences then valid
    bits. Metadata gate must represent matching gain/chain/source/spectral grid.
    Positive-power tests occur in PL; arbitrary digital differences are not Rw.
    """
    if not 1<=bands<=32: raise ValueError('bands')
    c=Code(); c.u(0,0); c.u(3,0); c.f(2,0); c.f(3,1); c.f(4,10/math.log(10))
    for i in range(bands):
        c.store(2,3,i); c.store(2,3,bands+i)
        if not metadata_matched: continue
        c.history(0,3,2*bands+i); c.history(1,3,3*bands+i)
        a=c.emit(19,a=2,b=0,target=0); j=c.emit(17,imm=0); c.words[a][2]=len(c.words)
        b=c.emit(19,a=2,b=1,target=0); k=c.emit(17,imm=0); c.words[b][2]=len(c.words)
        c.emit(7,0,0,1); c.emit(9,0,0); c.emit(6,0,0,4); c.store(0,3,i); c.store(3,3,bands+i)
        c.words[j][1]=len(c.words); c.words[k][1]=len(c.words)
    c.emit(0)
    return c,4*bands,dict(service='relative_band_difference',metadata_matched=metadata_matched,
        input_offset=2*bands,standardBuildingInsulation=False,calibratedSPL=False,
        producer_required='PL octave band energy from two explicit measurement captures')


def level_statistics(channel=0):
    """Sliding 16 equally-spaced FFT RMS levels; linear Ln sample quantiles.

    Output L10,L50,L90,LeqFS,valid,count; rolling history starts at8, scratch24.
    Floor silence at -200dBFS. Valid only after16 observations. This histogram
    is digital level statistics, not calibrated noise criteria or absolute SPL.
    Caller must schedule uniform observation cadence, reset after missing hops.
    """
    if not 0<=channel<6: raise ValueError('channel')
    c=Code(); c.u(3,0); c.u(1,channel*8192+7171); c.f(0,0); c.f(1,1)
    c.f(2,1e-10); c.f(3,20/math.log(10)); c.f(4,16)
    c.load(5); c.emit(12,5,5,2); c.emit(9,5,5); c.emit(6,5,5,3)
    # Shift old observations backward before writing newest value.
    for i in range(15,0,-1): c.history(6,3,8+i-1); c.store(6,3,8+i)
    c.store(5,3,8)
    c.history(6,3,5); c.emit(4,6,6,1); c.emit(11,6,6,4); c.store(6,3,5)
    c.store(0,3,4); warm=c.emit(19,a=6,b=4,target=0); c.store(1,3,4)
    c.words[warm][2]=len(c.words)
    c.f(7,math.log(10)/10); c.f(8,0)
    for i in range(16):
        c.history(5,3,8+i); c.store(5,3,24+i); c.emit(6,5,5,7); c.emit(10,5,5); c.emit(4,8,8,5)
    c.emit(7,8,8,4); c.emit(9,8,8); c.f(7,10/math.log(10)); c.emit(6,8,8,7); c.store(8,3,3)
    # Fixed insertion network; 120 compare-exchanges, runtime values only.
    for end in range(1,16):
        for j in range(end,0,-1):
            c.history(5,3,24+j-1); c.history(6,3,24+j)
            c.emit(11,7,5,6); c.emit(12,8,5,6); c.store(7,3,24+j-1); c.store(8,3,24+j)
    for out,lower in enumerate([13,7,1]):
        c.history(5,3,24+lower); c.history(6,3,25+lower)
        c.emit(4,5,5,6); c.f(7,.5); c.emit(6,5,5,7); c.store(5,3,out)
    c.emit(0)
    return c,40,dict(service='rolling_L10_L50_L90_LeqFS_16',observations=16,
        output_fields=['L10DBFS','L50DBFS','L90DBFS','LeqFS','valid','count'],
        uniform_cadence_required=True,calibratedSPL=False,silence_floor_dbfs=-200)


def stipa_combine(test_signal_confirmed=False):
    """Only final 14-MTF combiner; envelope/modulation extraction NOT implemented.

    Input output[16:30] observed/reference modulation ratios supplied by a PL
    producer. Confirmation alone is not sufficient for complete STIPA validity.
    Output estimate, arithmetic-valid, certified=0; never arbitrary speech STI.
    """
    c=Code(); c.u(3,0); c.f(0,0); c.f(1,0); c.f(2,1); c.f(3,1e-6); c.f(4,1-1e-6)
    c.f(5,10/math.log(10)); c.f(6,-15); c.f(7,15); c.f(8,30); c.f(15,1.3)
    if not test_signal_confirmed:
        c.store(0,3,0); c.store(0,3,1); c.store(0,3,2); c.emit(0)
    else:
        invalid=[]
        for band,alpha in enumerate([.085,.127,.230,.233,.309,.224,.173]):
            c.f(9,0)
            for pair in range(2):
                c.history(10,3,16+band*2+pair)
                invalid.extend([c.emit(19,a=10,b=1,target=0),c.emit(19,a=15,b=10,target=0)])
                c.emit(12,10,10,3); c.emit(11,10,10,4); c.emit(5,11,2,10); c.emit(7,10,10,11)
                c.emit(9,10,10); c.emit(6,10,10,5); c.emit(12,10,10,6); c.emit(11,10,10,7)
                c.emit(4,10,10,7); c.emit(7,10,10,8); c.emit(4,9,9,10)
            c.f(11,.5); c.emit(6,9,9,11); c.f(11,alpha); c.emit(6,11,9,11); c.emit(4,0,0,11)
            if band:
                c.emit(6,11,9,12); c.emit(8,11,11); c.f(13,[.085,.078,.065,.011,.047,.095][band-1]); c.emit(6,11,11,13); c.emit(5,0,0,11)
            c.emit(4,12,9,1)
        c.emit(12,0,0,1); c.emit(11,0,0,2); c.store(0,3,0); c.store(2,3,1); c.store(1,3,2)
        done=c.emit(17,imm=0)
        for p in invalid: c.words[p][2]=len(c.words)
        c.store(1,3,0); c.store(1,3,1); c.store(1,3,2); c.words[done][1]=len(c.words); c.emit(0)
    return c,30,dict(service='experimental_STIPA_MTF_combiner_only',input_offset=16,
        certified=False,full_stipa_valid=False,producer_required='7x2 modulation ratios with active-reference acquisition and validity checks')


def install_noise(memory, specification, **kwargs):
    spec=install(memory,specification,**kwargs)
    meta=specification[2]
    if 'coefficients' in meta:
        memory[spec['output']+3:spec['output']+1028]=meta['coefficients']
    for offset,values in meta.get('constant_blocks',[]):
        memory[spec['output']+offset:spec['output']+offset+len(values)]=values
    if meta.get('read_layout')=='raw_planar_pcm24':
        u=memory.view(np.uint32)
        for slot in range(4): u[spec['descriptor']+16*slot+5:spec['descriptor']+16*slot+7]=[slot*16384,12288]
    return spec


def noise_curve(family='NR', calibration=None, input_unit='dBFS'):
    """Lowest containing versioned curve; PL consumes measured octave levels.

    Input private history starts32. Require explicit SPL calibration/nominal
    reference even when levels are labelled dBSPL. No reference => valid0.
    Output [rating,valid,estimated]; no assertion of instrument certification.
    """
    if family not in ('NR','NC') or input_unit not in ('dBFS','dBSPL'):
        raise ValueError('family/unit')
    if calibration is not None:
        if calibration.get('mode') not in ('nominal','calibrated') or not calibration.get('source'):
            raise ValueError('explicit calibration source/mode required')
        if input_unit=='dBFS' and not math.isfinite(calibration.get('offsetDB',float('nan'))):
            raise ValueError('finite SPL reference offset required')
    if family=='NR':
        centers=[31.5,63,125,250,500,1000,2000,4000,8000]
        ratings=np.arange(101,dtype=float)
        a=np.array([55.4,35.4,22,12,4.8,0,-3.5,-6.1,-8])
        b=np.array([.681,.790,.870,.930,.974,1,1.015,1.025,1.030])
        table=np.round(a[None]+ratings[:,None]*b[None],1)
    else:
        centers=[63,125,250,500,1000,2000,4000,8000]
        ratings=np.arange(15,71,5,dtype=float)
        table=np.array([[47,36,29,22,17,14,12,11],[51,40,33,26,22,19,17,16],
            [54,44,37,31,27,24,22,21],[57,48,41,35,31,29,28,27],
            [60,52,45,40,36,34,33,32],[64,56,50,45,41,39,38,37],
            [67,60,54,49,46,44,43,42],[71,64,58,54,51,49,48,47],
            [74,67,62,58,56,54,53,52],[77,71,67,63,61,59,58,57],
            [80,75,71,68,66,64,63,62],[83,79,75,72,71,70,69,68]],float)
    bands=len(centers); table_offset=64; ratings_offset=table_offset+table.size
    c=Code();c.u(3,0);c.f(0,0);c.f(1,1)
    for i in range(3): c.store(0,3,i)
    if calibration is not None:
        c.f(2,calibration['offsetDB'] if input_unit=='dBFS' else 0)
        c.u(0,0); c.u(2,table_offset)
        row=len(c.words);c.u(1,0)
        band=len(c.words); c.history(3,1,32); c.emit(4,3,3,2); c.history(4,2)
        fail=c.emit(19,a=4,b=3,target=0)
        c.addi(1,1,1);c.addi(2,2,1);c.loop(1,bands,band)
        c.history(5,0,ratings_offset);c.store(5,3,0);c.store(1,3,1)
        c.f(6,int(calibration['mode']=='nominal'));c.store(6,3,2);c.emit(0)
        c.words[fail][2]=len(c.words)
        # Move table pointer from the failing band to next row. u1 is current
        # band index, so advance remaining columns using a bounded inner loop.
        advance=len(c.words);c.addi(2,2,1);c.addi(1,1,1);c.loop(1,bands,advance)
        c.addi(0,0,1);c.loop(0,len(ratings),row)
    c.emit(0)
    return c,ratings_offset+len(ratings),dict(service=family+'_reference_curve',input_offset=32,
        input_units=input_unit,centers_hz=centers,calibratedSPL=bool(calibration and calibration['mode']=='calibrated'),
        nominalEstimate=bool(calibration and calibration['mode']=='nominal'),referenceRequired=True,
        instrumentCertified=False,constant_blocks=[(table_offset,table.ravel().tolist()),(ratings_offset,ratings.tolist())],
        reference='Phase14 frozen noise_metrics: NR Arup ISO R1996 coefficient reference; NC manufacturer2018 table',
        producer_required='octave band digital levels, same calibration convention; invalid unresolved bands must suppress submission')
