"""Peak-frequency drift on PL, using immutable scheduler frame metadata."""
import math
from programs import Code

def frequency_drift(sample_rate=48009.775390625,channel=0,first=1,count=1024):
    if not math.isfinite(sample_rate) or sample_rate<=0 or not 0<=channel<6 or first<1 or count<1 or first+count>1025:
        raise ValueError('invalid spectrum range')
    c=Code();c.u(0,first);c.u(1,channel*8192+4098+3*first);c.u(3,0)
    c.f(0,0);c.f(1,0);c.f(2,sample_rate/2048);c.f(3,0);c.f(4,1);c.f(5,.5)
    start=len(c.words);c.load(6)
    update=c.emit(19,a=0,b=6,target=0);skip=c.emit(17,imm=0)
    c.words[update][2]=len(c.words);c.emit(4,0,6,3);c.emit(18,1,0);c.emit(6,1,1,2)
    c.words[skip][1]=len(c.words);c.addi(0,0,1);c.addi(1,1,3);c.loop(0,first+count,start)
    c.store(1,3,0);c.store(3,3,1);c.store(3,3,2);c.store(3,3,3)
    c.f(12,1e-20);silent=c.emit(19,a=0,b=12,target=0)
    c.emit(26,7,imm=0);c.history(7,3,5)
    initial=c.emit(19,a=7,b=5,target=0)
    c.emit(20,8,3,imm=6,target=2);c.emit(24,9,7,8);c.emit(18,8,9)
    c.f(9,2048/sample_rate);c.emit(6,8,8,9);c.history(10,3,4);c.emit(5,10,1,10)
    c.emit(7,11,10,8);c.store(10,3,1);c.store(11,3,2);c.store(4,3,3)
    c.words[initial][2]=len(c.words)
    c.store(1,3,4);c.store(4,3,5);c.emit(21,7,3,imm=6,target=1);finish=c.emit(17,imm=0)
    c.words[silent][2]=len(c.words);c.store(3,3,4);c.store(3,3,5)
    c.words[finish][1]=len(c.words);c.emit(0)
    return c,7,dict(service='peak_frequency_drift',fields=['peak_hz','delta_hz','drift_hz_per_second','drift_valid','history_hz','initialized','frame_uint'],
        bin_resolution_hz=sample_rate/2048,scope='dominant mixed-signal FFT peak, not source tracking',
        lifetime='reset history on channel/config change; scheduler must supply distinct monotonic frame IDs')
