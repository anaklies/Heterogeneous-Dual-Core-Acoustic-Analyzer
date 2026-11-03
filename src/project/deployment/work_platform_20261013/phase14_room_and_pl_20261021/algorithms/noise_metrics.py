"""Relative/digital noise metrics, never uncalibrated dBFS advertised as SPL.

NR coefficients: https://strutt.arup.com/help/Curves/NRCurve.htm (ISO R1996).
NC reference table: Crystal Instruments2018 public63Hz–8kHz table, NC15–70.
Weighting uses the conventional analog A/C transfer functions and bilinear
conversion at48kHz. This is a numerical reference, not IEC instrument approval.
"""
from dataclasses import dataclass
import math
import numpy as np
from scipy import signal

VERSION = "phase14-noise/1"
NR_CENTERS = np.array([31.5,63.,125.,250.,500.,1000.,2000.,4000.,8000.])
NR_A = np.array([55.4,35.4,22.,12.,4.8,0.,-3.5,-6.1,-8.])
NR_B = np.array([.681,.790,.870,.930,.974,1.,1.015,1.025,1.030])
NC_CENTERS = NR_CENTERS[1:].copy()
NC_LEVELS = np.array([
    [47,36,29,22,17,14,12,11], [51,40,33,26,22,19,17,16],
    [54,44,37,31,27,24,22,21], [57,48,41,35,31,29,28,27],
    [60,52,45,40,36,34,33,32], [64,56,50,45,41,39,38,37],
    [67,60,54,49,46,44,43,42], [71,64,58,54,51,49,48,47],
    [74,67,62,58,56,54,53,52], [77,71,67,63,61,59,58,57],
    [80,75,71,68,66,64,63,62], [83,79,75,72,71,70,69,68],
],dtype=float)


def _audio(x):
    value = np.asarray(x, dtype=np.float64)
    if value.ndim == 1:
        value = value[:, None]
    if value.ndim != 2 or not len(value) or not value.shape[1] or not np.isfinite(value).all():
        raise ValueError("nonempty finite sample-major digital audio required")
    return value


def _fs(fs):
    if fs != 48000:
        raise ValueError("frozen48kHz reference required")


def analog_weighting_db(frequency_hz, weighting="A"):
    """Conventional A/C reference amplitudes;Z is flat. DC has zero A/C gain."""
    f = np.asarray(frequency_hz, dtype=float)
    weighting = weighting.upper()
    if not np.isfinite(f).all() or np.any(f < 0) or weighting not in {"A","C","Z"}:
        raise ValueError("nonnegative finite frequency and A/C/Z required")
    if weighting == "Z":
        return np.zeros_like(f)
    f2 = f*f
    with np.errstate(divide="ignore", invalid="ignore"):
        if weighting == "A":
            ratio = (12194.217**2*f2*f2 / ((f2+20.598997**2)*(f2+12194.217**2)
                     * np.sqrt((f2+107.65265**2)*(f2+737.86223**2))))
            result = 20*np.log10(ratio)+1.9997
        else:
            ratio = 12194.217**2*f2 / ((f2+20.598997**2)*(f2+12194.217**2))
            result = 20*np.log10(ratio)+.0619
    return result


def weighting_sos(weighting="A", fs=48000):
    _fs(fs)
    weighting = weighting.upper()
    if weighting == "Z":
        return np.array([[1.,0,0,1,0,0]])
    if weighting not in {"A","C"}:
        raise ValueError("A/C/Z weighting required")
    f1,f2,f3,f4 = 20.598997,107.65265,737.86223,12194.217
    poles = -2*np.pi*np.array([f1,f1,f4,f4]+([f2,f3] if weighting=="A" else []))
    zeros = np.zeros(4 if weighting=="A" else 2)
    gain = (2*np.pi*f4)**2 * 10**((1.9997 if weighting=="A" else .0619)/20)
    z,p,k = signal.bilinear_zpk(zeros,poles,gain,fs)
    sos = signal.zpk2sos(z,p,k)
    # Match digital1kHz exactly. High-frequency bilinear warping is reported,
    # not hidden by calling the filter an instrument-class realization.
    _, response = signal.sosfreqz(sos,worN=[1000],fs=fs)
    sos[0,:3] /= abs(response[0])
    return sos


class FrequencyWeighting:
    def __init__(self, weighting="A", fs=48000):
        self.fs = fs
        self.weighting = weighting.upper()
        self.sos = weighting_sos(self.weighting,fs)
        self.state = None

    def reset(self):
        self.state = None

    def process(self, audio):
        x = _audio(audio)
        if self.state is None:
            self.state = np.zeros((len(self.sos),2,x.shape[1]))
        elif self.state.shape[-1] != x.shape[1]:
            raise ValueError("channel change requires reset")
        out,self.state = signal.sosfilt(self.sos,x,axis=0,zi=self.state)
        return out


class TimeWeightedPower:
    """Causal exponential squared-signal average; startup uses zero initial state."""
    def __init__(self, response="FAST", fs=48000):
        _fs(fs)
        response = response.upper()
        if response not in {"FAST","SLOW"}:
            raise ValueError("FAST or SLOW required")
        self.response = response
        self.tau = .125 if response=="FAST" else 1.
        self.fs = fs
        self.alpha = math.exp(-1/(fs*self.tau))
        self.state = None
        self.samples = 0

    def reset(self):
        self.state = None
        self.samples = 0

    def process(self, audio):
        x = _audio(audio)
        if self.state is None:
            self.state = np.zeros((1,x.shape[1]))
        elif self.state.shape[-1] != x.shape[1]:
            raise ValueError("channel change requires reset")
        p,self.state = signal.lfilter([1-self.alpha],[1,-self.alpha],x*x,axis=0,zi=self.state)
        self.samples += len(x)
        return dict(powerFS2=p, rmsFS=np.sqrt(np.maximum(p,0)),
                    settled=self.samples>=math.ceil(5*self.tau*self.fs),
                    response=self.response,timeConstantSeconds=self.tau,
                    unit="digitalFS2,notPa2", calibratedSPL=False)


def equivalent_level(audio, fs=48000, weighting="Z"):
    _fs(fs)
    x = _audio(audio)
    if weighting.upper() != "Z":
        x = FrequencyWeighting(weighting,fs).process(x)
    mean = np.mean(x*x,axis=0)
    level = [float(10*np.log10(p)) if p>0 else None for p in mean]
    return dict(equivalentLevelDBFS=level,meanPowerFS2=mean.tolist(),
                durationSeconds=len(x)/fs,weighting=weighting.upper(),
                valid=(mean>0).tolist(),calibratedSPL=False,
                definition="10log10(mean(weightedAudio2)/digitalFullScale2); notLAeqSPL")


def level_statistics(levels_dbfs, sample_interval_seconds=1.):
    """Equally spaced level observations;Ln means exceeded n percent of time."""
    levels = np.asarray(levels_dbfs, dtype=float)
    if levels.ndim!=1 or not len(levels) or not np.isfinite(levels).all():
        raise ValueError("finite1D uniform-time level samples required")
    if not np.isfinite(sample_interval_seconds) or sample_interval_seconds<=0:
        raise ValueError("positive uniform sample interval required")
    # Subtract max to prevent overflow for otherwise valid numeric levels.
    maximum = levels.max()
    leq = maximum + 10*np.log10(np.mean(10**((levels-maximum)/10)))
    return dict(equivalentLevelDBFS=float(leq),minimumDBFS=float(levels.min()),
                maximumDBFS=float(maximum),L10DBFS=float(np.percentile(levels,90)),
                L50DBFS=float(np.percentile(levels,50)),L90DBFS=float(np.percentile(levels,10)),
                observations=len(levels),durationSeconds=len(levels)*sample_interval_seconds,
                percentileConvention="Ln is exceeded n percent; linear sample quantile",
                calibratedSPL=False)


def octave_band_powers(audio, centers=NR_CENTERS, fs=48000, nfft=8192):
    _fs(fs)
    x = _audio(audio)
    centers = np.asarray(centers,dtype=float)
    if centers.ndim!=1 or not len(centers) or not np.isfinite(centers).all() or np.any(centers<=0):
        raise ValueError("positive finite octave centers required")
    if not isinstance(nfft,int) or nfft<16:
        raise ValueError("bounded FFT length required")
    nfft = min(nfft,len(x))
    f,p = signal.welch(x,fs,window="hann",nperseg=nfft,noverlap=nfft//2,
                       detrend="constant",scaling="density",axis=0)
    df = fs/nfft
    values=[];valid=[];bins=[]
    for fc in centers:
        low,high=fc/np.sqrt(2),fc*np.sqrt(2)
        mask=(f>=low)&(f<high)
        count=int(mask.sum())
        values.append(np.sum(p[mask],axis=0)*df)
        valid.append(count>=2 and high<=fs/2)
        bins.append(count)
    power=np.array(values)
    return dict(centerHz=centers,powerFS2=power,bandValid=np.array(valid),
                resolvedBins=np.array(bins),frequencyResolutionHz=df,
                method="WelchPSD center-bin octave integration,notIECfilterbank")


def relative_insulation(source_audio, receiver_audio, source_metadata, receiver_metadata,
                        centers=NR_CENTERS,fs=48000,nfft=8192):
    """Same-chain/gain/source relative band difference;notRw/DnT/standardTL."""
    keys=("gain_id","measurement_chain_id","source_configuration_id")
    for key in keys:
        if not source_metadata.get(key) or source_metadata.get(key)!=receiver_metadata.get(key):
            raise ValueError(f"matching nonempty {key} metadata required")
    if source_metadata.get("sample_rate",fs)!=fs or receiver_metadata.get("sample_rate",fs)!=fs:
        raise ValueError("sample-rate metadata mismatch")
    source=octave_band_powers(source_audio,centers,fs,nfft)
    receiver=octave_band_powers(receiver_audio,centers,fs,nfft)
    if source['powerFS2'].shape!=receiver['powerFS2'].shape:
        raise ValueError("same selected channels required")
    # Same FFT resolution is necessary for consistent band-bin integration.
    if source['frequencyResolutionHz']!=receiver['frequencyResolutionHz']:
        raise ValueError("equal spectral grid required; use enough samples in both recordings")
    a,b=source['powerFS2'],receiver['powerFS2']
    valid=(a>0)&(b>0)&source['bandValid'][:,None]&receiver['bandValid'][:,None]
    result=np.full_like(a,np.nan)
    result[valid]=10*np.log10(a[valid]/b[valid])
    return dict(centerHz=np.asarray(centers),relativeBandLevelDifferenceDB=result,valid=valid,
                metadataChecked=list(keys),calibrationRequiredForSameChainDifference=False,
                standardBuildingInsulation=False,
                limits="source stability,backgroundfloor,spatial averaging and roomR correction not certified")


def nr_curves(ratings=np.arange(0,101)):
    rating=np.asarray(ratings,dtype=float)
    if rating.ndim!=1 or not len(rating) or not np.isfinite(rating).all() or np.any(np.diff(rating)<=0):
        raise ValueError("increasing finite curve numbers required")
    return dict(name="NR",centerHz=NR_CENTERS.copy(),ratings=rating,
                levelsDBSPL=np.round(NR_A[None]+rating[:,None]*NR_B[None],1),
                reference="ArupStrutt ISO R1996 coefficients; https://strutt.arup.com/help/Curves/NRCurve.htm",
                instrumentCertified=False)


def nc_curves():
    """Traditional8-band NC15..70 reference. No16/31.5Hz orRNC extension."""
    return dict(name="NC",centerHz=NC_CENTERS.copy(),ratings=np.arange(15,71,5,dtype=float),
                levelsDBSPL=NC_LEVELS.copy(),
                reference="Crystal Instruments2018 traditionalNC table; https://www.crystalinstruments.com/blog/2018/9/27/noise-criteria-nc-curves",
                tableVersion="2018manufacturer-public-63to8000Hz-NC15to70-step5",
                interpolation=False,instrumentCertified=False)


def nominal_inmp441_offset(sensitivity_dbfs_at94):
    """Operator-selected nominal sensitivity only;not an acoustic calibration."""
    if not np.isfinite(sensitivity_dbfs_at94):
        raise ValueError("finite nominal sensitivity required")
    return dict(mode="nominal",offsetDB=94-float(sensitivity_dbfs_at94),
                source="operator-selected nominal microphone sensitivity at94dBSPL; no per-unit calibration",
                referenceConventionAssumed="sensitivityDBFS uses same mean-square full-scale convention as these metrics")


def noise_curve_rating(band_levels, centers=None, family="NR", input_unit="dBFS",
                       calibration=None, curves=None):
    """Lowest containing curve. NoNC/NR number without explicitSPL reference."""
    family=family.upper()
    if family not in {"NR","NC"}:
        raise ValueError("NR orNC required")
    levels=np.asarray(band_levels,dtype=float)
    centers=np.asarray((NR_CENTERS if family=="NR" else NC_CENTERS) if centers is None else centers,dtype=float)
    if levels.ndim!=1 or levels.shape!=centers.shape or not np.isfinite(levels).all():
        raise ValueError("finite octave-band levels aligned with centerHz required")
    if input_unit not in {"dBFS","dBSPL"}:
        raise ValueError("explicit dBFS or dBSPL required")
    if calibration is None or calibration.get("mode") not in {"calibrated","nominal"}:
        return dict(valid=False,rating=None,family=family,reason="SPL_reference_required_dBFS_is_not_SPL")
    if not calibration.get('source'):
        raise ValueError("calibration/nominal source description required")
    if input_unit=="dBFS":
        offset=float(calibration.get("offsetDB",np.nan))
        if not np.isfinite(offset):
            raise ValueError("finite calibration/nominal offsetDB required")
        levels=levels+offset
    if curves is None:
        curves=nc_curves() if family=="NC" else nr_curves()
    f=np.asarray(curves['centerHz'],float);r=np.asarray(curves['ratings'],float);table=np.asarray(curves['levelsDBSPL'],float)
    if (curves.get('name','').upper()!=family or not curves.get('reference') or
        table.shape!=(len(r),len(f)) or len(r)<2 or not np.isfinite(table).all() or
        not np.isfinite(r).all() or np.any(np.diff(r)<=0) or np.any(np.diff(table,axis=0)<0)):
        raise ValueError("monotonic versioned curve table required")
    if len(f)!=len(centers) or not np.allclose(f,centers,rtol=1e-8,atol=1e-8):
        raise ValueError("all required octave bands and identical centers required")
    fit=np.all(levels[None]<=table+1e-9,axis=1)
    if not fit.any():
        return dict(valid=False,rating=None,family=family,reason="above_highest_curve",estimated=calibration['mode']=='nominal')
    j=int(np.flatnonzero(fit)[0]);margin=table[j]-levels;critical=int(np.argmin(margin))
    return dict(valid=True,rating=float(r[j]),family=family,estimated=calibration['mode']=='nominal',
                criticalBandHz=float(f[critical]),minimumMarginDB=float(margin[critical]),
                bandLevelsDBSPL=levels.tolist(),reference=curves['reference'],
                belowLowestCurve=bool(j==0 and np.all(margin>0)),instrumentCertified=False)
