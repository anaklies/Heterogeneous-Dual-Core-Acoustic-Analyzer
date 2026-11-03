import json,time,sys,struct,winsound
from pathlib import Path
from sixmic_backend.session import DeviceSession
from pc_client.client import FeatureClient
R=Path(__file__).resolve().parent
d={k:R/'final_user'/k for k in ['logs','data','events','recordings','exports','config']}
for q in d.values():q.mkdir(parents=True,exist_ok=True)
s=DeviceSession(host='192.168.77.2',user_dirs=d);rows=[]
try:
 s.connect();c=FeatureClient(s);c.list_features();time.sleep(.5)
 cases=[('spectral_decay',{'stimulus':'impulse','autoChannel':True}),('frequency_time_weighting',{'timeResponse':True,'autoChannel':True}),('frequency_time_weighting',{'weighting':'C','autoChannel':True}),('noise_rating',{'family':'NR','referenceConfirmed':True,'referenceOffsetDb':0,'calibrationSource':'explicit digital nominal reference, not SPL calibration','autoChannel':True})]
 for index,(fid,p) in enumerate(cases):
  row={'feature':fid,'params':p};rows.append(row);t=time.monotonic();j=c.start_feature(fid,p);jid=j['jobId'];played=False
  while time.monotonic()-t<40:
   v=c.get_feature(jid)
   if fid=='spectral_decay' and not played and (v.get('progress')or{}).get('phase')=='capturing':winsound.PlaySound(str(R/'pulse_test.wav'),winsound.SND_FILENAME|winsound.SND_ASYNC);played=True
   if v['state'] in ['completed','failed','canceled']:break
   time.sleep(.04)
  row.update(job=v,seconds=time.monotonic()-t)
  if v['state']=='completed':
   z=c.get_feature_result(jid);row['metadata']=z.to_dict();raw=s.data_store.read_slice(z.data_ref['handleId'],0,z.data_ref['count']);(R/f'final_{index}.bin').write_bytes(raw);s.data_store.release(z.data_ref['handleId']);row['summary']=list(struct.unpack('<'+str(min(32,len(raw)//4))+'f',raw[:min(128,len(raw))]))
  elif v['state'] not in ['failed','canceled']:c.stop_feature(jid)
  print(fid,v['state'],v.get('selectedChannel'),round(row['seconds'],2),flush=True)
finally:
 winsound.PlaySound(None,0);s.close();(R/'METRICS_BOARD_FINAL.json').write_text(json.dumps(rows,indent=2),encoding='utf8')
