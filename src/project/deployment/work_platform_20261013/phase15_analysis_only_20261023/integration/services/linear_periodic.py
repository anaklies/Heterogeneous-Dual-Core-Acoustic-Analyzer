"""Zero-padded linear 1024-sample correlations through the shared 2048 FFT.
The first half of a pinned 2048-sample raw block is used; no Hann window.
No host filtering/correlation or generated signal enters deployed inference.
"""
import math
from programs import Code
from p2_chains import install as _install
N=1024

def _forward(c,channel):
 c.u(0,channel*2048);c.u(1,0);c.f(20,0);c.f(21,0);c.f(22,1/8388608);c.f(23,N)
 loop=len(c.words);c.emit(20,9,0,target=1);c.emit(22,0,9);c.emit(6,0,0,22);c.emit(4,21,21,0)
 c.addi(0,0,1);c.addi(1,1,1);c.loop(1,N,loop);c.emit(7,21,21,23)
 c.u(0,channel*2048);c.u(1,0);c.u(2,4096)
 loop=len(c.words);c.emit(20,9,0,target=1);c.emit(22,0,9);c.emit(6,0,0,22);c.emit(5,0,0,21);c.store(0,2);c.store(20,2,1)
 c.addi(0,0,1);c.addi(1,1,1);c.addi(2,2,2);c.loop(1,N,loop)
 loop=len(c.words);c.store(20,2);c.store(20,2,1);c.addi(1,1,1);c.addi(2,2,2);c.loop(1,2048,loop);c.emit(23,imm=1)

def linear_correlation(channel=0,other=None,phat=False):
 if not 0<=channel<6 or (other is not None and not 0<=other<6):raise ValueError('channel')
 c=Code();_forward(c,channel)
 if other is not None:
  c.u(0,0);c.u(1,8192);c.u(2,12288);loop=len(c.words);c.history(0,1);c.store(0,2)
  c.addi(0,0,1);c.addi(1,1,1);c.addi(2,2,1);c.loop(0,4096,loop);_forward(c,other)
 c.u(0,0);c.u(1,12288 if other is not None else 8192);c.u(2,8192);c.u(3,4096);c.f(20,0);c.f(21,1e-20)
 loop=len(c.words);c.history(0,1);c.history(1,1,1);c.history(2,2);c.history(3,2,1)
 c.emit(6,4,0,2);c.emit(6,5,1,3);c.emit(4,4,4,5);c.emit(6,5,1,2);c.emit(6,6,0,3);c.emit(5,5,5,6)
 if phat:
  c.emit(6,6,4,4);c.emit(6,7,5,5);c.emit(4,6,6,7);c.emit(8,6,6);c.emit(12,6,6,21);c.emit(7,4,4,6);c.emit(7,5,5,6)
 c.store(4,3);c.store(5,3,1)
 for r,step in ((0,1),(1,2),(2,2),(3,2)):c.addi(r,r,step)
 c.loop(0,2048,loop);c.emit(23,imm=2);c.u(0,0);c.u(1,8192)
 loop=len(c.words);c.history(0,1);c.store(0,0);c.addi(0,0,1);c.addi(1,1,2);c.loop(0,2048,loop);c.emit(0)
 return c,dict(service='raw_linear_gcc_phat' if phat else 'raw_linear_correlation',output_count=2048,raw_input=True,
  samples=N,window='demeaned rectangular 1024, zero padded to2048',units='relative PHAT' if phat else 'FS squared sum',
  lag='positive lag: first channel delayed versus second; index>1024 maps to index-2048')

def fundamental(sample_rate=48009.775390625,channel=0,low=100,high=2000):
 if not math.isfinite(sample_rate) or not 0<low<high<sample_rate/2:raise ValueError('frequency range')
 first=max(2,math.ceil(sample_rate/high));last=min(N//2,math.floor(sample_rate/low))
 if first>=last:raise ValueError('period outside available support')
 c,meta=linear_correlation(channel);c.words.pop();c.u(0,first);c.u(3,0);c.u(7,first);c.u(10,1);c.f(0,0);c.f(20,0);c.f(21,1e-20)
 loop=len(c.words);c.history(1,0);c.emit(24,8,0,10);c.history(10,8);c.addi(8,0,1);c.history(11,8)
 reject_peaks=[c.emit(19,a=1,b=10,target=0),c.emit(19,a=1,b=11,target=0)]
 take=c.emit(19,a=0,b=1,target=0);skip=c.emit(17,imm=0)
 c.words[take][2]=len(c.words);c.emit(4,0,1,20);c.emit(15,7,0,imm=0);c.words[skip][1]=len(c.words)
 for j in reject_peaks:c.words[j][2]=len(c.words)
 c.addi(0,0,1);c.loop(0,last+1,loop)
 c.history(1,3,0);c.emit(12,1,1,21);c.emit(7,2,0,1);c.store(20,3,2050);c.store(2,3,2049)
 c.f(3,.2);invalid=c.emit(19,a=2,b=3,target=0)
 c.u(8,1);c.emit(24,8,7,8);c.history(3,8);c.addi(8,7,1);c.history(4,8)
 c.f(5,2);c.emit(6,5,0,5);c.emit(4,6,3,4);c.emit(5,6,6,5);c.f(9,-1e-20)
 nofit=c.emit(19,a=9,b=6,target=0)
 c.emit(5,5,3,4);c.f(8,.5);c.emit(6,5,5,8);c.emit(7,5,5,6);c.f(8,-.5);c.emit(12,5,5,8);c.f(8,.5);c.emit(11,5,5,8)
 finish=c.emit(17,imm=0);c.words[nofit][2]=len(c.words);c.f(5,0);c.words[finish][1]=len(c.words)
 c.emit(18,7,7);c.emit(4,7,7,5);c.f(8,sample_rate);c.emit(7,7,8,7);c.store(7,3,2048);c.f(8,1);c.store(8,3,2050);skipend=c.emit(17,imm=0)
 c.words[invalid][2]=len(c.words);c.store(20,3,2048);c.words[skipend][1]=len(c.words);c.emit(0)
 return c,dict(meta,service='linear_autocorrelation_fundamental',output_count=2051,fields_tail=['fundamental_hz','period_strength','valid'],
  scope='dominant periodic mixture, not separated sources; configurable100-2000Hz default')

def install(memory,specification,**kwargs):
 s=_install(memory,specification,**kwargs);u=memory.view('uint32')
 for slot in range(4):u[s['descriptor']+16*slot+5:s['descriptor']+16*slot+7]=[slot*16384,12288]
 return s
