"""Assemble private PL plans only. No DSP execution, device writes or P0 edits.

Run: python build_plans.py [--output DIR] [--stipa-weights]
Import compile_feature(feature_id, params) for parameter-specific private plans.
All addresses are arena word indices; all binary records are little-endian u32.
"""
from pathlib import Path
import argparse, csv, hashlib, importlib, inspect, json, math, struct, sys
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SERVICES=ROOT/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/services'
sys.path.insert(0,str(SERVICES))
import programs as p
import p2_chains as chains
import analysis_statistics as statistics
import linear_periodic as linear
import extra_spectral as extra
import noise_services as noise
import room_services as room
import room_band_decay as room_band
import recorded_time_response as recorded
import manual_das as das
import das_map
import stipa_graph as stipa
import stipa_offline as stipa_old
import raw_conversion
import producers
from frequency_drift import frequency_drift
from cross_spectral_services import cross_spectra, install_cross

FS=49162010/1024
BASE=1048576
TABLE=525312
ARENA_WORDS=4194304
P0_END=524288
PROFILE=json.loads((ROOT/'deployment/echo_ps_release_20261025/profiles/default/PROFILE.json').read_text())
MAP=ROOT/'deployment/releases/SixMic3D_PL_Analysis_RC1_RecoveryFix_20261024/FUNCTION_EXECUTION_MAP.csv'
P1={'psd':'welch','spectrum_average':'spectrum_ema','octave':'octave','third_octave':'third_octave',
    'peak_hold':'peak_hold','smoothing':'smoothing','frequency_tracking':'shape','frequency_drift':'frequency_drift',
    'csd':'selected_pair_CSD','coherence_phase':'selected_pair_CSD',
    'centroid':'shape','flatness':'shape','spectral_flux':'flux_delta'}
BUILTIN={'io_pcm','levels_core','data_continuity','fft','stft','spatial_interface','signal_quality','levels_extended','event_trigger'}
FIELDS={
 'io_pcm':['sample_PCM24'],'data_continuity':['source_frame_id','raw_cursor','continuity_status'],
 'signal_quality':['capture_valid','fresh','source_frame_id'],'spatial_interface':['manual_direction','manual_grid','map_result_identity'],
 'event_trigger':['event_status','clip_capture_identity','raw_clip_PCM24'],
 'fft':['amplitude_FS','PSD_FS2_per_Hz','bin_power_FS2'],'stft':['amplitude_FS','PSD_FS2_per_Hz','bin_power_FS2'],
 'psd':['distinct_frame_count_uint32','mean_PSD_FS2_per_Hz'],
 'zoom_fft':['amplitude_FS','PSD_FS2_per_Hz'],'fundamental':['correlation_FS2_sum','fundamental_hz','period_strength','valid'],
 'spectrum_average':['EMA_bin_power_FS2'],'peak_hold':['max_bin_power_FS2'],'smoothing':['smoothed_bin_power_FS2'],
 'octave':['band_power_FS2'],'third_octave':['band_power_FS2'],
 'frequency_time_weighting':['weighted_power_FS2','weighted_dBFS','valid'],
 'envelope_hilbert':['analytic_envelope_FS'],'envelope_spectrum':['envelope_FFT_magnitude'],'modulation_spectrum':['envelope_FFT_magnitude'],
 'autocorrelation':['linear_correlation_FS2_sum'],'cross_correlation':['linear_correlation_FS2_sum'],'gcc_phat':['relative_PHAT_correlation'],
 'spectrum_freeze':['signed_delta_FS2','unused_middle','threshold_flags'],'relative_limit':['signed_delta_FS2','unused_middle','threshold_flags'],
 'cepstrum':['real_cepstrum_log_FS'],'spectral_kurtosis':['frame_count_float32','sum_power','sum_power_squared','kurtosis','valid'],
 'full_das':['point_power_FS2','peak_index_uint32','peak_power_FS2','peak_valid'],
 'band_das':['point_power_FS2','peak_index_uint32','peak_power_FS2','peak_valid'],
 'spatial_grid':['point_azimuth_deg','point_elevation_deg','point_power_FS2'],
 'spatial_peaks':['peak_index_uint32','peak_power_FS2','peak_valid'],
 'relative_insulation':['relative_difference_dB','valid'],'noise_rating':['rating','valid','estimated'],
 'stipa_experimental':['experimental_index','valid','certified_zero'],
}
UNITS={
 'io_pcm':'signed24 digital counts in LE32; FS normalization divisor8388608',
 'levels_core':'RMS/peak FS; dBFS; crest dimensionless; clipping sample count',
 'levels_extended':'FS','data_continuity':'frame/sample counts; status bit fields',
 'fft':'amplitude FS; PSD FS squared/Hz; binPower FS squared',
 'stft':'amplitude FS; PSD FS squared/Hz; binPower FS squared; time seconds',
 'spatial_interface':'azimuth/elevation degrees; power FS squared; identities uint32',
 'signal_quality':'valid/fresh Boolean; frame/sample counts',
 'frequency_tracking':'centroid/peak Hz; flatness dimensionless; peak power FS squared',
 'frequency_drift':'Hz; Hz/second; valid/initialized Boolean; frame uint32',
 'directed_das':'complex raw Hann FFT; PSD FS squared/Hz',
 'centroid':'centroid/peak Hz; flatness dimensionless; peak power FS squared',
 'flatness':'centroid/peak Hz; flatness dimensionless; peak power FS squared',
 'event_trigger':'status bit fields; raw PCM24 digital counts; capture/frame identities uint32',
 'level_statistics':'L10/L50/L90/Leq dBFS; valid Boolean; observation count',
 'zoom_fft':'amplitude FS; PSD FS squared/Hz; frequency Hz',
 'harmonic_ratio':'harmonic band powers FS squared; THD dimensionless ratio; valid Boolean',
 'sidebands':'band powers FS squared; carrier ratios dimensionless; valid Boolean',
 'spectral_flux':'positive/L1 flux FS squared; RMS delta FS squared; private history FS squared',
 'room_decay':'EDT/T20/T30 seconds; R2 dimensionless; validity Boolean; decay dB; time seconds',
 'room_clarity':'C50/C80 dB; D50 percent; energies FS squared sum; validity Boolean',
 'spectral_decay':'filtered EDT/T20/T30 seconds; decay dB; time seconds',
 'relative_insulation':'relative level difference dB; validity Boolean; no Rw claim',
 'stipa_experimental':'index0..1; arithmetic validity Boolean; certified always0',
 'noise_rating':'NC/NR curve number; validity/estimated Boolean; explicit reference input dBFS/dBSPL',
}

# Tuple: assembler, installer, explicit assembly defaults. Defaults are useful
# examples, not invented measurement/calibration assertions.
DEFS={
 'psd':(statistics.welch,p.install,{}),
 'spectrum_average':(p.vector,p.install,{'kind':'ema'}),
 'octave':(p.band_sums,p.install,{'sample_rate':FS,'fraction':1}),
 'third_octave':(p.band_sums,p.install,{'sample_rate':FS,'fraction':3}),
 'peak_hold':(p.vector,p.install,{'kind':'peak_hold'}),
 'smoothing':(p.smoothing,p.install,{}),
 'frequency_tracking':(p.shape,p.install,{'sample_rate':FS}),
 'frequency_drift':(frequency_drift,p.install,{'sample_rate':FS}),
 'directed_das':(producers.managed_local_das,das.install_das,{'sample_rate':FS}),
 'csd':(cross_spectra,install_cross,{'sample_rate':FS}),
 'coherence_phase':(cross_spectra,install_cross,{'sample_rate':FS}),
 'energy_change':(producers.energy_change,p.install,{}),
 'band_tracking':(producers.band_tracking,p.install,{'sample_rate':FS}),
 'centroid':(p.shape,p.install,{'sample_rate':FS}),
 'flatness':(p.shape,p.install,{'sample_rate':FS}),
 'frequency_time_weighting':(noise.weighted_level,noise.install_noise,{'sample_rate':FS}),
 'level_statistics':(noise.level_statistics,noise.install_noise,{}),
 'zoom_fft':(extra.zoom_spectrum,extra.install_zoom,{'fs':FS,'center_hz':FS/4}),
 'fundamental':(linear.fundamental,linear.install,{'sample_rate':FS}),
 'harmonic_ratio':(extra.harmonic_energy,chains.install,{'fs':FS,'f0':1000.0}),
 'sidebands':(extra.sidebands,chains.install,{'fs':FS,'carrier':6000.0,'spacing':1000.0,'half_width':100.0}),
 'envelope_hilbert':(chains.envelope,chains.install,{}),
 'envelope_spectrum':(chains.envelope,chains.install,{'spectrum':True}),
 'modulation_spectrum':(chains.envelope,chains.install,{'spectrum':True}),
 'autocorrelation':(linear.linear_correlation,linear.install,{}),
 'full_das':(das_map.power_map,das_map.install,{'sample_rate':FS,'count':1024}),
 'band_das':(das_map.power_map,das_map.install,{'sample_rate':FS}),
 'cross_correlation':(linear.linear_correlation,linear.install,{'other':1}),
 'gcc_phat':(linear.linear_correlation,linear.install,{'other':1,'phat':True}),
 'spectral_flux':(p.difference,p.install,{}),
 'spectrum_freeze':(statistics.compare,p.install,{}),
 'relative_limit':(statistics.compare,p.install,{}),
 'cepstrum':(chains.cepstrum,chains.install,{}),
 'spectral_kurtosis':(extra.spectral_kurtosis,chains.install,{}),
 'spatial_grid':(das_map.power_map,das_map.install,{'sample_rate':FS}),
 'spatial_peaks':(das_map.power_map,das_map.install,{'sample_rate':FS}),
 'room_decay':(room.room_ir,room.install_room,{'samples':24000,'sample_rate':FS}),
 'room_clarity':(room.room_ir,room.install_room,{'samples':24000,'sample_rate':FS}),
 'spectral_decay':(room_band.band_decay,room.install_room,{'samples':24000,'sample_rate':FS}),
 'relative_insulation':(noise.relative_band_difference,noise.install_noise,{}),
 'noise_rating':(producers.noise_rating,noise.install_noise,{'sample_rate':FS}),
}

def clean(value):
 if isinstance(value,np.generic):return value.item()
 if isinstance(value,np.ndarray):return value.tolist()
 if isinstance(value,Path):return str(value)
 raise TypeError(type(value).__name__)

def params_for(fn, overrides):
 result={}
 for name,q in inspect.signature(fn).parameters.items():
  if name.startswith('_'):continue
  default=overrides.get(name,q.default)
  result[name]={'default':None if default is inspect.Parameter.empty else default,
                'required':default is inspect.Parameter.empty}
  if name in ('channel','channel_i','channel_j','other'):result[name]['range']=[0,5]
  if name=='first':result[name]['range']=[0,1024]
  if name=='count':result[name]['range']=[1,1025]
  if name=='alpha':result[name]['range']='0 < alpha <= 1'
  if name in ('sample_rate','fs'):result[name]['unit']='Hz'
  if name in ('center','center_hz','f0','carrier','spacing','half_width','low','high','sound_speed'):result[name]['unit']='m/s' if name=='sound_speed' else 'Hz'
  if name in ('fraction',):result[name]['enum']=[1,3]
  if name=='weighting':result[name]['enum']=['A','C','Z']
  if name=='family':result[name]['enum']=['NR','NC']
  if name=='input_unit':result[name]['enum']=['dBFS','dBSPL']
  if name=='orders':result[name]['range']=[1,16]
  if name=='samples':result[name]['range']=[32,60000]
  if name=='azimuth_deg':result[name]['range']=[-360,360]
  if name=='elevation_deg':result[name]['range']=[-90,90]
 # Keep exact validators beside the schema so coupled constraints are not lost.
 src=inspect.getsource(fn)
 return result,[line.strip() for line in src.splitlines() if 'raise ValueError' in line or line.strip().startswith('if ')]

def write_plan(path,plan):
 """SMP records: LE32 wordOffset,wordCount,words[count]; final0,0.
 No implicit clear or device write. Clear ranges are explicit in JSON.
 """
 if 'patchRecords' in plan:
  data=bytearray()
  for r in plan['patchRecords']:
   a,n=r['wordOffset'],r['wordCount'];assert n==len(r['words'])
   assert (a==TABLE and n==64) or BASE<=a<a+n<=ARENA_WORDS
   data+=struct.pack('<II',a,n)+np.asarray(r['words'],dtype='<u4').tobytes()
  data+=struct.pack('<II',0,0);binary=path.with_suffix('.smp');binary.write_bytes(data)
  plan['patchFile']=str(binary.relative_to(path.parent.parent)).replace('\\','/')
  plan['patchSHA256']=hashlib.sha256(data).hexdigest()
 path.write_text(json.dumps(plan,default=clean,separators=(',',':')),encoding='utf-8')

def records(memory, ranges):
 u=memory.view(np.uint32); answer=[]
 for begin,size in ranges:
  assert P0_END<=begin<begin+size<=ARENA_WORDS
  answer.append({'wordOffset':begin,'wordCount':size,'words':u[begin:begin+size].tolist()})
 return answer

def sparse_records(memory,begin,end):
 u=memory.view(np.uint32); indices=np.flatnonzero(u[begin:end])+begin
 if len(indices)==0:return []
 out=[];start=last=int(indices[0])
 for v in [*map(int,indices[1:]),end+32]:
  if v-last>16:
   out.extend(records(memory,[(start,last-start+1)]));start=v
  last=v
 return out

def compile_feature(feature_id, params=None, session=1,config=1,generation=1):
 """Return one isolated P2 plan; input buffers remain zero and require capture.

 Caller must enforce input requirements from REGISTRY.json BEFORE scheduling.
 Patches are installed with P1/P2 disabled+drained, then identities are rekeyed.
 No caller may treat a successful assembly as acoustic/hardware acceptance.
 """
 fn,installer,defaults=DEFS[feature_id];args=dict(defaults);args.update(params or {})
 unknown=set(args)-set(inspect.signature(fn).parameters)
 if unknown:raise ValueError('unknown parameters: '+','.join(sorted(unknown)))
 spec=fn(**args);memory=np.zeros(ARENA_WORDS,np.float32)
 s=installer(memory,spec,base=BASE);u=memory.view(np.uint32)
 if feature_id in ('spectrum_freeze','relative_limit'):
  # Compare consumes explicit private A/B spectra rather than the FFT triplets.
  count=s['output_words']//3;source=s['output']+4096
  for slot in range(4):u[BASE+16*slot+5:BASE+16*slot+7]=[source,2*count]
  s['metadata']['input_word_offset']=source
 for slot in range(4):
  u[BASE+16*slot+11]=session;u[BASE+16*slot+12]=config;u[BASE+16*slot+14]=generation
 u[TABLE:TABLE+64]=u[BASE:BASE+64]
 end=max(BASE+32768,s['output']+s['output_words'])
 if feature_id=='zoom_fft':end=BASE+73728
 assert end<=ARENA_WORDS
 patches=records(memory,[(TABLE,64)])+sparse_records(memory,BASE,end)+records(memory,[(int(u[BASE+2]),int(u[BASE+3])*4),(BASE+4352,320)])
 return {'kind':'p2_program','featureId':feature_id,'params':args,'descriptorTable':TABLE,
  'base':BASE,'arenaWords':ARENA_WORDS,'producer':fn.__module__+'.'+fn.__name__,
  'privateClearRanges':[{'wordOffset':BASE,'wordCount':end-BASE}],
  'patchRecords':patches,'service':s,'outputWordOffset':s['output'],'outputWordCount':s['metadata'].get('output_count',s['output_words']),
  'identities':dict(session=session,config=config,generation=generation),
  'activation':'disable+drain P1/P2; clear only listed private pool; patch; upload real inputs; commit matching identities; run pinned source once; wait DONE; page result',
  'assemblyOnly':True,'hardwareAccepted':False}

def compile_stipa_stage(index,n=720000,confirmed=False,weights=False):
 """Compile every actual stage instruction without touching captured workspace.
 Weight generation accepts n/band/coefficient only and performs no audio DSP.
 """
 d=stipa.graph()[index];q=stipa_old.layout(n);memory=np.zeros(ARENA_WORDS,np.float32)
 if BASE+8192+q['words']>ARENA_WORDS:raise ValueError('STIPA arena bounds')
 if d['kind']=='convert_raw_PCM24':c,_,_=raw_conversion.convert_pcm24(2*n,0)
 elif d['kind']=='validate_captures':c,_=stipa_old.validation_program(n,confirmed)
 elif d['kind']=='filter':c,_,_=stipa_old.filter_program(n,d['band'],d['trace'])
 elif d['kind']=='fit':c,_=stipa_old.fit_program(n,d['band'],d['trace'],d['coefficient'])
 else:c,_=stipa.final_program(n,confirmed)
 s=stipa_old.install_stage(memory,c,q,base=BASE);u=memory.view(np.uint32);prototype=u[BASE:BASE+16].copy()
 for slot in range(4):
  v=prototype.copy();v[4]=BASE+4352+80*slot;v[9]=512;v[13]=index+1
  u[BASE+16*slot:BASE+16*(slot+1)]=v;u[TABLE+16*slot:TABLE+16*(slot+1)]=v
 ranges=[(TABLE,64),(BASE+128,len(c.words)*4),(BASE+4352,320),(s['output']-16,16)]
 plan={'stage':index,'definition':d,'scheduledDescriptor':TABLE,'service':s,'workspace':q,
       'patchRecords':records(memory,ranges),'clearWorkspace':False,'requiresPriorStagesDone':index>0,
       'confirmed':confirmed,'samples':n,'outputWordOffset':s['output']}
 if d['kind']=='fit':
  plan['weightPage']={'key':f"band{d['band']}_coefficient{d['coefficient']}",'wordOffset':s['output']+q['weight'],'wordCount':n,
                      'producer':'stipa_offline.regression_weights','materialized':weights}
  if weights:plan['_weightData']=stipa_old.regression_weights(n,d['band'],d['coefficient'])
 return plan

def input_contract(fid):
 c={'source':'pinned six-channel stream_fft2048 Hann snapshot','layout':'channel stride8192; complex raw FFT4096 words; 1025 amplitude/PSD/binPower triplets at4096',
    'sampleRateHz':FS,'fftSize':2048,'frameRequirement':'same immutable slot + matching session/config/generation; unique fresh frame IDs for accumulated metrics','requiresAcquisition':True}
 if fid in ('io_pcm','data_continuity','signal_quality','event_trigger'):
  c.update(source='P0 live acquisition and status/mailbox',layout='sign-extended PCM24 LE32 raw ring; explicit continuity counters and immutable descriptor metadata; event clip mailbox for triggered capture')
 if fid=='spatial_interface':c.update(source='manual analysis/view configuration and valid PL map result',requires=['manual requested direction or grid; no automatic source direction'])
 if fid in ('fundamental','autocorrelation','cross_correlation','gcc_phat'):
  c.update(source='pinned raw planar PCM24 slot',layout='6x2048 sign-extended PCM24 LE32; stride2048; first1024 samples/channel; PL demeans and zero pads to2048',window='rectangular; no Hann')
 if fid in ('room_decay','room_clarity','spectral_decay'):
  c.update(source='explicit onset-trimmed measured mono impulse response',layout='float32 FS at output+32; samples32..60000',requires=['external excitation/IR capture','explicit onset trim provenance; arbitrary live PCM rejected'],preprocessing='no automatic onset detection or RIR extraction exists')
 if fid=='zoom_fft':c.update(source='captured contiguous normalized mono audio',layout='float32 FS at output+raw_offset; length raw_samples from assembler metadata',requires=['contiguous capture','PCM24 normalization must execute on PL'])
 if fid in ('spectrum_freeze','relative_limit'):
  c.update(source='two explicit PL bin-power snapshots A and B',layout='float32 FS2/bin [A[count],B[count]] at service.metadata.input_word_offset',requires=['capture/freeze reference B','matching channel/grid/gain/source metadata'])
 if fid=='relative_insulation':c.update(source='two explicit PL octave energy captures',layout='float32 powers A then B at output+2*bands',requires=['matching measurement chain/gain/grid metadata','metadata_matched=true only after validation'],defaultProducesValid=False)
 if fid=='noise_rating':c.update(source='PL-produced octave levels with stated SPL calibration or nominal reference',layout='float32 levels at output+32; centers_hz from producer metadata',requires=['calibration source/mode and offsetDB for dBFS','all octave bands resolved'],defaultProducesValid=False)
 if fid=='stipa_experimental':c.update(source='captured reference AND received active STIPA test traces',layout='two sign-extended PCM24 LE32 mono traces, reference first, each n samples at output+[0,n]',requires=['15s minimum nominal48kHz; n720000 default','confirmed active reference signal; arbitrary speech rejected','all101 ordered stages done','same captured workspace retained; P1 off throughout graph'],sampleRateHz=48000,defaultProducesValid=False)
 return c

def builtin(fid):
 fields={'levels_core':{'rms_FS':7171,'peak_FS':7172,'rms_dBFS':7175,'crest_ratio':7176,'clip_count':7177,'nonzero_energy_valid':7178},
         'levels_extended':{'peak_to_peak_FS':7173,'mean_FS':7174},
         'fft':{'complex':{'offset':0,'words':4096},'triplets':{'offset':4096,'count':1025,'fields':['amplitude_FS','PSD_FS2_per_Hz','bin_power_FS2']}},
         'stft':{'triplets':{'offset':4096,'count':1025,'fields':['amplitude_FS','PSD_FS2_per_Hz','bin_power_FS2']}}}.get(fid,{})
 return {'kind':'p0_builtin','producer':'integration/shared_backend/stream_fft.cpp' if fields else 'integration/instrument_top.sv',
         'channelStrideWords':8192,'fields':fields,'privatePatchRequired':False,
         'validity':'rms_dBFS is encoded0 for silence in current producer; nonzero_energy_valid=0 suppresses interpretation' if fid.startswith('levels') else 'P0 status/frame/source validity required; fresh sequence and matching capture identity',
         'acquisitionRequired':True}

def build(output,stipa_weights=False):
 output=Path(output);output.mkdir(parents=True,exist_ok=True);(output/'plans').mkdir(exist_ok=True)
 rows=[r for r in csv.DictReader(MAP.open(encoding='utf-8-sig')) if r['id']!='srpdnn_main'];registry=[]
 for row in rows:
  fid=row['id'];entry={'featureId':fid,'name':row['name'],'tier':row['tier'],'input':input_contract(fid),'hardwareAccepted':False}
  if fid in BUILTIN:
   plan=builtin(fid);entry.update(producer=plan['producer'],params={'channel':{'default':0,'range':[0,5]}},output=plan)
  elif fid=='stipa_experimental':
   graph=stipa.graph();stages=[];weight_cache={}
   for i in range(len(graph)):
    plan=compile_stipa_stage(i,confirmed=True,weights=False)
    if 'weightPage' in plan and stipa_weights:
     w=plan['weightPage'];key=w['key'];d=plan['definition']
     if key not in weight_cache:
      values=stipa_old.regression_weights(720000,d['band'],d['coefficient']);path=output/'plans'/f'stipa_{key}.f32le';path.write_bytes(values.astype('<f4').tobytes());weight_cache[key]=path.name
     w.update(materialized=True,file=weight_cache[key],sha256=hashlib.sha256((output/'plans'/weight_cache[key]).read_bytes()).hexdigest())
    path=output/'plans'/f'stipa_stage_{i:03}.json';write_plan(path,plan);stages.append({'stage':i,**graph[i],'plan':str(path.relative_to(output)).replace('\\','/'),'patchFile':plan['patchFile'],'weightPage':plan.get('weightPage')})
   plan={'kind':'stage_graph','stages':stages,'samples':720000,'initialClearRange':{'wordOffset':BASE,'wordCount':8192+4*720000+256},'weightsMaterialized':stipa_weights,'finalOutput':{'offset':BASE+8192,'fields':['experimental_index','valid','certified_zero']},'captureValidationRequired':True}
   entry.update(producer='stipa_graph.graph + stipa_graph.install_graph_stage',params={'samples':{'default':720000,'range':[720000,(ARENA_WORDS-BASE-8192-256)//4]},'confirmed':{'default':False,'requires':'verified reference+received acquisition'}},output=plan['finalOutput'])
  else:
   fn,_,defaults=DEFS[fid];plan=compile_feature(fid);schema,validators=params_for(fn,defaults)
   entry.update(producer=plan['producer'],params=schema,parameterConstraints=validators,output={'encoding':'LE float32 except explicit uint32 fields in producer metadata','metadata':plan['service']['metadata'],'wordOffset':plan['outputWordOffset'],'wordCount':plan['outputWordCount']})
   if fid in P1:
    route=P1[fid];entry['defaultP1Route']={'name':route,**PROFILE['p1_services'][route],'scope':'fixed default profile; other parameters compile isolated P2 plan'}
   if fid=='relative_insulation':
    verified=compile_feature(fid,{'metadata_matched':True});vpath=output/'plans'/'relative_insulation_verified.json';write_plan(vpath,verified)
    entry['verifiedCapturePlan']={'file':vpath.relative_to(output).as_posix(),'patchFile':verified['patchFile'],'params':{'metadata_matched':True},'requires':'two actual PL octave-energy A/B captures with matching gain/measurement-chain/source/grid metadata validated by PS; no arbitrary Boolean bypass'}
   if fid=='noise_rating':
    entry['runtimeInput']=plan['service']['metadata']['runtimeInput']
    entry['params'].update({'referenceConfirmed':{'required':True,'runtimeInput':True,'mustEqual':True},'referenceOffsetDb':{'required':True,'runtimeInput':True,'unit':'dB','constraint':'finite explicit nominal reference offset'},'calibrationSource':{'required':True,'runtimeInput':True,'constraint':'nonempty source/reference explanation'}})
    entry['input'].update(source='fresh actual pinned stream_fft2048 PSD',layout='1025 PSD triplets at channel*8192+4097; PL integrates exact NR/NC octave-center bin supports',requires=['referenceConfirmed=true','explicit finite referenceOffsetDb','nonempty calibrationSource','fresh valid immutable source snapshot'],defaultProducesValid=False)
    entry['output']['metadata']['runtimeInput']=entry['runtimeInput']
   if fid=='directed_das':
    entry['runtimeInput']=plan['service']['metadata']['runtimeInput']
    for key,value in entry['runtimeInput'].items():
     value['wordOffset']=plan['service']['output']+value['wordOffsetRelativeToOutput']
     entry['params'][key].update(runtimeInput=True,constraint='finite and within stated range; local array frame only')
    entry['input'].update(requires=['finite requested local azimuth_deg[-360,360] and elevation_deg[-90,90]','serialize angles at output0/1 before every invocation','fresh immutable pinned FFT snapshot'],angleFrame='local array only; no PS trig or global orientation transform')
   if fid=='frequency_time_weighting':
    extra_plan=compile_recorded();write_plan(output/'plans'/'frequency_time_weighting_recorded.json',extra_plan)
    entry['additionalPlan']={'file':'plans/frequency_time_weighting_recorded.json','producer':'recorded_time_response.recorded_time_response','params':{'samples':{'default':48000,'range':[1,1000000]},'contiguous':{'default':False,'requires':'capture continuity proven'}},'input':'mono sign-extended PCM24 LE32 at output+32','outputFields':['FAST_power_FS2','FAST_dBFS','SLOW_power_FS2','SLOW_dBFS','LeqFS','samples_uint32','valid','FAST_settled','SLOW_settled'],'limitation':'FAST/SLOW unweighted Z recurrence; A/C are spectral weighting only; no combined A/C FAST/SLOW producer'}
   if fid=='zoom_fft':
    prep=compile_pcm_prepare(plan['service']['metadata']['raw_samples'],plan['service']['metadata']['raw_offset'],plan['service']['output_words'])
    write_plan(output/'plans'/'zoom_prepare_PCM24.json',prep)
    entry['acquisitionPreparationPlan']={'file':'plans/zoom_prepare_PCM24.json','inputWords':prep['inputWords'],'inputWordOffset':prep['inputWordOffset'],'sequence':['initialize Zoom private allocation once','copy immutable captured PCM24 bits at stated input offset','run PCM24 preparation to DONE','reload Zoom patch code/contexts/constants WITHOUT privateClearRanges','run Zoom to DONE'],'neverClearInputBetweenStages':True}
   if fid in ('room_decay','room_clarity','spectral_decay'):
    prep=compile_pcm_prepare(plan['service']['metadata']['samples'],32,plan['service']['output_words'])
    write_plan(output/'plans'/f'{fid}_prepare_PCM24.json',prep)
    entry['acquisitionPreparationPlan']={'file':f'plans/{fid}_prepare_PCM24.json','inputWordOffset':prep['inputWordOffset'],'inputWords':prep['inputWords'],'requires':'explicit onset-trimmed measured mono IR as sign-extended PCM24; existing float32 IR skips conversion','sequence':['initialize private allocation once','copy verified onset-trimmed captured IR PCM24 bits','run PCM24 preparation to DONE','reload room patch WITHOUT privateClearRanges','run room producer to DONE'],'neverClearInputBetweenStages':True}
    if plan['service']['metadata']['ir_offset']==32:
     impulse=compile_impulse_prepare(plan['service']['metadata']['samples']);write_plan(output/'plans'/f'{fid}_prepare_impulse.json',impulse)
     entry['experimentalImpulsePreparationPlan']={'file':f'plans/{fid}_prepare_impulse.json','patchFile':impulse['patchFile'],
      'stimulusRequired':'explicit declared clap/impulse; arbitrary speech rejected','captureSamples':impulse['inputWords'],
      'inputWordOffset':impulse['inputWordOffset'],'summary':impulse['service']['metadata']['summary'],
      'thresholdFraction':0.1,'thresholdParameterPolicy':'0<threshold_fraction<=1; default0.1; nondefault requires compile_impulse_prepare(samples,threshold_fraction)',
      'readSummaryBeforeMain':True,'preserveWorkspace':True,
      'sequence':['initialize main private allocation once','copy2*n actual mono PCM24 samples at output+32','require declared impulse/clap stimulus','run impulse preparation to DONE','read onset/peak/valid summary28..31; abort unless valid','reload main code/context without private clear','run unchanged room algorithm'],
      'limitations':impulse['service']['metadata']['limitations']}
     entry['input']['captureSamples']=2*plan['service']['metadata']['samples']
     entry['input']['optionalCaptureMode']='experimental declared impulse/clap with PL approximate onset trim; otherwise explicit pretrimmed IR required'
   # Exact materialized parameter variants: a runtime may select one only when
   # every submitted parameter matches its declared compilation defaults.
   variant_args=[];signature=inspect.signature(fn).parameters
   if 'channel' in signature:
    variant_args=[{'channel':ch} for ch in range(6)]
    if fid in ('cross_correlation','gcc_phat'):variant_args=[{'channel':ch,'other':other} for ch in range(6) for other in range(6) if ch!=other]
    if fid=='noise_rating':variant_args=[{'family':family,'channel':ch} for family in ('NR','NC') for ch in range(6)]
   elif 'channel_i' in signature:variant_args=[{'channel_i':i,'channel_j':j} for i in range(6) for j in range(6) if i!=j]
   if variant_args:
    entry['variants']=[]
    for values in variant_args:
     variant=compile_feature(fid,values);suffix='_'.join(f'{k}{v}' for k,v in values.items());vpath=output/'plans'/f'{fid}_{suffix}.json';write_plan(vpath,variant)
     entry['variants'].append({'params':values,'file':vpath.relative_to(output).as_posix(),'patchFile':variant['patchFile'],'completeParams':{k:v['default'] for k,v in schema.items() if not v.get('runtimeInput')}|variant['params']})
     entry['variants'][-1]['completeParams'].update(values)
  if fid in ('fft','psd','stft','spectrum_average','peak_hold','smoothing','zoom_fft','envelope_spectrum','modulation_spectrum'):
   entry['axes']={'frequencyHz':'bin*sample_rate/2048; zoom uses producer metadata frequency convention','time':'frameId/sample cadence for histories; not reconstructed from result fetch time'}
  if fid in ('fundamental','cross_correlation','autocorrelation','gcc_phat','cepstrum'):entry['axes']={'lagSeconds':'signedIndex/sample_rate for correlations; quefrency index/sample_rate for cepstrum'}
  if fid in ('full_das','band_das','spatial_grid','spatial_peaks','directed_das'):entry['axes']={'azimuth':'deg: +X0,+Y90','elevation':'deg: +Z90','frame':'array local unless explicit valid orientation quaternion'}
  path=output/'plans'/f'{fid}.json';write_plan(path,plan)
  entry['executionPlan']={'file':path.relative_to(output).as_posix(),'kind':plan['kind'],'noCpuDSP':True}
  if 'patchFile' in plan:entry['executionPlan']['patchFile']=plan['patchFile']
  entry['mode']='events' if fid=='event_trigger' else 'p0' if fid in BUILTIN else 'staged' if fid=='stipa_experimental' else 'p1' if fid in P1 else 'p2'
  meta=entry.get('output',{}).get('metadata',{})
  entry['schema']={'kind':'scalars' if fid.startswith('levels') else 'stages' if fid=='stipa_experimental' else 'tensor',
    'encoding':entry.get('output',{}).get('encoding','LE float32 except explicit uint32 counters/IDs'),
    'fields':meta.get('fields',meta.get('output_fields',entry.get('output',{}).get('fields',[]))),
    'axes':entry.get('axes',{}),'units':UNITS.get(fid,meta.get('units','producer-defined digital units')),
    'validity':meta.get('validity',entry.get('output',{}).get('validity','requires fresh PL DONE and valid captured source; acquisition requirements must be enforced'))}
  if fid in FIELDS:entry['schema']['fields']=FIELDS[fid]
  if 'experimentalImpulsePreparationPlan' in entry:entry['schema']['limitations']=entry['experimentalImpulsePreparationPlan']['limitations']
  if not entry['schema']['axes']:
   entry['schema']['axes']={'sample':'sample_index / sampleRateHz'} if fid=='io_pcm' else {'bandHz':meta['centers_hz']} if 'centers_hz' in meta else {'index':'producer-defined field/bin/point index; see output.metadata'}
  entry['parameterPolicy']={'precompiledValuesOnly':True,'runtimeMutableParams':[],
    'nondefault':'reject unless separately compiled with compile_feature(featureId, params); no silently ignored values',
    'compileCommand':'python registry/build_plans.py --feature FEATURE --params JSON --output OUTPUT_DIRECTORY'}
  if fid=='noise_rating':entry['parameterPolicy'].update(runtimeMutableParams=['referenceConfirmed','referenceOffsetDb','calibrationSource'],runtimeMutablePolicy='serialize only confirmed1 and finite explicit referenceOffsetDb into private output30/31 after validating nonempty calibrationSource; family/channel must match compiled variant')
  if fid=='directed_das':entry['parameterPolicy'].update(runtimeMutableParams=['azimuth_deg','elevation_deg'],runtimeMutablePolicy='finite local array-frame degrees; azimuth[-360,360],elevation[-90,90]; serialize output0/1 before every invocation; other defaults immutable without reassembly')
  registry.append(entry)
 assert len(registry)==51 and len({e['featureId'] for e in registry})==51
 result={'schemaVersion':1,'features':registry,'count':51,'excluded':['srpdnn_main'],'arenaWords':ARENA_WORDS,'p2Base':BASE,'p2DescriptorTable':TABLE,'protectedP0Words':[0,P0_END],'allAssemblyOnly':True,'allHardwareAccepted':False}
 (output/'REGISTRY.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=clean),encoding='utf-8')
 print(json.dumps({'registryFeatures':len(registry),'p2Programs':len(DEFS),'stipaStages':len(stipa.graph()),'stipaWeightsMaterialized':stipa_weights,'hardwareAccepted':False}))
 return result

def compile_recorded(samples=48000,contiguous=True):
 memory=np.zeros(ARENA_WORDS,np.float32);s=recorded.install(memory,recorded.recorded_time_response(samples,FS,contiguous),base=BASE);u=memory.view(np.uint32);u[TABLE:TABLE+64]=u[BASE:BASE+64];end=s['output']+s['output_words']
 return {'kind':'p2_program','service':s,'patchRecords':records(memory,[(TABLE,64)])+sparse_records(memory,BASE,end),'privateClearRanges':[{'wordOffset':BASE,'wordCount':end-BASE}],'requiresContiguousCapturedInput':True,'contiguousParameterMustMatchCapture':True,'inputWordOffset':s['output']+32,'assemblyOnly':True}

def compile_pcm_prepare(count,offset,workspace_words):
 c,_,meta=raw_conversion.convert_pcm24(count,offset);memory=np.zeros(ARENA_WORDS,np.float32)
 s=chains.install(memory,(c,meta),base=BASE);u=memory.view(np.uint32)
 for slot in range(4):u[BASE+16*slot+8]=workspace_words
 u[TABLE:TABLE+64]=u[BASE:BASE+64]
 return {'kind':'p2_preparation','service':s,'inputWordOffset':s['output']+offset,'inputWords':count,'inputFormat':'sign-extendedPCM24 LE32','outputFormat':'normalizedfloat32 FS in place','preserveWorkspace':True,'privateClearRanges':[],
  'patchRecords':records(memory,[(TABLE,64),(BASE+128,len(c.words)*4),(BASE+4352,320)]),'assemblyOnly':True}

def compile_impulse_prepare(samples=24000,threshold_fraction=0.1):
 c,meta=producers.impulse_capture_prepare(samples,threshold_fraction,stimulus_confirmed=True)
 memory=np.zeros(ARENA_WORDS,np.float32);s=chains.install(memory,(c,meta),base=BASE);u=memory.view(np.uint32);workspace=max(16384,meta['workspace_words'])
 if s['output']+workspace>ARENA_WORDS:raise ValueError('impulse workspace outside private arena')
 for slot in range(4):u[BASE+16*slot+8]=workspace
 s['output_words']=workspace;u[TABLE:TABLE+64]=u[BASE:BASE+64]
 return {'kind':'p2_preparation','service':s,'inputWordOffset':s['output']+32,'inputWords':2*samples,'inputFormat':'sign-extendedPCM24 LE32 actual declared impulse/clap capture','outputFormat':'float32 FS onset-trimmed firstn in place','preserveWorkspace':True,'privateClearRanges':[],
  'requiresDeclaredImpulseStimulus':True,'readSummaryBeforeMain':True,
  'patchRecords':records(memory,[(TABLE,64),(BASE+128,len(c.words)*4),(BASE+4352,320)]),'assemblyOnly':True}

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=HERE);ap.add_argument('--stipa-weights',action='store_true');ap.add_argument('--feature');ap.add_argument('--params',default='{}');args=ap.parse_args()
 if args.feature:
  target=args.output/'plans'/f'{args.feature}.json';target.parent.mkdir(parents=True,exist_ok=True);write_plan(target,compile_feature(args.feature,json.loads(args.params)));print(target)
 else:build(args.output,args.stipa_weights)
