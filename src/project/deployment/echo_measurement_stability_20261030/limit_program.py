from pathlib import Path
import sys,json,math,struct,hashlib
import numpy as np
O=Path(__file__).resolve().parent;ROOT=O.parents[1];S=ROOT/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/services';sys.path.insert(0,str(S));from programs import Code,install
N=1025;BASE=1048576;TABLE=525312;OUT=BASE+8192;ARENA=4194304

def limit_program(count=N,threshold_db=6.):
 c=Code();c.u(0,0);c.u(1,0);c.u(2,count);c.u(3,2*count);c.u(4,count);c.u(5,0);c.f(3,threshold_db);c.f(4,0);c.f(5,1);c.f(6,1e-10);c.f(7,10/math.log(10));c.f(15,0);c.f(16,0)
 loop=len(c.words);c.load(0,1);c.load(1,2);c.emit(5,8,0,1);c.store(8,0);c.emit(12,9,0,6);c.emit(12,10,1,6);c.emit(7,11,9,10);c.emit(9,11,11);c.emit(6,11,11,7);c.store(11,4);c.emit(13,12,11);c.store(4,3);alarm=c.emit(19,a=3,b=12,target=0);skip=c.emit(17,imm=0);c.words[alarm][2]=len(c.words);c.store(5,3);c.emit(4,15,15,5);c.words[skip][1]=len(c.words);c.emit(12,16,16,12)
 for reg in range(5):c.addi(reg,reg,1)
 c.loop(0,count,loop);c.store(3,5,3*count);c.store(15,5,3*count+1);c.store(16,5,3*count+2);c.emit(0)
 return c,3*count+3,{'service':'relative_limit_power_ratio_v2','bins':count,'input_word_offset':OUT+4096,'change_db_offset':count,'flags_offset':2*count,'summary_offset':3*count,'threshold_db':threshold_db,'power_floor_FS2_bin':1e-10,'units':'delta FS2/bin; change dB; flags boolean','programRevision':2}

def build():
 base=ROOT/'deployment/echo_interface_guard_20261026/registry/plans/relative_limit.json';plan=json.loads(base.read_text());spec=limit_program();m=np.zeros(ARENA,np.float32);service=install(m,spec,base=BASE);u=m.view(np.uint32)
 for slot in range(4):u[BASE+16*slot+5:BASE+16*slot+7]=[OUT+4096,2*N]
 u[TABLE:TABLE+64]=u[BASE:BASE+64]
 ranges=[(TABLE,64),(BASE,64),(BASE+128,4*len(spec[0].words)),(BASE+4352,320)]
 plan.update(service=service,producer='relative_limit_power_ratio_v2',outputWordCount=spec[1],params={'count':N,'threshold':6.0},patchRecords=[{'wordOffset':a,'wordCount':n,'words':u[a:a+n].tolist()} for a,n in ranges])
 data=b''.join(struct.pack('<II',a,n)+u[a:a+n].astype('<u4').tobytes() for a,n in ranges)+struct.pack('<II',0,0)
 plan.update(patchFile='plans/relative_limit.smp',patchSHA256=hashlib.sha256(data).hexdigest())
 out=O/'registry/plans';out.mkdir(parents=True,exist_ok=True);(out/'relative_limit.smp').write_bytes(data);(out/'relative_limit.json').write_text(json.dumps(plan,separators=(',',':')),encoding='utf-8')
 j=json.loads((ROOT/'deployment/echo_stipa_quick_20261030/registry/INTERFACE_REGISTRY.json').read_text(encoding='utf-8'));f=next(x for x in j['features']if x['featureId']=='relative_limit');f['params']['threshold'].update(default=6.0,unit='dB');f['output']['metadata']=service['metadata'];f['output']['wordCount']=spec[1];f['producer']='relative_limit_power_ratio_v2';f['input']['layout']='float32 FS2/bin [current B, frozen A] at input_word_offset';f['input']['requires']=['capture/freeze reference A','matching channel/grid/gain/source metadata'];f['schema']['units']=service['metadata']['units'];f['schema']['fields']=['signed_delta_FS2','change_db','threshold_flags','summary'];f['schema']['producerLayout']=service['metadata'];f['schema']['programRevision']=2
 (O/'registry/INTERFACE_REGISTRY.json').write_text(json.dumps(j,ensure_ascii=False,indent=2),encoding='utf-8');print('Relative limit program',len(spec[0].words),'instructions; threshold 6dB')
if __name__=='__main__':build()
