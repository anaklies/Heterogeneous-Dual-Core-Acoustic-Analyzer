"""Single deployment entry: disjoint PL program/data pools and descriptor tables.
No signal processing is performed here: only assembly/configuration and raw upload.
Do not load before reserving DDR in the matched Linux device tree.
"""
from pathlib import Path
import json,hashlib,struct
import numpy as np
from programs import install,vector,smoothing,band_sums,shape,difference
from analysis_statistics import welch,compare
from frequency_drift import frequency_drift
from cross_spectral_services import cross_spectra,install_cross
import p2_chains as p2
import linear_periodic as linear
import manual_das as das
import das_map
import room_services as room
from room_band_decay import band_decay
import noise_services as noise
import extra_spectral as extra
from continuous_guard import checked_time_response

ARENA_WORDS=4194304
PRIVATE=524288
P1_TABLE=PRIVATE
P2_TABLE=PRIVATE+16*64
BASIC_BASE=600000
BASIC_STRIDE=24576
CROSS_BASE=851968
P2_BASE=1048576
FS=49162010/1024


def _p2(memory,name,params):
 args=dict(params)
 if name in ("FAST","SLOW","FAST_recorded","SLOW_recorded","time_response_recorded"):
  import recorded_time_response as rt
  args.setdefault("samples",48000);return rt.install(memory,rt.recorded_time_response(sample_rate=FS,**args),base=P2_BASE),True
 if name=="stipa":
  from stipa_graph import install_graph_stage
  args.setdefault("index",0);return install_graph_stage(memory,base=P2_BASE,**args),True
 if name in ('cepstrum','envelope','envelope_spectrum'):
  spec=p2.cepstrum(**args) if name=='cepstrum' else p2.envelope(spectrum=name=='envelope_spectrum',**args)
  return p2.install(memory,spec,base=P2_BASE),False
 if name in ('autocorrelation','cross_correlation','gcc_phat','fundamental'):
  if name=='fundamental':spec=linear.fundamental(sample_rate=FS,**args)
  else:
   if name!='autocorrelation':args.setdefault('other',1)
   spec=linear.linear_correlation(phat=name=='gcc_phat',**args)
  return linear.install(memory,spec,base=P2_BASE),False
 if name=='manual_das':return das.install_das(memory,das.manual_das(sample_rate=FS,**args),base=P2_BASE),False
 if name in ('das_map','band_das'):
  return das_map.install(memory,das_map.power_map(sample_rate=FS,**args),base=P2_BASE),False
 if name in ('room_decay','room_band_decay'):
  args.setdefault('samples',24000)
  spec=room.room_ir(sample_rate=FS,**args) if name=='room_decay' else band_decay(sample_rate=FS,**args)
  return room.install_room(memory,spec,base=P2_BASE),True
 if name=='zoom':return extra.install_zoom(memory,extra.zoom_spectrum(FS,**args),base=P2_BASE),True
 if name in ('harmonics','sidebands','spectral_kurtosis'):
  f={'harmonics':extra.harmonic_energy,'sidebands':extra.sidebands,'spectral_kurtosis':extra.spectral_kurtosis}[name]
  spec=f(**args) if name=='spectral_kurtosis' else f(FS,**args)
  return p2.install(memory,spec,base=P2_BASE),False
 if name in ('weighting','level_statistics','relative_insulation','noise_curve','FAST','SLOW'):
  if name=='weighting':spec=noise.weighted_level(FS,**args)
  elif name=='level_statistics':spec=noise.level_statistics(**args)
  elif name=='relative_insulation':spec=noise.relative_band_difference(**args)
  elif name=='noise_curve':spec=noise.noise_curve(**args)
  else:spec=checked_time_response(FS,name,**args)
  return noise.install_noise(memory,spec,base=P2_BASE),name in ('relative_insulation','noise_curve')
 if name=='AB_limit':
  spec=install(memory,compare(**args),base=P2_BASE);count=spec['output_words']//3;begin=spec['output']+4096;u=memory.view(np.uint32)
  for slot in range(4):u[spec['descriptor']+16*slot+5:spec['descriptor']+16*slot+7]=[begin,2*count]
  spec['metadata']['input_word_offset']=begin
  return spec,True
 raise ValueError('unsupported/stage-managed P2 profile; STIPA requires its explicit finite stage graph')


def build_profile(p2_name=None,params=None,session=1,config=1,generation=1,input_ready=False):
 if any(not isinstance(v,int)or not 1<=v<=0xffffffff for v in (session,config,generation)):raise ValueError('nonzero uint32 identities')
 memory=np.zeros(ARENA_WORDS,np.float32);u=memory.view(np.uint32)
 definitions=[('snapshot',vector('copy')),('peak_hold',vector('peak_hold')),('spectrum_ema',vector('ema')),('smoothing',smoothing()),('octave',band_sums(FS,1)),('third_octave',band_sums(FS,3)),('shape',shape(FS)),('flux_delta',difference()),('welch',welch()),('frequency_drift',frequency_drift(FS))]
 services={};intervals=[]
 for index,(name,program) in enumerate(definitions):
  base=BASIC_BASE+index*BASIC_STRIDE;s=install(memory,program,base=base,session=session,config=config,generation=generation)
  services[name]=s;intervals.append((base,base+BASIC_STRIDE,name))
 services['selected_pair_CSD']=install_cross(memory,cross_spectra(sample_rate=FS),base=CROSS_BASE,session=session,config=config,generation=generation)
 intervals.append((CROSS_BASE,CROSS_BASE+24576,'selected_pair_CSD'))
 for index,s in enumerate(services.values()):u[P1_TABLE+64*index:P1_TABLE+64*(index+1)]=u[s['descriptor']:s['descriptor']+64]
 selected=None;requires_input=False
 if p2_name:
  selected,requires_input=_p2(memory,p2_name,params or {})
  end=max(selected['output']+int(u[selected['descriptor']+8]),P2_BASE+24576)
  assert end<=ARENA_WORDS
  intervals.append((P2_BASE,end,p2_name));u[P2_TABLE:P2_TABLE+64]=u[selected['descriptor']:selected['descriptor']+64]
  # All installers publish four slot descriptors; rekey one locked transaction.
  for slot in range(4):
   d=P2_TABLE+16*slot;assert u[d]==0x414c5531
   u[d+11]=session;u[d+12]=config;u[d+14]=generation
  selected['scheduled_descriptor']=P2_TABLE
 for i,(lo,hi,name)in enumerate(intervals):
  if lo<PRIVATE+1088 or hi>ARENA_WORDS:raise ValueError('private allocation escaped')
  for a,z,other in intervals[:i]:
   if lo<z and a<hi:raise ValueError('overlapping runtime allocations: '+name+' '+other)
 cfg=[0]*32;cfg[:8]=[session,config,0x10000000,ARENA_WORDS,0x10000000,0x11000000,P1_TABLE,P2_TABLE]
 cfg[8]=1|((2|4) if selected and (not requires_input or input_ready) else 0)
 cfg[9:15]=[0x12000000,0x1000000,0x12000000,0x14000000,0x13000000,0]
 cfg[15]=len(services)-1;cfg[30]=64;cfg[31]=int(requires_input)
 if p2_name=='stipa':cfg[8]&=~1 # keep P1 off across the complete multistage graph
 meta=dict(format='SMI1 sparse LE32, private clear before patches',session=session,config=config,generation=generation,
  arena_words=ARENA_WORDS,arena_byte_address=cfg[2],p1_services=services,p2=selected,config32=cfg,allocations=intervals,
  p2_requires_input=requires_input,input_ready=bool(input_ready),all_service_RTL_accepted=False,
  activation='Only after PS DDR reservation and with P1/P2 disabled+drained during upload',
  special_limits=['FAST/SLOW needs consecutive raw frames; ordinary periodic carousel cannot guarantee it','STIPA stage graph and cost remain separately pending','No automatic DOA, XYZ, tracker or absolute SPL'],
  installed_programs_are='PL scalar instructions; no CPU DSP fallback')
 return memory,meta


def save_profile(directory,**kwargs):
 memory,meta=build_profile(**kwargs);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);u=memory.view(np.uint32)
 # Every omitted history/context word must first be zeroed. Never clear P0 slots.
 data=bytearray(struct.pack('<4sIII',b'SMI1',ARENA_WORDS,PRIVATE,ARENA_WORDS-PRIVATE))
 nonzero=np.flatnonzero(u[PRIVATE:])+PRIVATE
 if len(nonzero):
  start=last=int(nonzero[0])
  for value in [*map(int,nonzero[1:]),ARENA_WORDS+32]:
   if value-last>16:
    data+=struct.pack('<II',start,last-start+1)+u[start:last+1].astype('<u4').tobytes();start=value
   last=value
 data+=struct.pack('<II',0,0);meta['image_sha256']=hashlib.sha256(data).hexdigest();meta['image_bytes']=len(data)
 (directory/'profile_init.smi').write_bytes(data);(directory/'PROFILE.json').write_text(json.dumps(meta,indent=2))
 return meta
if __name__=='__main__':
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('output');ap.add_argument('--p2');ap.add_argument('--params',default='{}');args=ap.parse_args()
 m=save_profile(args.output,p2_name=args.p2,params=json.loads(args.params));print('PROFILE_ASSEMBLED',m['image_bytes'],'bytes; NOT hardware acceptance')
