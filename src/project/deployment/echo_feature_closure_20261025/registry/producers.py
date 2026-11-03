"""Small missing scalar PL assemblers. Host emits instructions, never audio DSP."""
import math
from programs import Code

def _tail(c,fields):
 # Current power f0, previous f1, initialized f2, zero f3, one f4.
 c.u(3,0);c.f(3,0);c.f(4,1);c.history(1,3,4);c.history(2,3,5)
 c.store(0,3,0);c.store(1,3,1);c.emit(5,5,0,1);c.store(5,3,2);c.store(2,3,3)
 c.store(0,3,4);c.store(4,3,5);c.emit(0)
 return c,6,dict(service=fields['service'],fields=['power_FS2','previous_power_FS2','delta_FS2','delta_valid','history_power_FS2','initialized'],
  units='FS squared; validity dimensionless',validity='first frame delta_valid=0; subsequent distinct frames only; reset on source/channel/config change',**{k:v for k,v in fields.items() if k!='service'})

def energy_change(channel=0):
 if not isinstance(channel,int) or not 0<=channel<6:raise ValueError('channel integer0..5')
 c=Code();c.u(1,channel*8192+7171);c.load(0);c.emit(6,0,0,0)
 return _tail(c,dict(service='short_time_mean_square_change',source='stream_fft raw2048 RMS squared; unwindowed'))

def band_tracking(sample_rate=48009.775390625,channel=0,low=100.0,high=1000.0):
 if not isinstance(channel,int)or not 0<=channel<6 or not all(math.isfinite(x) for x in (sample_rate,low,high)) or not 0<=low<high<=sample_rate/2:raise ValueError('channel0..5; finite 0<=low<high<=Nyquist')
 first=math.ceil(low*2048/sample_rate);end=min(1025,math.ceil(high*2048/sample_rate))
 if first>=end:raise ValueError('selected band contains no FFT bins')
 c=Code();c.u(0,first);c.u(1,channel*8192+4097+3*first);c.f(0,0);c.f(2,sample_rate/2048)
 loop=len(c.words);c.load(1);c.emit(6,1,1,2);c.emit(4,0,0,1)
 c.addi(0,0,1);c.addi(1,1,3);c.loop(0,end,loop)
 return _tail(c,dict(service='selected_band_energy_change',low_hz=low,high_hz=high,first_bin=first,bins=end-first,band_interval='inclusive lower/exclusive upper; FFT PSD integration'))

def impulse_capture_prepare(samples,threshold_fraction=0.1,stimulus_confirmed=False):
 """Experimental impulsive room capture trim; conversion/onset/copy all PL.

 Consume2*n PCM24 words at output+32. Find peak and first threshold crossing
 in firstn, then forward-copy exactlyn float32 samples from that crossing.
 This is an approximate impulsive response, not extracted/deconvolved RIR.
 """
 from raw_conversion import convert_pcm24
 if not isinstance(samples,int)or not 32<=samples<=60000:raise ValueError('samples32..60000')
 if not math.isfinite(threshold_fraction)or not 0<threshold_fraction<=1:raise ValueError('0<threshold_fraction<=1')
 c,_,_=convert_pcm24(2*samples,32);c.words.pop();c.u(3,0);c.f(0,0)
 for off in range(28,32):c.store(0,3,off)
 if stimulus_confirmed:
  c.u(0,0);c.f(1,0);begin=len(c.words)
  c.history(0,0,32);c.emit(13,0,0);c.emit(12,1,1,0)
  c.addi(0,0,1);c.loop(0,samples,begin);c.store(1,3,29)
  c.f(2,1e-20);present=c.emit(19,a=2,b=1,target=0);c.emit(0)
  c.words[present][2]=len(c.words);c.f(4,threshold_fraction);c.emit(6,4,4,1);c.store(4,3,31)
  c.u(0,0);begin=len(c.words);c.history(0,0,32);c.emit(13,0,0)
  below=c.emit(19,a=0,b=4,target=0);c.addi(5,0,0);found=c.emit(17,imm=0)
  c.words[below][2]=len(c.words);c.addi(0,0,1);c.loop(0,samples,begin);c.emit(0)
  c.words[found][1]=len(c.words);c.emit(21,5,3,imm=28,target=1)
  c.u(0,0);c.addi(1,5,32);begin=len(c.words)
  c.history(0,1);c.store(0,0,32);c.addi(0,0,1);c.addi(1,1,1);c.loop(0,samples,begin)
  c.f(0,1);c.store(0,3,30)
 c.emit(0)
 return c,dict(service='experimental_impulsive_room_capture_prepare',samples=samples,capture_samples=2*samples,workspace_words=32+2*samples,
  input_offset=32,input_format='2*n sign-extended PCM24 LE32 captured mono samples',output_format='n onset-trimmed float32 FS samples at output+32',threshold_fraction=threshold_fraction,
  stimulus_confirmed=stimulus_confirmed,summary={'onset_index_uint32':28,'peak_FS':29,'valid':30,'threshold_FS':31},
  validity='declared clap/impulse stimulus AND firstn peak>1e-20 AND first >=threshold crossing copied; read summary before main clears it',
  limitations=['approximate impulsive room response only','no deconvolution or calibrated/certified RIR','arbitrary speech rejected by caller stimulus gate','threshold crossing is an approximate onset, not automatic impulse identification','noise/capture clipping can bias peak/onset; main decay validity still applies'])

def noise_rating(sample_rate=48009.775390625,family='NR',channel=0):
 """Pinned PSD -> exact curve-center octave levels -> nominal NR/NC in PL.

 Runtime output[30] must equal1 AND caller must validate reference declaration.
 output[31] is a finite user-supplied nominal SPL offset in dB. Zero initialized
 memory cannot establish a reference. Configuration constants alone run on host.
 """
 from noise_services import noise_curve
 if not math.isfinite(sample_rate)or sample_rate<=0 or not isinstance(channel,int)or not 0<=channel<6:raise ValueError('positive finite sample rate; channel0..5')
 tail,n,meta=noise_curve(family,calibration={'mode':'nominal','source':'explicit runtime nominal reference; caller gate required','offsetDB':0.0},input_unit='dBFS')
 c=Code();c.u(3,0);c.f(0,0);c.f(1,1)
 for off in range(3):c.store(0,3,off)
 c.history(3,3,30);reject=[c.emit(19,a=3,b=1,target=0),c.emit(19,a=1,b=3,target=0)]
 c.f(4,sample_rate/2048);c.f(5,1e-20);c.f(6,10/math.log(10));ranges=[]
 for band,center in enumerate(meta['centers_hz']):
  first=max(0,math.ceil(center/math.sqrt(2)*2048/sample_rate));end=min(1025,math.floor(center*math.sqrt(2)*2048/sample_rate)+1)
  if first>=end:raise ValueError('standard octave band unresolved by FFT grid')
  ranges.append([first,end]);c.f(0,0);c.u(0,first);c.u(1,channel*8192+4097+3*first)
  loop=len(c.words);c.load(2);c.emit(6,2,2,4);c.emit(4,0,0,2)
  c.addi(0,0,1);c.addi(1,1,3);c.loop(0,end,loop)
  c.emit(12,0,0,5);c.emit(9,0,0);c.emit(6,0,0,6);c.store(0,3,32+band)
 # Replace the curve's literal nominal offset by an actual private runtime
 # reference load. This leaves all frozen curve constants and comparisons intact.
 replacements=0
 for raw in tail.words:
  if raw[0]&255==1 and (raw[0]>>8)&31==2:
   raw[:]=[2|2<<8|3<<13,31,2,0];replacements+=1
 assert replacements==1
 shift=len(c.words)
 for raw in tail.words:
  v=raw.copy();op=v[0]&255
  if op in (16,19):v[2]+=shift
  elif op==17:v[1]+=shift
  c.words.append(v)
 end=len(c.words);c.emit(0)
 for jump in reject:c.words[jump][2]=end
 assert len(c.words)<=1024
 return c,n,dict(meta,service='pinned_PSD_octaves_nominal_'+family,channel=channel,sample_rate=sample_rate,bin_ranges=ranges,
  fields=['rating','valid','estimated'],units='nominal curve rating; valid Boolean; estimated1 for valid nominal reference',
  runtimeInput={'referenceConfirmed':{'wordOffsetRelativeToOutput':30,'encoding':'float32','requiredValue':1,'default':0},
                'referenceOffsetDb':{'wordOffsetRelativeToOutput':31,'encoding':'float32','required':'finite explicit supplied nominal offset; do not infer default0'},
                'calibrationSource':{'location':'PS metadata only','required':'nonempty caller explanation of nominal reference'}},
  validity='PS must require referenceConfirmed=true, finite referenceOffsetDb and nonempty calibrationSource; PL gates output30==1; source snapshot must be fresh/valid',
  calibratedSPL=False,nominalEstimate=True,instrumentCertified=False,
  producer_required='fresh actual pinned Hann FFT PSD; standard-center rectangular FFT band integration in PL',
  limitations=['nominal estimate only; no physical calibrator implied','not certified SPL/NC/NR instrument','finite2048-bin rectangular octave integration, not IEC filterbank','silence log floor -200dBFS','invalid if explicit reference declaration absent'])

def managed_local_das(azimuth_deg=0.0,elevation_deg=0.0,sample_rate=48009.775390625,sound_speed=343.42,first=1,count=128):
 """Existing PL trig/beam program with two serialized private angle inputs."""
 from manual_das import manual_das
 c,n,meta=manual_das(azimuth_deg,elevation_deg,sample_rate,sound_speed,first,count,_angle_register=3)
 return c,n,dict(meta,service='managed_local_runtime_angle_DAS',
  runtimeInput={'azimuth_deg':{'wordOffsetRelativeToOutput':0,'encoding':'float32','range':[-360,360],'required':'finite degrees before every invocation'},
                'elevation_deg':{'wordOffsetRelativeToOutput':1,'encoding':'float32','range':[-90,90],'required':'finite degrees before every invocation'}},
  validity='PS validates finite local array-frame angles and fresh immutable pinned FFT; PL loads both angles before overwriting output with beam triplets',
  frame='local array frame only: +X azimuth0,+Y azimuth90,+Z elevation90; no global orientation transform',
  angleInputLifetime='input words0/1 overwritten by result; serialize requested angles before every new invocation',
  noCpuTrig=True,default_bins=128,default_first_bin=1)
