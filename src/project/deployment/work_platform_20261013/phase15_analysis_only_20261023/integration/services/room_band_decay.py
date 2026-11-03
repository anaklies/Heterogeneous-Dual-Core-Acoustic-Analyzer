"""Per-band PL room decay: SOS filtering + existing Schroeder/fit chain.
Input is an explicit onset-trimmed copied IR, never an arbitrary live mixture.
Each band starts from an unmodified copy of that same IR. Not IEC certified.
"""
import math
from scipy import signal
from programs import Code
from room_services import room_ir

def band_decay(samples,sample_rate=48000,center=1000,fraction=1):
 if fraction not in (1,3) or not math.isfinite(center) or center<=0:raise ValueError('band')
 lo=center*2**(-1/(2*fraction));hi=center*2**(1/(2*fraction))
 if hi>=sample_rate/2:raise ValueError('band exceeds Nyquist')
 tail,size,meta=room_ir(samples,sample_rate);sos=signal.butter(4,[lo,hi],fs=sample_rate,btype='bandpass',output='sos')
 c=Code();c.u(0,meta['ir_offset']);c.u(1,0);c.f(31,0)
 for r in range(2,10):c.f(r,0)
 loop=len(c.words);c.history(0,0)
 for i,(b0,b1,b2,a0,a1,a2) in enumerate(sos):
  for r,v in zip(range(20,25),(b0,b1,b2,a1,a2)):c.f(r,v)
  z1,z2=2+2*i,3+2*i;c.emit(6,1,0,20);c.emit(4,1,1,z1)
  c.emit(6,z1,0,21);c.emit(6,25,1,23);c.emit(5,z1,z1,25);c.emit(4,z1,z1,z2)
  c.emit(6,z2,0,22);c.emit(6,25,1,24);c.emit(5,z2,z2,25);c.emit(4,0,1,31)
 c.store(0,0);c.addi(0,0,1);c.addi(1,1,1);c.loop(1,samples,loop)
 offset=len(c.words)
 for raw in tail.words:
  v=raw.copy();op=v[0]&255
  if op in (16,19):v[2]+=offset
  elif op==17:v[1]+=offset
  c.words.append(v)
 assert len(c.words)<=1024
 meta=dict(meta,service='filtered_room_decay',center_hz=center,fraction=fraction,sos=sos.tolist(),
           exclusions=['automatic onset/RIR extraction','stationary-noise correction','certified room measurement'])
 return c,size,meta
