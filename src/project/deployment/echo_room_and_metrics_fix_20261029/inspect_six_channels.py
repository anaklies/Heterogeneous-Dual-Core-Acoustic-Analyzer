import json,time,struct
from pathlib import Path
import numpy as np
from sixmic_backend.session import DeviceSession
from pc_client.client import FeatureClient
R=Path(__file__).resolve().parent;d={k:R/'six_user'/k for k in ['logs','data','events','recordings','exports','config']}
for x in d.values():x.mkdir(parents=True,exist_ok=True)
s=DeviceSession(host='192.168.77.2',user_dirs=d)
try:
 s.connect();c=FeatureClient(s);c.list_features();j=c.start_feature('io_pcm',{'samples':48000,'channels':6});t=time.monotonic()
 while time.monotonic()-t<10:
  v=c.get_feature(j['jobId'])
  if v['state'] in ['completed','failed']:break
  time.sleep(.1)
 out={'job':v}
 if v['state']=='completed':
  z=c.get_feature_result(j['jobId']);raw=s.data_store.read_slice(z.data_ref['handleId'],0,z.data_ref['count']);(R/'six_pcm.bin').write_bytes(raw);x=np.frombuffer(raw,'<i4').reshape(6,-1)/8388608;out['schema']=z.schema;out['channels']=[]
  for i in range(6):
   a=x[i];q=np.percentile(abs(a),[50,90,99,99.9,100]);out['channels'].append({'channel':i+1,'rms':float(np.sqrt(np.mean(a*a))),'absPercentiles':q.tolist(),'spikesAbove0_05':int(np.sum(abs(a)>.05)),'peakIndex':int(np.argmax(abs(a)))})
  s.data_store.release(z.data_ref['handleId'])
 print(out.get('channels'),flush=True);(R/'SIX_CHANNEL_INPUT.json').write_text(json.dumps(out,indent=2))
finally:s.close()
