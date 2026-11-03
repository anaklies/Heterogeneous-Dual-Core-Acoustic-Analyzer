import json,time,struct
from pathlib import Path
from sixmic_backend.session import DeviceSession
from pc_client.client import FeatureClient
R=Path(__file__).resolve().parent;d={k:R/'user'/k for k in ['logs','data','events','recordings','exports','config']}
for x in d.values():x.mkdir(parents=True,exist_ok=True)
s=DeviceSession(host='192.168.77.2',user_dirs=d);out=[]
try:
 s.connect();c=FeatureClient(s);cat=c.list_features();(R/'LIVE_CATALOG.json').write_text(json.dumps(cat,indent=2))
 for fid in ['frequency_tracking','frequency_drift','flatness','energy_change','spectral_kurtosis','gcc_phat']:
  row={'featureId':fid};jid=None;t=time.monotonic()
  try:
   j=c.start_feature(fid,{'channel':0});jid=j['jobId']
   while True:
    v=c.get_feature(jid)
    if v['state'] in ['completed','failed','canceled'] or time.monotonic()-t>10:break
    time.sleep(.15)
   row.update(result=v)
   if v['state']=='completed':
    z=c.get_feature_result(jid);row['metadata']=z.to_dict();raw=s.data_store.read_slice(z.data_ref['handleId'],0,z.data_ref['count']);(R/(fid+'.bin')).write_bytes(raw);s.data_store.release(z.data_ref['handleId'])
   else:c.stop_feature(jid)
  except Exception as e:row['error']=str(e)
  row['seconds']=time.monotonic()-t;out.append(row);(R/'PATH_CHECK.json').write_text(json.dumps(out,indent=2));print(fid,row.get('result',{}).get('state'),row.get('error'),round(row['seconds'],2),flush=True)
finally:s.close()
