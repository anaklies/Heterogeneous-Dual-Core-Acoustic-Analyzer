"""Bounded offline input/result/reference pairs. Does not contact hardware."""
from pathlib import Path
import argparse,ast,json,hashlib,sys,time,shutil,csv,ctypes,os
import numpy as np
from scipy import signal
from scipy.io import wavfile

def locate():
 p=Path(__file__).resolve()
 for parent in p.parents:
  if (parent/'build/PACKAGE_INFO.json').exists():return parent/'src/project',parent/'data/software_measurements'
 return p.parents[2],p.parents[2].parent/'ECHO_Final/data/software_measurements'
rr,oo=locate();ap=argparse.ArgumentParser();ap.add_argument('--source-root',type=Path,default=rr);ap.add_argument('--output',type=Path,default=oo);ap.add_argument('--reuse-native',action='store_true');args=ap.parse_args()
ROOT=args.source_root;OUT=args.output;OUT.mkdir(parents=True,exist_ok=True)
SERV=ROOT/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/services'
DLL=ROOT/'deployment/echo_measurement_flow_fix_20261028/room_native.dll'
sys.path.insert(0,str(SERV));sys.path.insert(0,str(ROOT/'deployment/echo_room_and_metrics_fix_20261029'))
def clean(v):
 if isinstance(v,np.ndarray):return v.tolist()
 if isinstance(v,np.generic):return v.item()
 if isinstance(v,complex):return {'real':v.real,'imag':v.imag}
 if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
 if isinstance(v,(list,tuple)):return [clean(x) for x in v]
 if isinstance(v,Path):return str(v)
 return v
def dump(p,v):
 p=OUT/p;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(clean(v),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def table(p,header,rows):
 p=OUT/p;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(header);w.writerows(rows)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def wav(name,x,fs=48000):
 p=OUT/'inputs'/name;p.parent.mkdir(exist_ok=True,parents=True)
 wavfile.write(p,fs,np.rint(np.clip(x,-.999,.999)*2147483392).astype(np.int32));return 'inputs/'+name

print('GENERATE_DETERMINISTIC_INPUTS',flush=True)
fs=48000;N=2048;rng=np.random.default_rng(20261101);t=np.arange(24000)/fs
tone=.2*np.sin(2*np.pi*1000*t)
dual=.15*np.sin(2*np.pi*1000*t)+.15*np.sin(2*np.pi*1500*t)
six=np.column_stack([np.roll(tone,k*2)*(1-.02*k) for k in range(6)])
inp={
 'tone':wav('01_1000Hz_six_channel.wav',six),
 'dual':wav('02_equal_amplitude_1000_1500Hz.wav',dual),
 'noise':wav('03_seeded_white_noise.wav',rng.normal(0,.02,len(t))),
 'am':wav('04_100Hz_AM_6000Hz_carrier.wav',.15*(1+.5*np.sin(2*np.pi*100*t))*np.cos(2*np.pi*6000*t)),
 'harmonic':wav('05_250Hz_with_harmonics.wav',.2*np.sin(2*np.pi*250*t)+.02*np.sin(2*np.pi*500*t)+.01*np.sin(2*np.pi*750*t))}
td=np.arange(144000)/fs
inp['drift']=wav('09_linear_1000_to_1030Hz_drift.wav',.2*np.sin(2*np.pi*(1000*td+5*td*td)))
noise_pair=rng.normal(0,.02,(24000,2));noise_pair[:,1]=np.roll(noise_pair[:,0],7)
inp['delay']=wav('10_broadband_pair_delay_7_samples.wav',noise_pair)
rt=.4;tr=np.arange(48000)/fs;ir=np.exp(-np.log(1000)*tr/rt);inp['room']=wav('06_ideal_RT60_0p4s.wav',ir*.7)
event=rng.normal(0,.002,96000);event[52800:57600]+=.15*np.sin(2*np.pi*3000*np.arange(4800)/fs)
inp['event']=wav('07_background_then_3kHz_event.wav',event)
ts=np.arange(384000)/fs;stim=np.zeros_like(ts)
for f,pair in [(500,(.63,3.15)),(1000,(2,10)),(2000,(1.25,6.25))]:
 env=np.ones_like(ts)
 for fm in pair:env*=1+.5*np.sin(2*np.pi*fm*ts)
 stim+=.1*np.sin(2*np.pi*f*ts)*env
inp['stipa']=wav('08_quick_STIPA_same_A_B_8s_each.wav',np.r_[stim,stim])
np.savez_compressed(OUT/'inputs/exact_float64_inputs.npz',six_channel=six,dual=dual,room_ir=ir,event=event,stipa_A=stim,stipa_B=stim,fs=np.array(fs),seed=np.array(20261101))

# Explicit golden results: known synthetic observations, separate from DUT outputs.
freq=np.fft.rfftfreq(N,1/fs);win=signal.windows.hann(N,sym=False)
X=np.fft.rfft(tone[:N]*win);P=abs(X)**2/(win.sum()**2);P[1:-1]*=2
psd=P/(fs*np.sum(win**2)/win.sum()**2)
Xd=np.fft.rfft(dual[:N]*win);Pd=abs(Xd)**2/win.sum()**2;Pd[1:-1]*=2
fw,pw=signal.welch(tone,fs,nperseg=N,noverlap=N//2,window='hann',detrend=False)
fst,tst,Z=signal.stft(tone,fs,nperseg=N,noverlap=N//2,window='hann',boundary=None,padded=False)
amplitude=np.sqrt(2*P);amplitude[[0,-1]]=np.sqrt(P[[0,-1]])
table('reference/fft_1000Hz.csv',['frequency_Hz','amplitude_FS','power_FS2','PSD_FS2_per_Hz'],zip(freq,amplitude,P,psd))
table('reference/welch_1000Hz.csv',['frequency_Hz','PSD_FS2_per_Hz'],zip(fw,pw))
np.savez_compressed(OUT/'reference/stft_reference.npz',frequency_hz=fst,time_s=tst,complex_stft=Z)
def bands(fraction):
 centers=1000*2**(np.arange(-18,15)/fraction);centers=centers[(centers>=20)&(centers<=20000)]
 values=[float(P[(freq>=c/2**(.5/fraction))&(freq<c*2**(.5/fraction))].sum()) for c in centers]
 return centers,np.array(values)
c1,b1=bands(1);c3,b3=bands(3)
table('reference/octave.csv',['center_Hz','power_FS2'],zip(c1,b1));table('reference/third_octave.csv',['center_Hz','power_FS2'],zip(c3,b3))
sys.path.insert(0,str(ROOT/'deployment/work_platform_20261013/phase14_room_and_pl_20261021/algorithms'))
from noise_metrics import analog_weighting_db,nr_curves,nc_curves,noise_curve_rating
weights={k:float(10*np.log10(np.sum(psd*10**(analog_weighting_db(freq,k)/10))*fs/N)) for k in ['A','C','Z']}
edc=10*np.log10(np.maximum(np.cumsum(ir[::-1]**2)[::-1]/np.sum(ir**2),1e-30))
fits={}
for name,hi,lo in [('EDT',0,-10),('T20',-5,-25),('T30',-5,-35)]:
 mask=(edc<=hi)&(edc>=lo);slope,offset=np.polyfit(tr[mask],edc[mask],1);fits[name]=-60/slope
energy=ir**2;total=energy.sum();e50=energy[:2400].sum();e80=energy[:3840].sum()
clarity={'C50_dB':10*np.log10(e50/(total-e50)),'C80_dB':10*np.log10(e80/(total-e80)),'D50_percent':100*e50/total}
table('reference/room_decay.csv',['time_s','energy_decay_dB'],zip(tr[::48],edc[::48]))
# Per-band curves must be calculated after filtering, never copied from broadband.
ir_noise=np.random.default_rng(20261102).normal(size=len(tr))*np.exp(-np.log(1000)*tr/rt)
ir_noise*=.7/max(abs(ir_noise));inp['bandroom']=wav('11_broadband_room_decay_RT0p4s.wav',ir_noise)
bandrows=[];bandcurves=[]
for center in [125,250,500,1000,2000,4000,8000]:
 filtered=signal.sosfilt(signal.butter(4,[center/np.sqrt(2),center*np.sqrt(2)],btype='bandpass',fs=fs,output='sos'),ir_noise)
 power=filtered**2;db=10*np.log10(np.maximum(np.cumsum(power[::-1])[::-1]/power.sum(),1e-30));bf=[]
 for hi,lo in [(0,-10),(-5,-25),(-5,-35)]:
  mask=(db<=hi)&(db>=lo);slope,offset=np.polyfit(tr[mask],db[mask],1);bf.append(-60/slope)
 bandrows.append([center,*bf]);bandcurves.extend((center,float(ts),float(ds)) for ts,ds in zip(tr[::48],db[::48]))
table('reference/band_decay_summary.csv',['center_Hz','EDT_s','T20_s','T30_s'],bandrows)
table('reference/band_decay_curves.csv',['center_Hz','time_s','energy_decay_dB'],bandcurves)
fcs,Pxy=signal.csd(six[:,0],six[:,1],fs,nperseg=N,noverlap=N//2,detrend=False)
_,coh=signal.coherence(six[:,0],six[:,1],fs,nperseg=N,noverlap=N//2)
table('reference/csd_coherence.csv',['frequency_Hz','csd_real','csd_imag','coherence','phase_rad'],zip(fcs,Pxy.real,Pxy.imag,coh,np.angle(Pxy)))
table('reference/dual_tone_spectrum.csv',['frequency_Hz','power_FS2'],zip(freq,Pd))
levelhist=np.linspace(-50,-20,16);refA=P.copy();refB=P*4
skframes=rng.exponential(.01,(8,64));ss=skframes.sum(0);sk=(9/7)*(8*np.sum(skframes**2,axis=0)/ss**2-1)-1
table('reference/spectral_kurtosis.csv',['bin','excess_spectral_kurtosis'],enumerate(sk))
tables={}
for family,curves in [('NR',nr_curves()),('NC',nc_curves())]:
 levels=curves['levelsDBSPL'][len(curves['ratings'])//2]-.25
 rr=noise_curve_rating(levels.astype(np.float32)-105,family=family,calibration={'mode':'nominal','offsetDB':105,'source':'synthetic test reference'})
 tables[family]={'rating':rr['rating'],'input_levels':levels.tolist(),'center_Hz':curves['centerHz'].tolist() if hasattr(curves['centerHz'],'tolist') else curves['centerHz'],'offset_dB':105}
dump('reference/NC_NR_explicit_nominal_reference.json',tables)
refs={
 'io_pcm':('tone',{'sampleRateHz':fs,'channels':6,'samplesPerChannel':len(t),'storage':'signed PCM32 WAV; exact normalized samples in NPZ'}),
 'levels_core':('tone',{'channel0_RMS_FS':np.sqrt(np.mean(tone**2)),'peak_FS':.2,'RMS_dBFS':20*np.log10(np.sqrt(np.mean(tone**2))),'crestFactor':np.sqrt(2),'clippedSamples':0}),
 'data_continuity':('tone',{'frames':[100,101,103],'detectedMissingFrames':1,'syntheticTransportFixture':True}),
 'fft':('tone',{'targetHz':1000,'resolutionHz':fs/N,'referenceCSV':'reference/fft_1000Hz.csv'}),
 'psd':('tone',{'integratedPower_FS2':np.trapezoid(pw,fw),'referenceCSV':'reference/welch_1000Hz.csv'}),
 'stft':('tone',{'frequencyGridStepHz':fs/N,'hopSamples':1024,'frames':len(tst),'referenceNPZ':'reference/stft_reference.npz'}),
 'spectrum_average':('tone',{'meanOfSpectrumAAnd4A':(2.5*P).tolist()}),
 'signal_quality':('tone',{'finite':True,'clipped':False,'allSixChannelsNonzero':True,'staleFixtureAgeMs':2500,'maxAgeMs':1000,'staleMustBeRejected':True}),
 'levels_extended':('tone',{'peakToPeak_FS':.4,'dc_FS':float(tone.mean()),'RMS_per_channel':np.sqrt(np.mean(six**2,axis=0)).tolist()}),
 'octave':('tone',{'referenceCSV':'reference/octave.csv'}),'third_octave':('tone',{'referenceCSV':'reference/third_octave.csv'}),
 'peak_hold':('tone',{'peakOfAAnd4A':(4*P).tolist()}),
 'smoothing':('tone',{'kernel':[.25,.5,.25],'power':np.r_[P[0],(P[:-2]+2*P[1:-1]+P[2:])*.25,P[-1]].tolist()}),
 'frequency_tracking':('tone',{'trueFrequencyHz':1000,'nearestFFTBinHz':float(freq[P.argmax()])}),
 'frequency_drift':('drift',{'instantaneousFrequencyHz':'1000+10*t','durationSeconds':3,'slopeHzPerSecond':10,'framewiseFFTTrackingIncludesBinQuantization':True}),
 'csd':('tone',{'convention':'conj(X)*Y','referenceCSV':'reference/csd_coherence.csv'}),
 'coherence_phase':('tone',{'delaySamples':2,'phaseAt1000Hz_rad':-2*np.pi*1000*2/fs,'coherenceNearTone':1,'referenceCSV':'reference/csd_coherence.csv'}),
 'energy_change':('event',{'backgroundSigma_FS':.002,'burstStartSeconds':1.1,'burstEndSeconds':1.2,'burstFrequencyHz':3000}),
 'band_tracking':('event',{'selectedBandHz':[2500,3500],'burstStartSeconds':1.1}),
 'centroid':('dual',{'trueEqualPowerCentroidHz':1250,'HannComputedCentroidHz':np.dot(freq,Pd)/Pd.sum(),'referenceCSV':'reference/dual_tone_spectrum.csv'}),
 'flatness':('tone',{'powerSpectralFlatness':float(np.exp(np.mean(np.log(np.maximum(P[1:],1e-20))))/np.mean(P[1:]))}),
 'event_trigger':('event',{'learningIntervalSeconds':[0,1],'expectedPhysicalChangeSeconds':[1.1,1.2],'clipBeforeSeconds':.2,'clipAfterSeconds':.3,'workflowFixtureOnly':True}),
 'frequency_time_weighting':('tone',{'spectralWeighting_dBFS':weights,'FAST_tau_s':.125,'SLOW_tau_s':1,'singleFrameTimeResponse':'state must continue across unique frames'}),
 'level_statistics':('tone',{'inputLevels_dBFS':levelhist,'L10_dBFS':np.percentile(levelhist,90),'L50_dBFS':np.percentile(levelhist,50),'L90_dBFS':np.percentile(levelhist,10),'Leq_dBFS':10*np.log10(np.mean(10**(levelhist/10)))}),
 'zoom_fft':('dual',{'bandHz':[800,1700],'expectedPeaksHz':[1000,1500],'nativeZoomEvidence':'native/test_extra_spectral'}),
 'fundamental':('harmonic',{'fundamentalHz':250}),
 'harmonic_ratio':('harmonic',{'fundamentalAmplitude':.2,'harmonicAmplitudes':[.02,.01],'THD_ratio':np.sqrt(.02**2+.01**2)/.2}),
 'sidebands':('am',{'carrierHz':6000,'sidebandHz':[5900,6100],'eachSidebandToCarrierPowerRatio':.0625}),
 'envelope_hilbert':('am',{'envelopeFormula':'0.15*(1+0.5*sin(2*pi*100*t))','min':.075,'max':.225}),
 'envelope_spectrum':('am',{'modulationPeakHz':100,'rawPeakTrackingIncludesDC':True}),
 'modulation_spectrum':('am',{'modulationPeakHz':100}),
 'autocorrelation':('tone',{'periodSamples':48,'periodSeconds':.001,'finiteWindowEnvelopeAffectsLagAmplitude':True}),
 'cross_correlation':('tone',{'channelPair':[0,1],'channel1DelaySamples':2,'signDependsOnConjugateConvention':'native convention X*conj(Y): peak lag -2'}),
 'gcc_phat':('delay',{'channel1DelaySamples':7,'nativeConvention_X_conjY_peakLagSamples':-7,'delayMagnitudeSeconds':7/fs,'reference':'native/test_p2_chains','pureToneDelayAmbiguous':True}),
 'spectral_flux':('tone',{'equalConsecutiveSpectraPositiveFlux':0,'A_to_4A_positiveFlux':float(3*P.sum())}),
 'spectrum_freeze':('tone',{'referencePower':refA.tolist(),'comparisonPower':refB.tolist(),'powerRatio_dB':6.020599913279624}),
 'relative_limit':('tone',{'referencePower':refA.tolist(),'comparisonPower':refB.tolist(),'threshold_dB':3,'expectedActiveBinDifference_dB':6.020599913279624,'activeBinsExceed':True}),
 'cepstrum':('harmonic',{'expectedPeriodSeconds':.004,'sampleRateHz':fs,'referenceDefinition':'real(ifft(log(max(abs(FFT(x)),1e-10))))'}),
 'spectral_kurtosis':('noise',{'snapshots':8,'referenceCSV':'reference/spectral_kurtosis.csv','formula':'(M+1)/(M-1)*(M*S2/S1^2-1)-1'}),
 'room_decay':('room',{'RT60_true_s':rt,**fits,'referenceCSV':'reference/room_decay.csv'}),
 'relative_insulation':('tone',{'referenceA_power':.02,'measurementB_power':.005,'relativeDifference_dB':10*np.log10(4)}),
 'stipa_experimental':('stipa',{'samePCM_A_B':True,'quickStages':15,'secondsPerCapture':8,'expectedIndex':1,'expectedValid':1,'referenceDepthGate':.15,'reuseEvidence':'inherited/STIPA_SAME_PCM_CHECK.json'}),
 'noise_rating':('noise',{'referenceJSON':'reference/NC_NR_explicit_nominal_reference.json','NC_expected':tables['NC']['rating'],'NR_expected':tables['NR']['rating']}),
 'room_clarity':('room',clarity),
 'spectral_decay':('bandroom',{'envelopeRT60_s':rt,'filter':'4th order Butterworth octave band, causal SOS','perBandReferenceCSV':'reference/band_decay_summary.csv','perBandCurvesCSV':'reference/band_decay_curves.csv','filteredBandRTNeedsItsOwnFit':True})}
catalog_path=ROOT/'deployment/echo_spatial_off_20261031/registry/INTERFACE_REGISTRY.json'
if not catalog_path.exists():catalog_path=ROOT/'deployment/echo_interface_guard_20261026/registry/INTERFACE_REGISTRY.json'
catalog=json.loads(catalog_path.read_text(encoding='utf-8-sig'))['features']
assert len(catalog)==45 and set(refs)=={x['featureId'] for x in catalog}
for f in catalog:
 key,ref=refs[f['featureId']];dump(Path('reference')/(f['featureId']+'.json'),{'featureId':f['featureId'],'name':f['name'],'input':inp[key],'reference':ref,'provenance':'deterministic synthetic input + offline formula/SciPy golden; not a board measurement'})

# Capture native production scalar tests without recompiling, and redirect all
# test result writes into this new directory. Originals remain unchanged.
native=[];counter=0;current=''
def save_case(local,g):
 global counter
 counter+=1;name=str(local.get('name',local.get('label',local.get('service',f'case_{counter}'))))
 if name=='None':name=f'case_{counter}'
 arrays={};meta={}
 for k,v in local.items():
  if k=='g' and isinstance(v,dict):
   for key,value in v.items():
    if isinstance(value,np.ndarray):arrays['reference_'+key]=value
  if k in {'actual','expected','a','b','gold','x','out','frames','d','db','trace'}:
   try:
    a=np.asarray(v)
    if a.dtype.kind in 'biufc' and a.size:arrays[k]=a
   except (ValueError,TypeError):pass
  elif isinstance(v,(str,int,float,bool)):meta[k]=v
 memory=g.get('memory',g.get('mem'))
 if isinstance(memory,np.ndarray):arrays['VM_memory_after']=memory.copy()
 path=Path('native')/current/(f'{counter:03d}.npz');(OUT/path).parent.mkdir(parents=True,exist_ok=True)
 np.savez_compressed(OUT/path,**arrays)
 aa=arrays.get('actual',arrays.get('a',arrays.get('out')));bb=arrays.get('expected',arrays.get('gold',arrays.get('b')))
 error=None
 if aa is not None and bb is not None and aa.shape==bb.shape:error=float(np.max(abs(aa-bb)))
 native.append({'suite':current,'case':name,'data':path.as_posix(),'arrays':list(arrays),'maxAbsoluteError':error,'checks':'original test assertions passed before capture','meta':meta})
 if aa is not None and bb is not None and aa.shape==bb.shape and aa.size<=20000:
  table(path.with_suffix('.csv'),['index','native_actual','reference','absolute_error'],((i,str(a),str(b),abs(a-b)) for i,(a,b) in enumerate(zip(aa.ravel(),bb.ravel()))))
def result_write(path,text,**kwargs):
 p=OUT/'native'/current/Path(path).name;p.parent.mkdir(parents=True,exist_ok=True);return p.write_text(text,encoding='utf-8')
class Capture(ast.NodeTransformer):
 def visit_Assign(self,n):
  if any(isinstance(t,ast.Name) and t.id=='DLL' for t in n.targets):
   return ast.copy_location(ast.Assign(targets=n.targets,value=ast.Name(id='_DLL',ctx=ast.Load())),n)
  return self.generic_visit(n)
 def visit_Expr(self,n):
  if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and isinstance(n.value.func.value,ast.Name) and n.value.func.value.id=='subprocess' and n.value.func.attr=='run':return None
  return self.generic_visit(n)
 def visit_Call(self,n):
  n=self.generic_visit(n)
  if isinstance(n.func,ast.Attribute) and n.func.attr=='CDLL':n.args=[ast.Call(func=ast.Name(id='str',ctx=ast.Load()),args=[ast.Name(id='_DLL',ctx=ast.Load())],keywords=[])];n.keywords=[]
  if isinstance(n.func,ast.Attribute) and n.func.attr=='write_text':
   return ast.copy_location(ast.Call(func=ast.Name(id='_write_result',ctx=ast.Load()),args=[n.func.value,*n.args],keywords=n.keywords),n)
  return n
 def visit_FunctionDef(self,n):
  n=self.generic_visit(n)
  if n.name in {'check','compare','case'} or (current=='test_room_services' and n.name=='run'):
   call=ast.parse('_capture(locals(), globals())').body[0]
   # All these small check functions have only a top-level return.
   for i,s in enumerate(n.body):
    if isinstance(s,ast.Return):n.body.insert(i,call);break
   else:n.body.append(call)
  return n
statuses=[]
for current in ([] if args.reuse_native else ['test_programs','test_cross_spectral_services','test_noise_services','test_p2_chains','test_extra_spectral','test_room_services']):
 print('NATIVE_SOFTWARE',current,flush=True);path=SERV/(current+'.py');start=time.perf_counter()
 code=Capture().visit(ast.parse(path.read_text(encoding='utf-8')));ast.fix_missing_locations(code)
 ns={'__file__':str(path),'__name__':'_bounded_reference_capture','_DLL':DLL,'_capture':save_case,'_write_result':result_write}
 try:exec(compile(code,str(path),'exec'),ns);statuses.append({'suite':current,'status':'PASS','seconds':time.perf_counter()-start})
 except Exception as e:statuses.append({'suite':current,'status':'FAIL','error':repr(e)});dump('native/SUITE_STATUS.json',statuses);raise
if args.reuse_native:
 native=json.loads((OUT/'native/CASES.json').read_text(encoding='utf-8'));statuses=json.loads((OUT/'native/SUITE_STATUS.json').read_text(encoding='utf-8'))
else:dump('native/CASES.json',native);dump('native/SUITE_STATUS.json',statuses)
# Export the independent room reference arrays even for inherited native captures.
for case in native:
 if case['suite']!='test_room_services':continue
 path=OUT/case['data'];data=dict(np.load(path));x=data['x'].astype(np.float64);rate=case['meta']['fs'];energy=x*x;total=energy.sum()
 expected=[];indices=[]
 if total:
  db=10*np.log10(np.maximum(np.cumsum(energy[::-1])[::-1]/total,1e-30));tt=np.arange(len(x))/rate
  data['reference_decay_dB']=db
  e50=energy[:int(.05*rate)].sum();e80=energy[:int(.08*rate)].sum()
  indices.extend(range(4));expected.extend([total,e50,e80,100*e50/total])
  for off,hi,lo in [(10,0,-10),(16,-5,-25),(22,-5,-35)]:
   use=(db<=hi)&(db>=lo);ids=np.flatnonzero(use);valid=False
   if np.any(db<=lo) and len(ids)>=max(16,int(.001*rate)) and np.ptp(tt[ids])>=.005:
    slope,offset=np.polyfit(tt[use],db[use],1);r2=1-np.sum((db[use]-(slope*tt[use]+offset))**2)/np.sum((db[use]-db[use].mean())**2)
    valid=slope<0 and r2>=.9
    if valid:indices.extend([off,off+1]);expected.extend([-60/slope,r2])
   indices.append(off+2);expected.append(int(valid))
 else:
  indices=[12,18,24];expected=[0,0,0]
 data['reference_summary_indices']=np.asarray(indices,np.int32);data['reference_summary']=np.asarray(expected);data['actual_summary']=data['a'][indices]
 np.savez_compressed(path,**data)
 table(Path(case['data']).with_suffix('.csv'),['output_word_index','native_actual','reference','absolute_error'],[(i,float(a),float(b),abs(float(a)-float(b))) for i,a,b in zip(indices,data['actual_summary'],expected)])
 case['arrays']=list(data);case['referenceExported']=True
dump('native/CASES.json',native)
hist=ROOT/'deployment/echo_stipa_8s_progress_20261030/SAME_PCM_CHECK.json'
if hist.exists():
 p=OUT/'inherited/STIPA_SAME_PCM_CHECK.json';p.parent.mkdir(exist_ok=True);shutil.copy2(hist,p)
 dump('inherited/PROVENANCE.json',{'source':str(hist.relative_to(ROOT)),'sha256':sha(hist),'rerun':False,'reason':'15-stage result already verified; reused instead of a long duplicate test','syntheticInputRegeneratedWithSameFormula':True})
suite_map={
 'test_programs':['spectrum_average','peak_hold','smoothing','octave','third_octave','centroid','flatness','spectral_flux'],
 'test_cross_spectral_services':['csd','coherence_phase'],
 'test_noise_services':['frequency_time_weighting','level_statistics','relative_insulation','noise_rating'],
 'test_p2_chains':['cepstrum','autocorrelation','cross_correlation','gcc_phat','envelope_hilbert','envelope_spectrum'],
 'test_extra_spectral':['harmonic_ratio','sidebands','spectral_kurtosis','fundamental','zoom_fft'],
 'test_room_services':['room_decay','room_clarity']}
rows=[]
for f in catalog:
 fid=f['featureId'];key,_=refs[fid];suites=[k for k,v in suite_map.items() if fid in v]
 status='NATIVE_CORE_PAIR' if suites else 'REFERENCE_FIXTURE'
 if fid=='stipa_experimental':status='INHERITED_NATIVE_15_STAGE'
 if fid in {'event_trigger','data_continuity','signal_quality'}:status='CONTROL_FIXTURE_NOT_END_TO_END'
 rows.append([fid,f['name'],inp[key],'reference/'+fid+'.json',status,';'.join('native/'+s for s in suites)])
table('45项输入结果参考索引.csv',['featureId','功能名称','输入数据','参考结果','证据类型','软件实际输出与对照目录'],rows)
dump('SUMMARY.json',{'features':45,'inputWavs':len(inp),'nativeSuites':statuses,'nativeCapturedCases':len(native),'softwareOnly':True,'noBoardAccess':True,'seed':20261101,'python':sys.version,'numpy':np.__version__,'scipy':__import__('scipy').__version__,'nativeEngineSHA256':sha(DLL),'coverageRule':'45 reference fixtures are not 45 deployed full-stack acceptance passes; native core pairs and workflow-only fixtures are labelled separately'})
(OUT/'数据说明.md').write_text('''# 软件测试数据与参考结果

从“45项输入结果参考索引.csv”查看各功能输入、参考结果与证据类型。

- inputs：可播放的WAV和无损float64精确输入；WAV为有符号32bit PCM，采样率48000Hz。
- reference：离线数学/SciPy参考数值、频谱、时频与衰减曲线。
- native：实际项目标量执行内核的软件输出与独立参考逐值对照；NPZ包含测试内存、输出及参考数组，CSV可直接查看。
- inherited：复用已验证的8秒15阶段STIPA同PCM结果，避免重复长测试。

NATIVE_CORE_PAIR表示对应数学内核的软件对照；REFERENCE_FIXTURE表示输入与预期参考，不代表最终设备调用已验证。事件服务、连续性、数据新鲜度包含控制流程，合成数据只能给流程测试夹具，不能据此宣称整机闭环通过。所有数据均不属于本轮上板实测。

各参考采用文件中明确记录的定义。Hann FFT幅度、功率和PSD的单位不同；纯音GCC存在周期歧义；NC/NR样例使用明确的名义参考；分频衰减需对滤波后信号拟合，不能把未滤波结果直接作为所有频带的答案。
''',encoding='utf-8')
table('SHA256SUMS.csv',['path','bytes','sha256'],[(p.relative_to(OUT).as_posix(),p.stat().st_size,sha(p)) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='SHA256SUMS.csv'])
print('DONE',len(rows),'features',len(native),'native captures',flush=True)
