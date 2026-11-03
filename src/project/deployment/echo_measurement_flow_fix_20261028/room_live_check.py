import json,time,winsound,struct
from pathlib import Path
from sixmic_backend.session import DeviceSession
from pc_client.client import FeatureClient
R=Path(__file__).resolve().parent;d={k:R/'room_user'/k for k in ['logs','data','events','recordings','exports','config']}
for v in d.values():v.mkdir(parents=True,exist_ok=True)
s=DeviceSession(host='192.168.77.2',user_dirs=d);out=[]
def save():(R/'ROOM_LIVE_CHECK.json').write_text(json.dumps(out,indent=2))
try:
 s.connect();c=FeatureClient(s);c.list_features()
 for name,play in [('background_only',False),('speaker_impulse',True)]:
  t=time.monotonic();j=c.start_feature('room_decay',{'stimulus':'impulse'});jid=j['jobId'];played=False;trace=[]
  while time.monotonic()-t<35:
   v=c.get_feature(jid);p=v.get('progress')or{}
   if play and not played and p.get('phase')=='capturing':winsound.PlaySound(str(R/'test_audio/高频宽带强脉冲_12ms.wav'),winsound.SND_FILENAME|winsound.SND_ASYNC);played=True
   sample={'seconds':round(time.monotonic()-t,2),'state':v['state'],'phase':p.get('phase'),'samples':p.get('capturedSamples'),'excitation':p.get('excitationDetected')}
   if not trace or sample['phase']!=trace[-1]['phase']:trace.append(sample)
   if v['state'] in ['completed','failed','canceled']:break
   time.sleep(.05)
  row={'case':name,'played':played,'elapsed':time.monotonic()-t,'result':v,'trace':trace}
  out.append(row);save()
  if v['state']=='completed':
   z=c.get_feature_result(jid);raw=s.data_store.read_slice(z.data_ref['handleId'],0,z.data_ref['count']);(R/(name+'.bin')).write_bytes(raw);row['schema']=z.schema;row['summary']=list(struct.unpack_from('<32f',raw));s.data_store.release(z.data_ref['handleId'])
  elif v['state'] not in ['failed','canceled']:c.stop_feature(jid)
  save();print(name,v['state'],v.get('error'),round(row['elapsed'],2),flush=True);time.sleep(.3)
 j=c.start_feature('event_trigger',{'channel':0});jid=j['jobId'];time.sleep(.4);v=c.get_feature(jid);out.append({'case':'monitor_state','result':v});c.stop_feature(jid);save();print('monitor',v['state'],flush=True)
finally:winsound.PlaySound(None,0);s.close()
