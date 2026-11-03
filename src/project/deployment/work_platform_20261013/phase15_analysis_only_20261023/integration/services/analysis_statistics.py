"""PL Welch accumulation and relative spectrum comparison; no host signal math."""
from programs import Code,_start,_step

def welch(channel=0,count=1025):
 c=_start(channel,0,count,1);c.emit(20,4,3,imm=0,target=2);c.addi(4,4,1);c.emit(21,4,3,imm=0,target=1);c.emit(18,31,4);c.u(5,1)
 loop=len(c.words);c.load(0);c.history(1,5);c.emit(5,2,0,1);c.emit(7,2,2,31);c.emit(4,1,1,2);c.store(1,5)
 c.addi(0,0,1);c.addi(1,1,3);c.addi(5,5,1);c.loop(0,count,loop);c.emit(0)
 return c,count+1,dict(service='welch_cumulative',units='FS squared/Hz',history='uint32 distinct frame count plus cumulative mean PSD',window='2048 Hann, nonoverlapping retained frames',scope='selected channel; periodic P1, not six-channel per-hop guarantee')

def compare(count=1025,threshold=0.01):
 if not 1<=count<=1025 or threshold<0:raise ValueError('invalid comparison')
 c=Code();c.u(0,0);c.u(1,0);c.u(2,count);c.u(3,2*count);c.f(3,threshold);c.f(4,0);c.f(5,1)
 loop=len(c.words);c.load(0,1);c.load(1,2);c.emit(5,0,0,1);c.store(0,0);c.emit(13,1,0);c.store(4,3)
 alarm=c.emit(19,a=3,b=1,target=0);skip=c.emit(17,imm=0);c.words[alarm][2]=len(c.words);c.store(5,3);c.words[skip][1]=len(c.words)
 for reg in range(4):c.addi(reg,reg,1)
 c.loop(0,count,loop);c.emit(0)
 return c,3*count,dict(service='relative_spectrum_AB_limit',input='private read region [current,reference] spectra in FS2/bin',outputs='signed delta followed by unused middle and absolute-change threshold flags',units='FS squared/bin',calibrated=False)
