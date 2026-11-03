"""3-band rapid modulation-transfer estimate. All sample math runs on PL ISA.
No changes to full 101-stage STIPA. Not a seven-band STIPA estimator.
"""
from pathlib import Path
import sys,math,json,hashlib,struct,copy
import numpy as np
from scipy import signal
R=Path(__file__).resolve().parent;ROOT=R.parents[1];S=ROOT/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/services';sys.path.insert(0,str(S))
from programs import Code
import stipa_offline as old
from raw_conversion import convert_pcm24
N=144000;DEC=240;BANDS=(2,3,4);BASE=1048576;TABLE=525312;OUT=BASE+8192;ARENA=4194304

def graph():
 a=[{'kind':'convert_raw_PCM24'},{'kind':'validate_captures'}]
 for band in BANDS:
  for trace in (0,1):a.extend([{'kind':'quick_filter','band':band,'trace':trace},{'kind':'joint_fit','band':band,'trace':trace}])
 return a+[{'kind':'quick_index'}]

def validation(n=N):
 q=old.layout(n);c=Code();c.u(0,0);c.u(3,0);c.f(0,0);c.f(2,1);c.store(0,3,q['result']+31)
 begin=len(c.words);c.history(1,0);c.emit(13,1,1);ok=c.emit(19,a=1,b=2,target=0);end=c.emit(17,imm=0);c.words[ok][2]=len(c.words);c.addi(0,0,1);c.loop(0,2*n,begin);c.store(2,3,q['result']+31);c.words[end][1]=len(c.words);c.emit(0);return c

def filt(band,trace,n=N):
 q=old.layout(n);sos=signal.butter(2,[old.CENTERS[band]/math.sqrt(2),old.CENTERS[band]*math.sqrt(2)],fs=old.FS,btype='bandpass',output='sos');lp=signal.butter(2,40,fs=old.FS,output='sos');sections=np.vstack((sos,lp))
 c=Code();c.u(0,trace*n);c.u(1,2*n);c.u(2,0);c.u(3,0);c.u(4,0)
 for r in range(2,10):c.f(r,0)
 c.f(30,0);c.f(31,0);start=len(c.words);c.history(0,0)
 for s,row in enumerate(sections):
  if s==len(sos):
   c.emit(6,0,0,0);lo=c.emit(16,a=2,imm=14400,target=0);hi=c.emit(16,a=2,imm=n-14400,target=0);skip=c.emit(17,imm=0);c.words[hi][2]=len(c.words);c.emit(4,30,30,0);c.words[lo][2]=len(c.words);c.words[skip][1]=len(c.words)
  b0,b1,b2,a0,a1,a2=row
  for reg,val in zip(range(24,29),[b0,b1,b2,a1,a2]):c.f(reg,val)
  z1,z2=2+2*s,3+2*s;c.emit(6,1,0,24);c.emit(4,1,1,z1);c.emit(6,z1,0,25);c.emit(6,29,1,27);c.emit(5,z1,z1,29);c.emit(4,z1,z1,z2);c.emit(6,z2,0,26);c.emit(6,29,1,28);c.emit(5,z2,z2,29);c.emit(4,0,1,31)
 c.emit(4,9,9,0);c.addi(4,4,1);skip=c.emit(16,a=4,imm=DEC,target=0);c.f(1,DEC);c.emit(7,9,9,1);c.store(9,1);c.addi(1,1,1);c.u(4,0);c.f(9,0);c.words[skip][2]=len(c.words)
 c.addi(0,0,1);c.addi(2,2,1);c.loop(2,n,start);c.f(1,n-28800);c.emit(7,30,30,1);c.store(30,3,q['result']+32+2*band+trace);c.emit(0);return c,sections

def weights(band,n=N):
 m=n//DEC;t=(np.arange(m)+.5)*DEC/old.FS;ix=np.arange(60,m-60);tt=t[ix];X=np.column_stack([np.ones(len(ix)),tt-tt.mean(),*[v for f in old.PAIRS[band] for v in (np.sin(2*np.pi*f*tt),np.cos(2*np.pi*f*tt))]])
 assert np.linalg.matrix_rank(X)==6 and np.linalg.cond(X)<10000
 w=np.zeros((6,m),np.float32);w[:,ix]=np.linalg.pinv(X).astype(np.float32);return w

def joint(band,trace,n=N):
 q=old.layout(n);m=n//DEC;c=Code();c.u(0,2*n);c.u(1,3*n);c.u(2,0);c.u(3,0);c.f(31,0)
 for r in range(10,22):c.f(r,0)
 start=len(c.words);c.history(0,0)
 for k in range(6):
  c.history(1,1,k*m);c.emit(6,2,0,1);c.emit(5,2,2,16+k);c.emit(4,3,10+k,2);c.emit(5,16+k,3,10+k);c.emit(5,16+k,16+k,2);c.emit(4,10+k,3,31)
 c.addi(0,0,1);c.addi(1,1,1);c.addi(2,2,1);c.loop(2,m,start)
 for k in range(6):c.store(10+k,3,q['result']+48+trace*42+band*6+k)
 c.emit(0);return c

def final(n=N):
 q=old.layout(n);c=Code();c.u(3,0);c.f(0,0);c.f(1,1)
 for j in range(3):c.store(0,3,j)
 exits=[]
 def require_positive(reg,threshold=0):
  c.f(29,threshold);ok=c.emit(19,a=29,b=reg,target=0);exits.append(c.emit(17,imm=0));c.words[ok][2]=len(c.words)
 c.history(6,3,q['result']+31);require_positive(6,.5);c.f(25,0)
 for band,alpha in zip(BANDS,[.230,.233,.309]):
  for tr in (0,1):c.history(6,3,q['result']+32+2*band+tr);require_positive(6,1e-18)
  for j in (0,1):
   for tr in (0,1):
    a=q['result']+48+tr*42+band*6;c.history(6,3,a);require_positive(6);c.history(7,3,a+2+2*j);c.history(8,3,a+3+2*j);c.emit(6,7,7,7);c.emit(6,8,8,8);c.emit(4,7,7,8);c.emit(8,7,7);c.emit(7,20+tr,7,6)
   require_positive(20,.15);c.emit(7,10,21,20);c.f(29,1.3);exits.append(c.emit(19,a=29,b=10,target=0))
   c.f(2,1e-6);c.f(4,1-1e-6);c.emit(12,10,10,2);c.emit(11,10,10,4);c.emit(5,11,1,10);c.emit(7,10,10,11);c.emit(9,10,10);c.f(5,10/math.log(10));c.emit(6,10,10,5);c.f(6,-15);c.f(7,15);c.emit(12,10,10,6);c.emit(11,10,10,7);c.emit(4,10,10,7);c.f(8,alpha/(2*sum([.230,.233,.309])*30));c.emit(6,10,10,8);c.emit(4,25,25,10)
 c.store(25,3,0);c.store(1,3,1);end=len(c.words);c.emit(0)
 for k in exits:
  if c.words[k][0]&255==17:c.words[k][1]=end
  else:c.words[k][2]=end
 return c

def build():
 reg=R/'registry';(reg/'plans').mkdir(parents=True,exist_ok=True);q=old.layout(N);stages=[];lengths=[]
 for i,d in enumerate(graph()):
  weight=None
  if d['kind']=='convert_raw_PCM24':c,_,_=convert_pcm24(2*N,0)
  elif d['kind']=='validate_captures':c=validation()
  elif d['kind']=='quick_filter':c,_=filt(d['band'],d['trace'])
  elif d['kind']=='joint_fit':c=joint(d['band'],d['trace']);weight=weights(d['band']).ravel()
  else:c=final()
  assert len(c.words)<=1024
  m=np.zeros(ARENA,np.float32);service=old.install_stage(m,c,q,base=BASE);u=m.view(np.uint32);proto=u[BASE:BASE+16].copy()
  for slot in range(4):
   v=proto.copy();v[4]=BASE+4352+80*slot;v[9]=512;v[13]=i+1;u[TABLE+16*slot:TABLE+16*(slot+1)]=v
  ranges=[(TABLE,64),(BASE+128,4*len(c.words)),(BASE+4352,320),(OUT-16,16)];records=[{'wordOffset':a,'wordCount':b,'words':u[a:a+b].tolist()} for a,b in ranges]
  patch=b''.join(struct.pack('<II',a,b)+u[a:a+b].astype('<u4').tobytes() for a,b in ranges)+struct.pack('<II',0,0)
  name=f'stipa_quick_stage_{i:03}';(reg/'plans'/f'{name}.smp').write_bytes(patch)
  plan={'stage':i,'definition':d,'scheduledDescriptor':TABLE,'service':service,'workspace':q,'patchRecords':records,'patchFile':f'plans/{name}.smp','patchSHA256':hashlib.sha256(patch).hexdigest(),'clearWorkspace':False,'requiresPriorStagesDone':i>0,'confirmed':True,'samples':N,'outputWordOffset':OUT}
  wp=None
  if weight is not None:
   data=weight.astype('<f4').tobytes();fn=f'stipa_quick_band{d["band"]}.f32le';(reg/'plans'/fn).write_bytes(data);wp={'wordOffset':OUT+3*N,'wordCount':len(weight),'materialized':True,'file':fn,'sha256':hashlib.sha256(data).hexdigest()};plan['weightPage']=wp
  (reg/'plans'/f'{name}.json').write_text(json.dumps(plan,separators=(',',':')),encoding='utf-8');stages.append({'stage':i,**d,'plan':f'plans/{name}.json','patchFile':plan['patchFile'],'weightPage':wp});lengths.append(len(c.words))
 graphplan={'kind':'stage_graph','measurementMode':'quick','indexLabel':'rapid modulation-transfer estimate','stages':stages,'samples':N,'initialClearRange':{'wordOffset':BASE,'wordCount':8192+q['words']},'weightsMaterialized':True,'finalOutput':{'offset':OUT,'fields':['experimental_index','valid','certified_zero']},'captureValidationRequired':True,'frequencyBandsHz':[500,1000,2000],'certified':False}
 (reg/'plans/stipa_quick.json').write_text(json.dumps(graphplan,separators=(',',':')),encoding='utf-8');print('Quick stages',len(stages),'Max program',max(lengths),'Sample count',N)
if __name__=='__main__':build()
