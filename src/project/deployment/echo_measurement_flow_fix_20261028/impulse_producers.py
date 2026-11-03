"""Bounded PL transient detector: concentrated block energy, not one sample."""
import math
from programs import Code
def impulse_capture_prepare(samples,threshold_fraction=.1,stimulus_confirmed=False):
 from raw_conversion import convert_pcm24
 if not 32<=samples<=60000:raise ValueError('samples')
 block=min(96,samples)
 while samples%block:block-=1
 c,_,_=convert_pcm24(2*samples,32);c.words.pop();c.u(3,0);c.f(0,0)
 for off in range(28,32):c.store(0,3,off)
 if stimulus_confirmed:
  c.u(0,0);c.u(6,0);c.u(7,0);c.u(5,0);c.u(8,0)
  for r in [1,5,7,8,9,10]:c.f(r,0)
  begin=len(c.words);c.history(0,0,32);c.emit(13,0,0);c.emit(6,6,0,0);c.emit(4,7,7,6);c.emit(12,8,8,0)
  c.addi(0,0,1);c.addi(6,6,1);c.loop(6,block,begin)
  c.emit(6,11,8,8);c.f(2,6);c.emit(6,11,11,2)
  broad=c.emit(19,a=11,b=7,target=0);reject_block=c.emit(17,imm=0);c.words[broad][2]=len(c.words);c.emit(4,5,5,7);c.addi(8,8,1)
  update=c.emit(19,a=9,b=7,target=0);skip=c.emit(17,imm=0)
  c.words[update][2]=len(c.words);c.emit(4,9,7,10);c.emit(4,1,8,10);c.addi(5,7,0)
  c.words[skip][1]=len(c.words);c.words[reject_block][1]=len(c.words);c.f(7,0);c.f(8,0);c.u(6,0);c.addi(7,0,0);c.loop(0,samples,begin)
  c.store(1,3,29)
  c.f(2,1e-4);above=c.emit(19,a=2,b=1,target=0);c.emit(0);c.words[above][2]=len(c.words)
  c.emit(18,6,8);c.f(2,8);c.emit(7,6,2,6);c.emit(6,6,6,5);strong=c.emit(19,a=6,b=9,target=0);c.emit(0);c.words[strong][2]=len(c.words)
  c.emit(6,6,1,1);c.f(2,6);c.emit(6,6,6,2);wide=c.emit(19,a=6,b=9,target=0);c.emit(0);c.words[wide][2]=len(c.words)
  zero=c.emit(16,a=5,imm=block//2,target=0);c.u(2,block//2);c.emit(24,5,5,2);skip=c.emit(17,imm=0);c.words[zero][2]=len(c.words);c.u(5,0);c.words[skip][1]=len(c.words)
  c.emit(21,5,3,imm=28,target=1);c.store(9,3,31)
  c.u(0,0);c.addi(1,5,32);begin=len(c.words);c.history(0,1);c.store(0,0,32);c.addi(0,0,1);c.addi(1,1,1);c.loop(0,samples,begin)
  c.f(0,1);c.store(0,3,30)
 c.emit(0)
 return c,dict(service='experimental_impulsive_room_capture_prepare',samples=samples,capture_samples=2*samples,workspace_words=32+2*samples,input_offset=32,input_format='sign-extended PCM24 LE32',output_format='onset-aligned float32 FS',threshold_fraction=threshold_fraction,stimulus_confirmed=stimulus_confirmed,block_samples=block,summary={'onset_index_uint32':28,'peak_FS':29,'valid':30,'block_energy_FS2':31},onsetPolicy='strongest energy block, half-block preroll',validity='declared excitation; block energy exceeds 8x mean eligible block energy and 6x peak squared; peak>1e-4',limitations=['Transient evidence, not sound class recognition','No RIR deconvolution or certification','A sufficiently concentrated unrelated sound can still qualify; decay must pass independent checks'])
