"""Same-PCM full 15-stage STIPA quick-chain verification on the real PL engine.

The synthetic record uses 500/1000/2000 Hz carriers, each amplitude-modulated by
the two frozen modulation frequencies of its band. The SAME segment is written
as reference A (first) and test B (second) in the quick input layout
(out .. out+2*N, sign-extended PCM24 LE32), then all 15 stages of quick_program
are installed/executed one after another through room_native.dll's scalar_native.

If the implementation has no A/B offset error, filtering and joint-fit results
must be bitwise identical between trace 0 and trace 1, the six (band, mod)
transfer ratios must be 1 and the published index must be ~1 with valid=1,
reason_code=0, certified_zero=0.

A real field recording (device live capture) is also run through the identical
chain with the same segment as A and B. Its bitwise A/B equality is the proof of
no implementation offset; its actual reference depth / ratio / reason code are
reported as-is (a low reference depth must surface as reason_code=3, not a fake
index).

Writes SAME_PCM_CHECK.json.  Runs under: system python + numpy/scipy PYTHONPATH.
"""
import ctypes,glob,hashlib,json,os,sys,time
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parent
sys.path.insert(0,str(R))
import quick_program as q

FS=q.old.FS;N=q.N;DEC=q.DEC;BASE=q.BASE;OUT=q.OUT;ARENA=q.ARENA
LAYOUT=q.old.layout(N);RES=LAYOUT['result']
DLL=q.ROOT/'deployment/echo_measurement_flow_fix_20261028/room_native.dll'
BANDS_HZ={band:q.old.CENTERS[band] for band in q.BANDS}
MODS={band:q.old.PAIRS[band] for band in q.BANDS}

def checks_note(rows,name,passed,detail=None):
 rows.append({'check':name,'pass':bool(passed),**({'detail':detail} if detail is not None else {})})
 return bool(passed)

class PL:
 """Thin bounded runner around the native scalar engine (same calling contract
 as the hardware slot budget: at most512 instructions per submission)."""
 def __init__(self,dll=DLL):
  self.fn=ctypes.CDLL(str(dll)).scalar_native
  self.fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
  self.calls=0;self.dll=dll
 def run(self,m,c,n=N):
  sp=q.old.install_stage(m,c,q.old.layout(n),base=BASE)
  m.view(np.uint32)[BASE+9]=512
  mine=0
  while True:
   status=ctypes.c_uint();self.fn(m.ctypes.data,sp['descriptor'],len(m),0,ctypes.byref(status));self.calls+=1;mine+=1
   if status.value&255:
    raise RuntimeError('PL scalar engine error status=%s stage_len=%d'%(hex(status.value),len(c.words)))
   if status.value&0x80000000:
    return mine
   if mine>500000:
    raise RuntimeError('PL stage did not reach DONE within the bounded unit budget')

def encode_pcm24(x):
 """float FS -> sign-extended PCM24 stored in LE32 words (exact inverse of the
 PL convert_raw_PCM24 recipe x = int32/8388608)."""
 x=np.asarray(x,dtype=np.float64)
 ints=np.rint(x*8388608.0)
 if np.any(np.abs(ints)>8388607):
  raise ValueError('PCM24 sample out of range')
 return ints.astype(np.int64).astype(np.int32).view(np.uint32)

def stage_program(d,weights_cache):
 if d['kind']=='convert_raw_PCM24':
  c,_,_=q.convert_pcm24(2*N,0);return c,None
 if d['kind']=='validate_captures':
  return q.validation(),None
 if d['kind']=='quick_filter':
  c,_=q.filt(d['band'],d['trace']);return c,None
 if d['kind']=='joint_fit':
  c=q.joint(d['band'],d['trace']);w=weights_cache[d['band']];return c,w
 return q.final(),None

def run_chain(pcm,pl):
 """Install+execute all 15 stages on one arena; returns (memory, per-stage calls)."""
 if len(pcm)!=2*N:raise ValueError('expected reference+test exactly 2*%d samples'%N)
 m=np.zeros(ARENA,np.float32)
 raw=encode_pcm24(pcm)
 m.view(np.uint32)[OUT:OUT+2*N]=raw
 weights_cache={band:q.weights(band).ravel().astype(np.float32) for band in q.BANDS}
 stages=q.graph();assert len(stages)==15, len(stages)
 calls=[]
 for d in stages:
  c,w=stage_program(d,weights_cache)
  if w is not None:
   assert len(w)==6*(N//DEC)
   m[OUT+3*N:OUT+3*N+len(w)]=w
  calls.append(pl.run(m,c))
 return m,calls

def bits(m,index):
 return int(m.view(np.uint32)[index])

def read_result(m):
 return {name:float(m[OUT+i]) for i,name in enumerate(q.RESULT_FIELDS)} | {'bits':[bits(m,OUT+i) for i in range(9)]}

def read_bands(m):
 """Read backward-compatible per-band powers and per-(band,trace) fit coefficients."""
 bands=[]
 for band in q.BANDS:
  powers=[]
  for tr in (0,1):
   v=float(m[OUT+RES+32+2*band+tr]);powers.append({'trace':tr,'power':v,'bits':bits(m,OUT+RES+32+2*band+tr)})
  coeffs=[]
  for tr in (0,1):
   a=[float(m[OUT+RES+48+tr*42+band*6+k]) for k in range(6)]
   ab=[bits(m,OUT+RES+48+tr*42+band*6+k) for k in range(6)]
   coeffs.append({'trace':tr,'coeff':a,'bits':ab})
  depths=[]
  for j in (0,1):
   c0=coeffs[0]['coeff'];c1=coeffs[1]['coeff']
   def depth(c):
    return float(np.hypot(c[2+2*j],c[3+2*j])/c[0])
   d0=depth(c0);d1=depth(c1)
   depths.append({'j':j,'modulationHz':float(q.contract_mod(MODS[band][j])),'rawModulationHz':float(MODS[band][j]),
                  'referenceDepth':d0,'measuredDepth':d1,'ratio':d1/d0 if d0 else None})
  bands.append({'bandIndex':band,'bandHz':float(BANDS_HZ[band]),
                'filterPower':powers,'coefficients':coeffs,'depths':depths})
 return bands

def evaluate(m,rows,prefix):
 """Assertions shared by the synthetic and real same-PCM chains."""
 bands=read_bands(m);final=read_result(m)
 bit_equal=[b['filterPower'][0]['bits']==b['filterPower'][1]['bits'] for b in bands]
 coeff_equal=[b['coefficients'][0]['bits']==b['coefficients'][1]['bits'] for b in bands]
 checks_note(rows,prefix+'/filter_power_bitwise_equal',all(bit_equal),{'perBand':bit_equal})
 checks_note(rows,prefix+'/filter_power_positive',all(p['power']>0 and np.isfinite(p['power']) for b in bands for p in b['filterPower']),
             {'powers':[[round(p['power'],12) for p in b['filterPower']] for b in bands]})
 checks_note(rows,prefix+'/joint_coefficients_bitwise_equal',all(coeff_equal),{'perBand':coeff_equal})
 coeff_values=[b['coefficients'][0]['coeff'] for b in bands]
 checks_note(rows,prefix+'/joint_coefficients_finite',all(np.isfinite(v) for c in coeff_values for v in c),{'coefficients':coeff_values})
 ratios=[d['ratio'] for b in bands for d in b['depths']]
 checks_note(rows,prefix+'/six_ratios_equal_1',all(r is not None and abs(r-1)<1e-6 for r in ratios),
             {'ratios':[None if r is None else round(r,12) for r in ratios]})
 return {'bands':bands,'final':final,'checks':[]}

def consistency_checks(rows,prefix,ev):
 """The 9 published words must agree with the frozen contract and with the
 coefficients actually present in the result region."""
 final=ev['final'];bands=ev['bands']
 reason=final['reason_code'];valid=final['valid'];cert=final['certified_zero']
 checks_note(rows,prefix+'/certified_zero_is_0',cert==0,{'certified_zero':cert})
 flat=[(b,d) for b in bands for d in b['depths']]
 if reason==0:
  checks_note(rows,prefix+'/valid_index_when_normal',valid==1 and abs(final['experimental_index']-1)<1e-5,
              {'index':final['experimental_index'],'valid':valid})
  checks_note(rows,prefix+'/reason_fields_zero_when_normal',all(final[name]==0 for name in q.RESULT_FIELDS[3:]),
              {name:final[name] for name in q.RESULT_FIELDS[3:]})
  checks_note(rows,prefix+'/all_reference_depths_pass_gate',all(d['referenceDepth']>=.15 for b,d in flat),
              {'referenceDepths':[round(d['referenceDepth'],9) for b,d in flat]})
 elif reason==3:
  first=next((b,d) for b,d in flat if d['referenceDepth']<.15)
  checks_note(rows,prefix+'/reason3_no_fake_index',valid==0 and final['experimental_index']==0,
              {'index':final['experimental_index'],'valid':valid})
  checks_note(rows,prefix+'/reason3_failed_band',final['failed_band_hz']==first[0]['bandHz'],
              {'failed_band_hz':final['failed_band_hz'],'expectedBandHz':first[0]['bandHz']})
  checks_note(rows,prefix+'/reason3_failed_modulation',final['failed_modulation_hz']==first[1]['modulationHz'],
              {'failed_modulation_hz':final['failed_modulation_hz'],'expectedModHz':first[1]['modulationHz'],'rawModHz':first[1]['rawModulationHz']})
  checks_note(rows,prefix+'/reason3_reference_depth',abs(final['reference_depth']-first[1]['referenceDepth'])<1e-6,
              {'reference_depth':final['reference_depth'],'expected':first[1]['referenceDepth']})
  checks_note(rows,prefix+'/reason3_measured_depth',abs(final['measured_depth']-first[1]['measuredDepth'])<1e-6,
              {'measured_depth':final['measured_depth'],'expected':first[1]['measuredDepth']})
  checks_note(rows,prefix+'/reason3_ratio_is_1',abs(final['transfer_ratio']-1)<1e-6,{'transfer_ratio':final['transfer_ratio']})
 elif reason==2:
  checks_note(rows,prefix+'/reason2_failed_band_known',final['failed_band_hz'] in q.CONTRACT_BANDS_HZ,
              {'failed_band_hz':final['failed_band_hz']})
 elif reason==4:
  checks_note(rows,prefix+'/reason4_ratio_gt_1.3',final['transfer_ratio']>1.3,{'transfer_ratio':final['transfer_ratio']})
 else:
  checks_note(rows,prefix+'/known_reason_code',False,{'reason_code':reason})
 checks_note(rows,prefix+'/reason_in_contract',reason in (0,1,2,3,4),{'reason_code':reason})
 checks_note(rows,prefix+'/failed_band_in_contract',final['failed_band_hz'] in q.CONTRACT_BANDS_HZ,{'failed_band_hz':final['failed_band_hz']})
 checks_note(rows,prefix+'/failed_modulation_in_contract',final['failed_modulation_hz'] in q.CONTRACT_MOD_HZ,{'failed_modulation_hz':final['failed_modulation_hz']})

def synthetic_pcm():
 t=np.arange(N)/FS
 sig=np.zeros(N)
 for band in q.BANDS:
  env=np.ones(N)
  for f in MODS[band]:env=env*(1+.5*np.sin(2*np.pi*f*t))
  sig=sig+.1*np.sin(2*np.pi*BANDS_HZ[band]*t)*env
 peak=float(np.max(np.abs(sig)))
 if peak>=.98:sig=sig*.9/peak;peak=.9
 return np.concatenate([sig,sig]),{'kind':'synthetic','carriersHz':[float(BANDS_HZ[b]) for b in q.BANDS],
  'modulationPairsHz':{str(float(BANDS_HZ[b])):[float(v) for v in MODS[b]] for b in q.BANDS},'peakFS':peak}

def _read_wav24(path,channel=0):
 import wave
 w=wave.open(str(path),'rb')
 ch=w.getnchannels();sw=w.getsampwidth();fs=w.getframerate();n=w.getnframes()
 raw=np.frombuffer(w.readframes(n),dtype=np.uint8);w.close()
 if sw==3:
  b=raw.reshape(-1,3)
  v=(b[:,0].astype(np.int32)|(b[:,1].astype(np.int32)<<8)|(b[:,2].astype(np.int32)<<16))
  v=np.where(v>=1<<23,v-(1<<24),v).astype(np.float64)/8388608.0
 elif sw==2:
  v=np.frombuffer(raw.tobytes(),dtype='<i2').astype(np.float64)/32768.0
 else:raise ValueError('unsupported sample width %d'%sw)
 v=v.reshape(n,ch)
 return v[:,min(channel,ch-1)],fs

def real_pcm_specs():
 """Real captured PCM used for the A/B implementation check. Primary source is
 an actual board live recording; second is an 8 s device capture example."""
 out=[]
 live=sorted(glob.glob(str(q.ROOT/'deployment/echo_event_wav_time_fix_20261029/live/events/*/*.wav')))
 if live:
  out.append({'kind':'real_field_capture','source':live[0],'channel':0,
   'note':'actual board event recording; resampled to 48k when needed and extended to 8s; A/B consistency record only'})
 cap=q.ROOT/'deployment/work_platform_20261013/phase12n_event_capture_20261021/examples/input.wav'
 out.append({'kind':'real_device_capture_8s','source':str(cap),'channel':0,
  'note':'exact 8s 6-channel device capture example, channel0 used for both A and B'})
 return out

def prepare_real_pcm(spec):
 x,fs=_read_wav24(Path(spec['source']),spec['channel'])
 if fs!=FS:
  from scipy import signal as sps
  x=sps.resample_poly(x,FS,fs)
 x=x[:N] if len(x)>=N else np.resize(x,N)
 peak=float(np.max(np.abs(x)))
 if peak>0:
  x=x*.9/peak
 spec=dict(spec);spec.update({'sourceSampleRate':fs,'framesUsed':N,'peakFS':peak,
  'normalizedToPeakFS':0.9 if peak>0 else 0})
 return np.concatenate([x,x]),spec

def same_pcm_run(verbose=True):
 rows=[];t0=time.time();pl=PL()
 pcm,meta=synthetic_pcm()
 m,calls=run_chain(pcm,pl)
 ev=evaluate(m,rows,'synthetic');consistency_checks(rows,'synthetic',ev)
 rows.append({'check':'synthetic/15_stages_reached_DONE','pass':len(calls)==15,'detail':{'stageSubmissions':calls}})
 syn={'source':meta,'stageSubmissions':calls,'bands':ev['bands'],'final':ev['final']}
 reals=[]
 for spec in real_pcm_specs():
  pcm2,meta2=prepare_real_pcm(spec)
  m2,calls2=run_chain(pcm2,pl)
  ev2=evaluate(m2,rows,spec['kind']);consistency_checks(rows,spec['kind'],ev2)
  rows.append({'check':spec['kind']+'/15_stages_reached_DONE','pass':len(calls2)==15,'detail':{'stageSubmissions':calls2}})
  reals.append({'source':meta2,'stageSubmissions':calls2,'bands':ev2['bands'],'final':ev2['final']})
 if verbose:
  for r in rows:print(('PASS' if r['pass'] else 'FAIL'),r['check'])
  print('PL submissions total',pl.calls,'elapsed %.2fs'%(time.time()-t0))
 result={'generatedAt':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'engine':'room_native.dll scalar_native',
  'enginePath':str(DLL),'engineSHA256':hashlib.sha256(DLL.read_bytes()).hexdigest(),
  'samplesPerTrace':N,'decimationsPerTrace':N//DEC,'stages':15,'arbitraryScale':False,
  'synthetic':syn,'realPcm':reals,'checks':rows,'plSubmissions':pl.calls,
  'elapsedSeconds':round(time.time()-t0,3),'allPass':all(r['pass'] for r in rows)}
 return result

def main():
 result=same_pcm_run(verbose=True)
 (R/'SAME_PCM_CHECK.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print('SAME_PCM_CHECK',('PASS' if result['allPass'] else 'FAIL'),'checks',len(result['checks']))
 return 0 if result['allPass'] else 1

if __name__=='__main__':
 sys.exit(main())
