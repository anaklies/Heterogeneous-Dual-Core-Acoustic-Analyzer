"""Known excitation and regularized IR recovery; no playback driver or GUI."""
import numpy as np
from scipy import signal,fft


def logarithmic_sweep(seconds=2.,sample_rate=48000,low_hz=80.,high_hz=16000.):
    if sample_rate!=48000 or not .5<=seconds<=5 or not 20<=low_hz<high_hz<=20000:
        raise ValueError('48kHz,0.5..5seconds and bounded sweep band required')
    n=round(seconds*sample_rate);t=np.arange(n)/sample_rate
    x=signal.chirp(t,low_hz,seconds,high_hz,method='logarithmic')
    return .15*x*signal.windows.tukey(n,.04),dict(sampleRate=sample_rate,seconds=seconds,
        lowHz=low_hz,highHz=high_hz,calibratedLevel=False,mode='known_sweep_IR_experiment')


def recover_ir(recording,reference,maximum_ir_seconds=.8,sample_rate=48000,regularization=1e-6):
    y=np.asarray(recording,float);x=np.asarray(reference,float)
    if y.ndim!=1 or x.ndim!=1 or not np.isfinite(y).all() or not np.isfinite(x).all():
        raise ValueError('finite mono aligned reference/recording required')
    if sample_rate!=48000 or not .05<=maximum_ir_seconds<=3 or not 0<regularization<=.01:
        raise ValueError('bounded IR duration and regularization required')
    needed=round(maximum_ir_seconds*sample_rate)
    if not len(x) or len(y)<len(x)+needed-1 or np.dot(x,x)==0:
        raise ValueError('record full excitation plus requested IR tail; nonzero reference required')
    nfft=fft.next_fast_len(len(y)+len(x)-1)
    X=fft.rfft(x,nfft);Y=fft.rfft(y,nfft);power=abs(X)**2
    H=Y*X.conj()/(power+regularization*power.max())
    h=fft.irfft(H,nfft)[:needed]
    return dict(impulseResponse=h,sampleRate=sample_rate,fftLength=nfft,
        regularizationRelative=regularization,inputTimebaseAlignedRequired=True,
        sourceAndMicrophoneResponseIncluded=True,referenceRecordingMeasured=True,
        scope='linear transfer estimate within excited frequencyband; not certified RIR',
        actualRoomMeasured=False)
