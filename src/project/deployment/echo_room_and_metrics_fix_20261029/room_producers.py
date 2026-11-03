"""PL transient capture: wide trigger window and local onset; no PS DSP."""
import math
from programs import Code
def impulse_capture_prepare(samples,threshold_fraction=.05,stimulus_confirmed=False):
 from raw_conversion import convert_pcm24
 if not 32<=samples<=60000:raise ValueError('samples')
 search=2*samples;capture=3*samples;block=min(96,samples)
 while search%block:block-=1
 c,_,_=convert_pcm24(capture,32);c.words.pop();c.u(3,0);c.f(27,0)
 c.emit(20,24,3,imm=30,target=2);bad=c.emit(16,a=24,imm=0x4e4f4953,target=0);yes=c.emit(16,a=24,imm=0x4e4f4954,target=0);skip=c.emit(17,imm=0);c.words[yes][2]=len(c.words);c.history(27,3,29);c.words[bad][2]=len(c.words);c.words[skip][1]=len(c.words)
 c.f(0,0)
 for off in range(28,32):c.store(0,3,off)
 if stimulus_confirmed:
  c.u(0,0);c.u(6,0);c.u(7,0);c.u(5,0)
  for r in [1,5,7,8,9,10]:c.f(r,0)
  begin=len(c.words);c.history(0,0,32);c.emit(13,0,0);c.emit(6,6,0,0);c.emit(4,5,5,6);c.emit(4,7,7,6);c.emit(12,8,8,0)
  c.addi(0,0,1);c.addi(6,6,1);c.loop(6,block,begin)
  better=c.emit(19,a=9,b=7,target=0);skip=c.emit(17,imm=0);c.words[better][2]=len(c.words);c.emit(4,9,7,10);c.emit(4,1,8,10);c.addi(5,7,0);c.words[skip][1]=len(c.words)
  c.f(7,0);c.f(8,0);c.u(6,0);c.addi(7,0,0);c.loop(0,search,begin);c.store(1,3,29)
  c.f(2,1e-4);ok=c.emit(19,a=2,b=1,target=0);c.emit(0);c.words[ok][2]=len(c.words)
  c.f(6,8.0*block/search);c.emit(6,6,6,5);ok=c.emit(19,a=6,b=9,target=0);c.emit(0);c.words[ok][2]=len(c.words)
  c.f(4,threshold_fraction);c.emit(6,4,4,1);c.f(6,6);c.emit(6,6,6,27);c.emit(12,4,4,6);c.store(4,3,31)
  early=c.emit(16,a=5,imm=2*block,target=0);c.u(2,2*block);c.emit(24,5,5,2);skip=c.emit(17,imm=0);c.words[early][2]=len(c.words);c.u(5,0);c.words[skip][1]=len(c.words)
  c.u(0,0);c.addi(1,5,32);begin=len(c.words);c.history(0,1);c.emit(13,0,0);found=c.emit(19,a=4,b=0,target=0);c.addi(0,0,1);c.addi(1,1,1);c.loop(0,3*block,begin);c.emit(0);c.words[found][2]=len(c.words)
  c.u(2,32);c.emit(24,5,1,2);c.emit(21,5,3,imm=28,target=1)
  c.u(0,0);c.addi(1,5,32);begin=len(c.words);c.history(0,1);c.store(0,0,32);c.addi(0,0,1);c.addi(1,1,1);c.loop(0,samples,begin);c.f(0,1);c.store(0,3,30)
 c.emit(0)
 return c,dict(service='experimental_impulsive_room_capture_prepare',samples=samples,capture_samples=capture,search_samples=search,workspace_words=32+capture,input_offset=32,input_format='sign-extended PCM24 LE32',output_format='locally onset-aligned float32 FS',threshold_fraction=threshold_fraction,summary={'onset_index_uint32':28,'peak_FS':29,'valid':30,'threshold_FS':31},onsetPolicy='strongest energy block then first local crossing within 4ms preroll',validity='declared impulse; energy concentration; clean input selection; not sound-class recognition')
