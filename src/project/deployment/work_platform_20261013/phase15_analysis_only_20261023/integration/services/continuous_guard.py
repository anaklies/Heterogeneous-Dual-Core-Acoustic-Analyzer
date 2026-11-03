"""Continuity-safe time response, retaining the tested numeric recurrence.
No missing raw frame is silently treated as consecutive audio.
"""
from programs import Code
from noise_services import time_response

def checked_time_response(sample_rate,response='FAST',channel=0):
 body,_,meta=time_response(sample_rate,response,channel,2048)
 c=Code();c.u(3,0);c.f(30,0);c.f(31,0);c.f(29,.5);c.history(28,3,8);c.emit(26,7,imm=0)
 first=c.emit(19,a=28,b=29,target=0);c.emit(20,8,3,imm=6,target=2);c.emit(24,9,7,8)
 fresh=c.emit(16,a=9,imm=1,target=0);normal=c.emit(16,a=9,imm=2,target=0)
 c.words[first][2]=len(c.words);c.f(30,1)
 for offset in (0,2,4):c.store(31,3,offset)
 c.words[normal][2]=len(c.words);offset=len(c.words)
 for raw in body.words[:-1]:
  v=raw.copy();op=v[0]&255
  if op in (16,19):v[2]+=offset
  elif op==17:v[1]+=offset
  c.words.append(v)
 c.emit(21,7,3,imm=6,target=1);c.f(28,1);c.store(28,3,8)
 gap=c.emit(19,a=29,b=30,target=0);leave=c.emit(17,imm=0)
 c.words[gap][2]=len(c.words);c.words[fresh][2]=len(c.words);c.store(31,3,7);c.words[leave][1]=len(c.words);c.emit(0)
 return c,9,dict(meta,service=response+'_continuity_checked',frame_id_uint_offset=6,history_marker_offset=8,
  gap_behavior='clear recurrence and cumulative history; first/gapped/duplicate frame valid=0; next contiguous frame valid=1; startup settling remains explicit',
  deployment='requires every pinned raw frame in order, otherwise exposes invalid/reset rather than fictitious time response')
