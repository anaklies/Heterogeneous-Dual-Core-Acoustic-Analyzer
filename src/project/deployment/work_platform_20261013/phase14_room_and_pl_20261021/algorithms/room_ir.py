"""Room-IR analysis reference, digital relative quantities, not certification.

Inputs must be a measured or synthesized room impulse response (IR), NOT an
arbitrary running recording. Schroeder backward energy integration and the
EDT/T20/T30 fit ranges follow the commonly published ISO3382 conventions.
References:
https://www.nti-audio.com/en/applications/room-building-acoustics/reverberation-time
https://www.roomeqwizard.com/help/help/html/graph_clarity.html
https://www.roomeqwizard.com/help/help_en-GB/html/graph_waterfall.html

Absolute gain calibration cancels in relative decay/clarity; this does not remove
requirements for adequate excitation, dynamic range, channel response or valid IR.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

VERSION = "room-ir-relative/1"


def _mono(ir, fs=48000, channel=0):
    x = np.asarray(ir, dtype=np.float64)
    if x.ndim == 2:
        if not isinstance(channel, (int, np.integer)) or not 0 <= channel < x.shape[1]:
            raise ValueError("channel is outside input")
        x = x[:, channel]
    if x.ndim != 1 or len(x) < 32 or not np.isfinite(x).all():
        raise ValueError("finite mono IR or sample-major channel IR required")
    if not isinstance(fs, (int, float)) or not np.isfinite(fs) or fs <= 0:
        raise ValueError("positive finite sample rate required")
    return x


def _tail_noise(x):
    """Conservative stationary-tail test, not a full Lundeby implementation."""
    length = max(8, len(x) // 5)
    chunks = np.array_split(x[-length:], 4)
    means = np.array([np.mean(v * v) for v in chunks])
    eps = max(float(np.max(x*x)) * 1e-30, np.finfo(float).tiny)
    stationary = bool(means.max() > eps and means.max() / max(means.min(), eps) <= 3)
    floor = float(np.mean(x[-length:] ** 2)) if stationary else 0.
    return floor, stationary, means


def decay_curve(ir, fs=48000, channel=0, onset_sample=None):
    x = _mono(ir, fs, channel)
    power = x * x
    peak = float(np.max(power))
    if peak == 0:
        return dict(valid=False, reason="silent IR", algorithmVersion=VERSION)
    floor, stationary, chunks = _tail_noise(x)
    if onset_sample is None:
        threshold = max(np.sqrt(peak) * .001, 8*np.sqrt(floor))
        hits = np.flatnonzero(abs(x) >= threshold)
        if not len(hits):
            return dict(valid=False, reason="no clear IR onset above estimated tail", algorithmVersion=VERSION)
        onset = int(hits[0])
        onset_method = "automatic amplitude threshold; direct-path identity not guaranteed"
    else:
        if not isinstance(onset_sample, (int, np.integer)) or not 0 <= onset_sample < len(x)-16:
            raise ValueError("onset sample outside IR")
        onset = int(onset_sample)
        onset_method = "caller supplied IR onset"
    x = x[onset:]
    power = x*x
    raw = np.cumsum(power[::-1])[::-1]
    corrected = np.maximum(raw - floor*np.arange(len(x), 0, -1), 0)
    corrected = np.minimum.accumulate(corrected)
    if corrected[0] <= 0:
        return dict(valid=False, reason="IR energy not above stationary-tail estimate", algorithmVersion=VERSION)
    db = 10*np.log10(np.maximum(corrected/corrected[0], 1e-30))
    # Peak short-time energy establishes a conservative usable dynamic range.
    width = min(len(x), max(8, int(fs*.005)))
    smoothed = np.convolve(power[:min(len(x), int(fs*.1))], np.ones(width)/width, mode="valid")
    onset_power = float(smoothed.max()) if len(smoothed) else float(power.max())
    snr = float(10*np.log10(onset_power/floor)) if floor > 0 else None
    return dict(valid=True, timeSeconds=np.arange(len(x))/fs, decayDB=db,
                normalizedEnergy=corrected/corrected[0], onsetSample=onset,
                onsetMethod=onset_method, noisePowerFS2=floor,
                stationaryTailDetected=stationary, tailChunkPowerFS2=chunks,
                estimatedPeakToNoiseDB=snr,
                tailCorrection="stationary last20% mean energy subtraction; monotonic conservative curve",
                algorithmVersion=VERSION, calibratedSPL=False)


def _fit_decay(curve, upper, lower, name, fs):
    invalid = dict(valid=False, estimateSeconds=None, fitR2=None, method=name,
                   fitRangeDB=[upper, lower])
    if not curve.get("valid"):
        return dict(invalid, reason=curve["reason"])
    snr = curve["estimatedPeakToNoiseDB"]
    if snr is not None and snr < -lower + 10:
        return dict(invalid, reason="insufficient estimated decay-to-background margin")
    d, t = curve["decayDB"], curve["timeSeconds"]
    reached = np.flatnonzero(d <= lower)
    if not len(reached):
        return dict(invalid, reason="required decay not reached before IR ends")
    # A sudden finite-record cutoff must not masquerade as a decay slope.
    selection = (d <= upper) & (d >= lower)
    ind = np.flatnonzero(selection)
    if len(ind) < max(16, int(.001*fs)) or t[ind[-1]]-t[ind[0]] < .005:
        return dict(invalid, reason="too few points or near-step decay")
    tx, y = t[ind], d[ind]
    slope, intercept = np.polyfit(tx, y, 1)
    fitted = slope*tx+intercept
    denominator = float(np.sum((y-y.mean())**2))
    r2 = 1-float(np.sum((y-fitted)**2))/denominator if denominator else 0.
    estimate = -60/slope if slope < 0 else None
    if estimate is None or not np.isfinite(estimate) or r2 < .90:
        return dict(invalid, fitR2=float(r2), reason="nonlinear or non-decaying fit")
    return dict(valid=True, estimateSeconds=float(estimate), fitR2=float(r2), method=name,
                fitRangeDB=[upper, lower], slopeDBPerSecond=float(slope),
                fitStartSeconds=float(tx[0]), fitEndSeconds=float(tx[-1]),
                points=len(ind), reason="relative IR estimate; not a certified spatial average")


def reverberation_time(ir, fs=48000, channel=0, onset_sample=None, include_curve=True):
    curve = decay_curve(ir, fs, channel, onset_sample)
    fits = {name:_fit_decay(curve, upper, lower, name, fs) for name, upper, lower in
            [("EDT",0,-10),("T20",-5,-25),("T30",-5,-35)]}
    preferred = next((key for key in ["T30","T20","EDT"] if fits[key]["valid"]), None)
    late_valid = preferred in ["T30","T20"]
    result = dict(valid=preferred is not None, preferredMethod=preferred,
                  rt60Seconds=fits[preferred]["estimateSeconds"] if late_valid else None,
                  decayEstimateSeconds=fits[preferred]["estimateSeconds"] if preferred else None,
                  lateReverberationValid=late_valid,
                  estimateScope="late-reverberation extrapolation" if late_valid else "early-decay only" if preferred else "unavailable",
                  fits=fits, algorithmVersion=VERSION, sourceType="room_impulse_response",
                  certifiedMeasurement=False)
    if include_curve:
        result["curve"] = curve
    return result


def clarity(ir, fs=48000, channel=0, onset_sample=None):
    curve = decay_curve(ir, fs, channel, onset_sample)
    if not curve.get("valid"):
        return dict(valid=False, reason=curve["reason"], C50DB=None,C80DB=None,D50Percent=None)
    if curve['estimatedPeakToNoiseDB'] is not None and curve['estimatedPeakToNoiseDB'] < 20:
        return dict(valid=False, reason="insufficient IR-to-background margin for early/late energy ratio",
                    C50DB=None,C80DB=None,D50Percent=None)
    x = _mono(ir, fs, channel)[curve["onsetSample"]:]
    if len(x)/fs < .1:
        return dict(valid=False, reason="IR shorter than100ms after onset", C50DB=None,C80DB=None,D50Percent=None)
    p = np.maximum(x*x-curve["noisePowerFS2"], 0)
    total = float(p.sum())
    e50 = float(p[:int(.05*fs)].sum())
    e80 = float(p[:int(.08*fs)].sum())
    def ratio(early):
        late = total-early
        return float(10*np.log10(early/late)) if early>0 and late>total*1e-15 else None
    return dict(valid=total>0, C50DB=ratio(e50), C80DB=ratio(e80),
                D50Percent=100*e50/total if total else None,
                centerTimeSeconds=float((np.arange(len(p))/fs*p).sum()/total) if total else None,
                energyEarly50=e50, energyEarly80=e80, energyTotal=total,
                infiniteClarity50=total>0 and total-e50<=total*1e-15,
                infiniteClarity80=total>0 and total-e80<=total*1e-15,
                onsetSample=curve["onsetSample"], relativeGainInvariant=True,
                limitation="noise subtraction and truncation can bias energy ratios; valid measured IR required")


def octave_room_metrics(ir, fs=48000, centers=(125,250,500,1000,2000,4000,8000), fraction=1, channel=0):
    x = _mono(ir,fs,channel)
    if fraction not in [1,3]:
        raise ValueError("fraction must be1 or3")
    rows=[]
    for center in centers:
        if not np.isfinite(center) or center<=0:
            raise ValueError("positive finite band centers required")
        low,high=center*2**(-1/(2*fraction)),center*2**(1/(2*fraction))
        if high>=fs*.475 or len(x)/fs < 6/low:
            rows.append(dict(centerHz=float(center),valid=False,reason="band unavailable or fewer than6 low-edge periods"))
            continue
        sos=signal.butter(4,[low,high],btype="bandpass",fs=fs,output="sos")
        filtered=signal.sosfilt(sos,x)
        rt=reverberation_time(filtered,fs,include_curve=False)
        rows.append(dict(centerHz=float(center),lowHz=float(low),highHz=float(high),
                         valid=rt["valid"],reverberation=rt,clarity=clarity(filtered,fs),
                         filter="4th-orderButterworth bandpass, causal, notIEC61260certified",
                         limitation="low-frequency filter ringing can dominate short room decays"))
    return rows


def spectral_decay(ir, fs=48000, channel=0, nfft=2048, hop=512, maximum_candidates=5):
    x=_mono(ir,fs,channel)
    if (not isinstance(nfft,int) or nfft<32 or not isinstance(hop,int) or not 0<hop<=nfft
            or not isinstance(maximum_candidates,int) or maximum_candidates<0):
        raise ValueError("integer FFT/hop required")
    if len(x)<nfft:
        return dict(valid=False,reason="IR shorter than one transform")
    f,t,z=signal.stft(x,fs=fs,window="hann",nperseg=nfft,noverlap=nfft-hop,boundary=None,padded=False)
    power=abs(z)**2
    peak=float(power.max())
    if peak==0:
        return dict(valid=False,reason="silent IR")
    cumulative=np.cumsum(power[:,::-1],axis=1)[:,::-1]
    normalized=cumulative/np.maximum(cumulative[:,:1],np.finfo(float).tiny)
    relative=10*np.log10(np.maximum(power/peak,1e-12))
    candidates=[]
    if len(t)>=6:
        strength=power.sum(1)
        peaks,_=signal.find_peaks(strength)
        for k in peaks:
            tail=10*np.log10(np.maximum(normalized[k],1e-12))
            indices=np.flatnonzero((tail<=-5)&(tail>=-25))
            if len(indices)<4 or strength[k]<strength.max()*1e-4:
                continue
            slope,intercept=np.polyfit(t[indices],tail[indices],1)
            y=tail[indices];den=float(np.sum((y-y.mean())**2))
            r2=1-float(np.sum((slope*t[indices]+intercept-y)**2))/den if den else 0
            if slope<0 and r2>=.6:
                candidates.append(dict(frequencyHz=float(f[k]),decayEstimateSeconds=float(-60/slope),fitR2=float(r2),
                                       relativeIntegratedPowerDB=float(10*np.log10(strength[k]/strength.max()))))
    candidates=sorted(candidates,key=lambda v:v["decayEstimateSeconds"],reverse=True)[:maximum_candidates]
    return dict(valid=True,frequencyHz=f,timeSeconds=t,relativePowerDB=relative,
                cumulativeBandDecayDB=10*np.log10(np.maximum(normalized,1e-12)),
                persistentSpectralCandidates=candidates,frequencyGridHz=float(fs/nfft),
                sourceType="IR spectral decay, not ordinary running STFT",
                limitation="spectral persistence hints, not validated physical room modes or machine fault diagnosis")
