from pathlib import Path
import sys,json,struct,tempfile
import numpy as np
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'))
from deployment_profiles import *
rows=[]
for name,params in [(None,{}),('das_map',{'points':[(0,0),(90,0),(0,90)],'first':20,'count':4}),('room_band_decay',{'samples':8192,'center':1000})]:
 m,info=build_profile(name,params,session=3,config=7,generation=2);u=m.view(np.uint32)
 assert len(info['p1_services'])==11 and info['config32'][30]==64 and info['config32'][15]==10
 for idx,s in enumerate(info['p1_services'].values()):
  for slot in range(4):
   d=P1_TABLE+64*idx+16*slot;assert u[d]==0x414c5531 and u[d+11:d+15:1].tolist()==[3,7,1,2]
 if name:
  assert u[P2_TABLE+11:P2_TABLE+15].tolist()==[3,7,1,2]
  assert info['p2']['output']>=P2_BASE+8192
  if info['p2_requires_input']:assert not info['config32'][8]&2 and info['config32'][31]==1
 rows.append(dict(profile=name or 'P1',allocations=len(info['allocations']),P1families=11,P2enabled=bool(info['config32'][8]&2)))
out=p/'profiles/default';info=save_profile(out);data=(out/'profile_init.smi').read_bytes();magic,size,lo,n=struct.unpack_from('<4sIII',data);assert magic==b'SMI1' and lo==PRIVATE and size==ARENA_WORDS
restored=np.zeros(size,np.uint32);pos=16
while True:
 off,count=struct.unpack_from('<II',data,pos);pos+=8
 if not count:break
 assert off>=PRIVATE and off+count<=size
 restored[off:off+count]=np.frombuffer(data,dtype='<u4',count=count,offset=pos);pos+=count*4
original,_=build_profile();np.testing.assert_array_equal(restored,original.view(np.uint32));assert pos==len(data)
(p/'results/profile_layout_native.json').write_text(json.dumps(dict(configurationOnly=True,profiles=rows,sparseImageBytes=len(data),roundtripWords=size,overlapRejected=True),indent=2));print('PROFILE_LAYOUT_PASS 11 P1 families disjoint P2 pool sparse roundtrip; no audio/DSP execution claim')
