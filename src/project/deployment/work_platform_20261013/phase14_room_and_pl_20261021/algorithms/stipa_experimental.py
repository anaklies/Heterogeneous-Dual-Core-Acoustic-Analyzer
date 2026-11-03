"""Reference-ratio STIPA research estimator; not an IEC-certified instrument.

Signal bands/modulation pairs and male weights cross-checked against:
https://github.com/zawi01/stipa (Zaviska, BrnoUniversity, GPL3 reference).
Implementation here uses independent joint least-squares envelope demodulation.
NTi explains playback/test requirements: https://www.nti-audio.com/en/applications/evacuation-systems/speech-intelligibility-stipa/
No auditory masking or absolute hearing-threshold correction without SPL data.
"""
import numpy as np
from scipy import signal

FS = 48000
CENTERS = np.array([125,250,500,1000,2000,4000,8000.],float)
MODULATION = np.array([[1.6,8],[1,5],[.63,3.15],[2,10],[1.25,6.25],[.8,4],[2.5,12.5]])
ALPHA = np.array([.085,.127,.230,.233,.309,.224,.173])
BETA = np.array([.085,.078,.065,.011,.047,.095])


def _audio(x):
    x=np.asarray(x,dtype=float)
    if x.ndim!=1 or not len(x) or not np.isfinite(x).all():
        raise ValueError('finite mono normalized audio required; select one microphone explicitly')
    return x


def combine_mtf(mtf):
    m=np.asarray(mtf,float)
    if m.shape!=(7,2) or not np.isfinite(m).all() or np.any(m<0):
        raise ValueError('finite nonnegative7x2 modulation ratios required')
    m=np.clip(m,1e-12,1-1e-12)
    apparent=np.clip(10*np.log10(m/(1-m)),-15,15)
    transmission=(apparent+15)/30
    band=transmission.mean(1)
    value=float(np.clip(ALPHA@band-BETA@np.sqrt(band[:-1]*band[1:]),0,1))
    return dict(estimate=value,modulationTransmissionIndices=band.tolist(),
                apparentSNRDB=apparent.tolist(),transmissionIndices=transmission.tolist())


def generate_reference(seconds=20.,seed=14211021):
    if not np.isfinite(seconds) or not 15<=seconds<=60:
        raise ValueError('15..60seconds required; this is an active measurement, not a short detection frame')
    rng=np.random.default_rng(seed);warm=2*FS;n=round(seconds*FS)
    t=np.arange(n+warm)/FS;total=np.zeros(n+warm)
    levels=np.array([-2.5,.5,0,-6,-12,-18,-24.])
    for center,pair,level in zip(CENTERS,MODULATION,levels):
        white=rng.normal(size=n+warm)
        # Narrow carrier support, then full-octave receiving filters.
        sos=signal.butter(10,[center/2**.25,center*2**.25],btype='bandpass',fs=FS,output='sos')
        carrier=signal.sosfilt(sos,white)
        carrier/=max(np.sqrt(np.mean(carrier[warm:]**2)),1e-20)
        intensity=.5*(1+.55*(np.sin(2*np.pi*pair[0]*t)-np.sin(2*np.pi*pair[1]*t)))
        if intensity.min()<-1e-10:
            raise ArithmeticError('test-signal intensity became negative')
        total+=carrier*np.sqrt(np.maximum(intensity,0))*10**(level/20)
    total=total[warm:];total*=.04/max(np.sqrt(np.mean(total**2)),1e-20)
    if abs(total).max()>=1:
        raise ArithmeticError('generated reference clips')
    return total,dict(profile='research_STIPA14_reference',sampleRate=FS,seconds=seconds,seed=seed,
        centersHz=CENTERS.tolist(),modulationHz=MODULATION.tolist(),referenceRequired=True,
        calibratedPlayback=False,standardTestSignalCertified=False)


def modulation_depth(envelope,sample_rate,pair):
    e=np.asarray(envelope,float);t=np.arange(len(e))/sample_rate
    if e.ndim!=1 or not np.isfinite(e).all() or len(e)<20:
        raise ValueError('finite intensity envelope required')
    # Joint fit prevents leakage between the two modulations on finite records.
    columns=[np.ones(len(e)),t-t.mean()]
    for f in pair:
        columns.extend([np.sin(2*np.pi*f*t),np.cos(2*np.pi*f*t)])
    coef,_,rank,_=np.linalg.lstsq(np.column_stack(columns),e,rcond=None)
    if rank!=6 or coef[0]<=0:
        return np.zeros(2),False
    return np.array([np.hypot(*coef[2:4]),np.hypot(*coef[4:6])])/coef[0],True


def _envelopes(x):
    envelopes=[];power=[]
    lp=signal.butter(4,40,fs=FS,output='sos')
    for center in CENTERS:
        sos=signal.butter(9,[center/np.sqrt(2),center*np.sqrt(2)],fs=FS,btype='bandpass',output='sos')
        y=signal.sosfilt(sos,x)
        intensity=signal.sosfilt(lp,y*y)
        e=signal.resample_poly(intensity,1,240)
        # Same transient discard for reference and observation.
        envelopes.append(e[60:-60]);power.append(float(np.mean(y[int(.3*FS):-int(.3*FS)]**2)))
    return envelopes,np.array(power)


def measure(recording,reference,*,test_signal_confirmed=False):
    observed=_audio(recording);reference=_audio(reference)
    base=dict(method='reference_ratio_STIPA_research_v1',certified=False,calibratedSPL=False,
        auditoryMaskingCorrected=False,absoluteHearingThresholdCorrected=False,
        backgroundAlreadyPresentInRecording=True,separateNoiseCorrectionApplied=False,
        notSpeechRecognition=True)
    if not test_signal_confirmed:
        return dict(base,valid=False,estimate=None,reason='explicit known test signal confirmation required; arbitrary speech unsupported')
    if min(len(observed),len(reference))<15*FS or max(len(observed),len(reference))>60*FS:
        return dict(base,valid=False,estimate=None,reason='observation duration must be15..60seconds')
    if np.max(abs(observed))>=1 or np.max(abs(reference))>=1:
        return dict(base,valid=False,estimate=None,reason='digital clipping; repeat with lower gain')
    er,pr=_envelopes(reference);eo,po=_envelopes(observed)
    mr=[];mo=[]
    for k,pair in enumerate(MODULATION):
        r,rv=modulation_depth(er[k],200,pair);o,ov=modulation_depth(eo[k],200,pair)
        if not rv or not ov or pr[k]<1e-18 or po[k]<1e-18 or np.min(r)<.15:
            return dict(base,valid=False,estimate=None,reason=f'insufficient reference/observed modulation support in band{k}',
                        referenceBandPowerFS2=pr.tolist(),observedBandPowerFS2=po.tolist())
        mr.append(r);mo.append(o)
    ratio=np.array(mo)/mr
    if np.max(ratio)>1.3:
        return dict(base,valid=False,estimate=None,reason='modulation ratio exceeds1.3; possible transient/instability',
                    rawModulationRatios=ratio.tolist())
    result=combine_mtf(ratio)
    return dict(base,**result,valid=True,reason='experimental estimate; no IEC verification or calibrated masking corrections',
        rawModulationRatios=ratio.tolist(),referenceModulationDepths=np.array(mr).tolist(),
        observedModulationDepths=np.array(mo).tolist(),referenceBandPowerFS2=pr.tolist(),observedBandPowerFS2=po.tolist(),
        observationSeconds=len(observed)/FS,referenceSeconds=len(reference)/FS)
