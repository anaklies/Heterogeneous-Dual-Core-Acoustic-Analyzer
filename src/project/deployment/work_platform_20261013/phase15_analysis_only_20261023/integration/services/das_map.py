"""User-requested bounded DAS power maps; no autonomous source detector.
Raw az/el configuration is converted to directions and beam weights by PL.
Map peaks are visualization aids, not verified source count or automatic DOA.
"""
import math
import numpy as np
from programs import Code
from manual_das import manual_das
from p2_chains import install as _install

def sphere_grid(azimuth_step=30,elevation_step=30):
 if azimuth_step not in (10,15,20,30,45,60,90) or elevation_step not in (10,15,30,45):raise ValueError('bounded angle steps')
 points=[(a,e) for e in range(-90+elevation_step,90,elevation_step) for a in range(0,360,azimuth_step)]
 return [(0,-90),*points,(0,90)]

def power_map(points=None,sample_rate=48009.775390625,sound_speed=343.42,first=1,count=85,max_peaks=3,separation_deg=30):
 points=sphere_grid() if points is None else list(points)
 if not 1<=len(points)<=614 or not 0<=max_peaks<=3 or not 0<separation_deg<=180:raise ValueError('grid/peaks bounds')
 if any(not math.isfinite(a) or not math.isfinite(e) or not -360<=a<=360 or not -90<=e<=90 for a,e in points):raise ValueError('angles')
 n=len(points);body,_,meta=manual_das(sample_rate=sample_rate,sound_speed=sound_speed,first=first,count=count,_angle_register=21)
 c=Code();c.u(20,0);c.u(21,4096);c.u(23,6144);begin=len(c.words);offset=len(c.words)
 for raw in body.words[:-1]:
  v=raw.copy();op=v[0]&255
  if op in (16,19):v[2]+=offset
  elif op==17:v[1]+=offset
  c.words.append(v)
 c.f(30,sample_rate/2048);c.f(31,0);c.u(0,0);c.u(1,2);loop=len(c.words)
 c.history(0,1);c.emit(6,0,0,30);c.emit(4,31,31,0);c.addi(0,0,1);c.addi(1,1,3);c.loop(0,count,loop)
 c.store(31,20,8192);c.store(31,20,9216)
 for j in range(3):c.store(17+j,23,j)
 c.addi(20,20,1);c.addi(21,21,2);c.addi(23,23,3);c.loop(20,n,begin)
 if max_peaks:
  c.u(20,0);c.u(23,10240);rankstart=len(c.words);c.u(21,0);c.u(22,0);c.u(25,6144);c.f(20,0);c.f(30,0);c.f(26,math.cos(math.radians(separation_deg)));c.f(24,1e-20)
  loop=len(c.words);c.history(0,21,9216);take=c.emit(19,a=30,b=0,target=0);skip=c.emit(17,imm=0)
  c.words[take][2]=len(c.words);c.emit(4,30,0,20);c.addi(22,21,0)
  for j in range(3):c.history(27+j,25,j)
  c.words[skip][1]=len(c.words);c.addi(21,21,1);c.addi(25,25,3);c.loop(21,n,loop)
  c.emit(21,22,23,target=1);c.store(30,23,1);c.store(20,23,2);valid=c.emit(19,a=24,b=30,target=0);skip=c.emit(17,imm=0)
  c.words[valid][2]=len(c.words);c.f(0,1);c.store(0,23,2);c.words[skip][1]=len(c.words)
  c.u(21,0);c.u(25,6144);loop=len(c.words);c.f(5,0)
  for j in range(3):c.history(0,25,j);c.emit(6,0,0,27+j);c.emit(4,5,5,0)
  remove=c.emit(19,a=26,b=5,target=0);skip=c.emit(17,imm=0);c.words[remove][2]=len(c.words);c.store(20,21,9216);c.words[skip][1]=len(c.words)
  c.addi(21,21,1);c.addi(25,25,3);c.loop(21,n,loop);c.addi(20,20,1);c.addi(23,23,3);c.loop(20,max_peaks,rankstart)
 c.emit(0);assert len(c.words)<=1024
 return c,dict(service='manual_DAS_power_map',points=points,output_count=10240+3*max_peaks,angle_config_offset=4096,vector_offset=6144,power_offset=8192,peak_offset=10240,
  units='relative FS squared in selected frequency band',first_bin=first,bins=count,max_peaks=max_peaks,separation_deg=separation_deg,
  automatic_doa=False,source_count=False,refresh='P2 asynchronous; one immutable captured window for whole map',math=meta)

def install(memory,specification,**kwargs):
 spec=_install(memory,specification,**kwargs);cfg=spec['output']+4096;angles=np.asarray(spec['metadata']['points'],np.float32).ravel();memory[cfg:cfg+len(angles)]=angles
 return spec
