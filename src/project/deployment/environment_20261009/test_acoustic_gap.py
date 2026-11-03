from pathlib import Path
import sys,ctypes,json
import numpy as np
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(Path('C:/Users/sunxi/Desktop/sixmic3D_fpga/pl/baseline_20261008')))
from measure_algorithms import lib,scene,positions,call,evaluate
from summarize import tracking,statistics
cand=ctypes.CDLL(str(HERE/'gap_tracking.dll'))
cand.candidate.argtypes=lib.baseline_track.argtypes
cand.before.argtypes=lib.baseline_track.argtypes

def tracked(fn,raw,dt,reset):
    out=np.zeros(52,np.int32);fn(raw,dt,reset,out);return out
def detection(point,valid=True):
    out=np.zeros(52,np.int32);out[0]=1;out[7]=1;out[8]=valid
    point=np.array(point);direction=point/np.linalg.norm(point)
    out[9:12]=np.rint(direction*65536).astype(np.int32)
    out[12:15]=np.rint(point*65536).astype(np.int32) if valid else 0
    return out
results={}
for name,fn in [('before',cand.before),('candidate',cand.candidate)]:
    recovery=[]
    for frame,(point,valid) in enumerate([([1,0,0],True),([1,0,0],True),([1,0,0],False),([1.04,0,0],True)]):
        out=tracked(fn,detection(point,valid),.25,frame==0);recovery.append(out.tolist())
    dt_ids=[]
    for f in range(24):
        point=[1,.04*f,.1]
        dt=.25 if f<2 else 1e-40 if f==2 else .25
        out=tracked(fn,detection(point),dt,f==0);dt_ids.append([int(out[7+15*t]) for t in range(out[0])])
    results[name]={'reacquire_step_cm':abs(recovery[3][12]-recovery[1][12])/655.36,'invalid_frame_range':recovery[2][8],
      'subnormal_dt_ids':dt_ids,'trajectory':{}}
    for group,count in [('static_track',1),('moving_two',2),('crossing_two',2),('moving_three',3)]:
        rows=[]
        for frame in range(40):
            if group=='crossing_two':
                az=np.array([-.6+.03*frame,.6-.03*frame]);el=np.array([.1,.14]);ds=np.array([1.2,1.5])
                p=np.stack((ds*np.cos(el)*np.cos(az),ds*np.cos(el)*np.sin(az),ds*np.sin(el)),axis=1)
            else:
                p=positions(1.5,count,42)
                if group!='static_track':p[:,0]+=.004*frame;p[:,1]+=.002*frame
            a,c,m=scene(p,12,.2,4000+frame,True);raw,_=call(a,c,m)
            out=tracked(fn,raw,.25,frame==0);r=evaluate(out,p);r.update(group=group,source_count=count,frame=frame)
            rows.append(r)
        results[name]['trajectory'][group]={'tracking':tracking(rows),'errors':statistics(rows)}
assert results['candidate']['invalid_frame_range']==0,'Never label stale distance as fresh valid'
assert results['candidate']['reacquire_step_cm']==0
assert all(ids==[1] for ids in results['candidate']['subnormal_dt_ids'])
(HERE/'acoustic_tracking_comparison.json').write_text(json.dumps(results,indent=2))
for name,r in results.items():
    print(name,'reacquire step cm',r['reacquire_step_cm'],'dt IDs',r['subnormal_dt_ids'][2:6])
    for group,s in r['trajectory'].items():print(group,'ID changes',s['tracking']['id_changes_on_assigned_truth'],'mean cm',s['errors']['mean_error_cm'],'OSPA',s['errors']['mean_ospa_cm_cap100'])

