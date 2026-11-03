"""Finite captured-data STIPA graph. Host orchestrates only stages/coefficients;
PCM conversion, SOS filtering, regressions, ratios and final index execute in PL.
No automatic speech intelligibility/certified IEC claim. High VM cost is explicit.
"""
import numpy as np
from programs import Code
from raw_conversion import convert_pcm24
import stipa_offline as old
from noise_services import stipa_combine
BASE=1048576
TABLE=525312

def _append(c,tail):
 shift=len(c.words)
 for raw in tail.words:
  v=raw.copy();op=v[0]&255
  if op in (16,19):v[2]+=shift
  elif op==17:v[1]+=shift
  c.words.append(v)

def final_program(n,confirmed=False):
 # Existing ratio gate remains unchanged; its END becomes a local branch to
 # the combining gate so both valid and invalid paths publish a fresh result.
 mtf,q=old.mtf_program(n,confirmed);c=Code()
 for v in mtf.words:
  c.words.append(v.copy())
 c.words[-1]=[17, len(c.words),0,0]
 c.u(3,0);c.f(0,0);c.f(1,.5);c.history(2,3,q['result']);invalid=c.emit(19,a=2,b=1,target=0)
 for i in range(14):c.history(0,3,q['result']+2+i);c.store(0,3,16+i)
 combiner,_,_=stipa_combine(True);_append(c,combiner)
 c.words[invalid][2]=len(c.words);c.f(0,0)
 for i in range(3):c.store(0,3,i)
 c.emit(0);assert len(c.words)<=1024
 return c,q

def graph():
 stages=[dict(kind='convert_raw_PCM24'),dict(kind='validate_captures')]
 for band in range(7):
  for trace in range(2):
   stages.append(dict(kind='filter',band=band,trace=trace))
   stages.extend(dict(kind='fit',band=band,trace=trace,coefficient=i) for i in range(6))
 stages.append(dict(kind='ratios_and_index'))
 return stages

def install_graph_stage(memory,index,n=720000,confirmed=False,session=1,config=1,generation=1,base=BASE):
 q=old.layout(n)
 if base+8192+q['words']>len(memory):raise ValueError('STIPA workspace exceeds reserved arena; current default supports about16.3s')
 stages=graph()
 if index not in range(len(stages)):raise ValueError('stage')
 d=stages[index];weights=None
 if d['kind']=='convert_raw_PCM24':c,_,_=convert_pcm24(2*n,0)
 elif d['kind']=='validate_captures':c,_=old.validation_program(n,confirmed)
 elif d['kind']=='filter':c,_,_=old.filter_program(n,d['band'],d['trace'])
 elif d['kind']=='fit':c,_=old.fit_program(n,d['band'],d['trace'],d['coefficient']);weights=old.regression_weights(n,d['band'],d['coefficient'])
 else:c,_=final_program(n,confirmed)
 s=old.install_stage(memory,c,q,base=base,generation=generation);memory[base+4352:base+4672]=0;memory[s['output']-16:s['output']]=0;u=memory.view(np.uint32);prototype=u[base:base+16].copy()
 for slot in range(4):
  words=prototype.copy();words[4]=base+4352+80*slot;words[9]=512;words[11]=session;words[12]=config;words[13]=index+1;words[14]=generation
  u[base+16*slot:base+16*(slot+1)]=words
  u[TABLE+16*slot:TABLE+16*(slot+1)]=words
 if weights is not None:memory[s['output']+q['weight']:s['output']+q['weight']+n]=weights
 s.update(output_words=q['words'],slot_count=4,scheduled_descriptor=TABLE,metadata=dict(service='experimental_STIPA_graph_stage',stage=index,total_stages=len(stages),definition=d,
   samples=n,nominal_sample_rate=old.FS,input_format='two sign-extended PCM24 LE32 captured traces; first stage converts on PL',
   certified=False,final_validity='only final stage after every preceding stage DONE and confirmed reference; false for arbitrary speech',
   needs_weight_page=weights is not None,high_processing_cost=True,
   clock_limit='nominal48kHz reference; actual48009.775Hz offset0.0204% not corrected; no certified claim'))
 return s

def stage_patch(memory,s):
 """Write only these ranges AFTER prior stage done/disabled, then apply a new
 unique config with matching descriptor IDs. NEVER clear captured workspace.
 Patch format is raw uint32 records for the caller's bounded memory uploader.
 """
 u=memory.view(np.uint32);b=int(u[s['descriptor']+2])-128;code=int(u[s['descriptor']+3]);ranges=[(TABLE,64),(b+128,4*code),(b+4352,320),(s['output']-16,16)]
 if s['metadata']['needs_weight_page']:ranges.append((s['output']+3*s['metadata']['samples'],s['metadata']['samples']))
 return [(a,u[a:a+n].copy())for a,n in ranges]
