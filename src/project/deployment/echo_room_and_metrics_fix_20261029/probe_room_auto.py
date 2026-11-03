import json,time,struct,winsound,urllib.request,wave
from pathlib import Path
import numpy as np
from sixmic_backend.session import DeviceSession
from pc_client.client import FeatureClient
R=Path(__file__).resolve().parent;fs=48000;rng=np.random.default_rng(29101);x=rng.normal(size=8192);f=np.fft.rfftfreq(len(x),1/fs);z=np.fft.rfft(x);z[(f<500)|(f>8000)]=0;x=np.fft.irfft(z);pulse=x[1000:1384]*np.hanning(384);pulse*=.8/max(abs(pulse));y=np.zeros(fs*2);y[2400:2400+len(pulse)]=pulse
with wave.open(str(R/'pulse_test.wav'),'wb')as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(fs);w.writeframes(np.rint(y*32767).astype('<i2').tobytes())
d={k:R/'user'/k for k in ['logs','data','events','recordings','exports','config']}
for q in d.values():q.mkdir(parents=True,exist_ok=True)
s=DeviceSession(host='192.168.77.2',user_dirs=d);opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));out={}
try:
 s.connect();c=FeatureClient(s);c.list_features();out['statusBefore']=s.control.request('status.get',{});j=c.start_feature('room_decay',{'stimulus':'impulse','autoChannel':True});jid=j['jobId'];t=time.monotonic();played=False;trace=[]
 while time.monotonic()-t<35:
  v=c.get_feature(jid);pg=v.get('progress')or{}
  if pg.get('phase')=='capturing' and not played:winsound.PlaySound(str(R/'pulse_test.wav'),winsound.SND_FILENAME|winsound.SND_ASYNC);played=True;out['playAt']=time.monotonic()-t
  item={'t':time.monotonic()-t,'state':v['state'],'progress':pg}
  if not trace or item['state']!=trace[-1]['state'] or pg.get('phase')!=trace[-1]['progress'].get('phase'):trace.append(item)
  if v['state'] in ['completed','failed','canceled']:break
  time.sleep(.03)
 out.update(job=v,trace=trace,seconds=time.monotonic()-t,played=played)
 if v['state']=='completed':
  z=c.get_feature_result(jid);out['metadata']=z.to_dict();raw=s.data_store.read_slice(z.data_ref['handleId'],0,z.data_ref['count']);(R/'auto_api_result.bin').write_bytes(raw);s.data_store.release(z.data_ref['handleId'])
 elif v['state'] not in ['failed','canceled']:c.stop_feature(jid)
 for file in ['captured.bin','prepared.bin','result.bin','trace.jsonl']:
  try:(R/('auto_'+file)).write_bytes(opener.open('http://192.168.77.2:48091/'+file,timeout=3).read())
  except Exception as e:out[file+'Error']=str(e)
 print(v['state'],v.get('error'),out['seconds'],flush=True)
finally:winsound.PlaySound(None,0);s.close();(R/'ROOM_AUTO_TRACE.json').write_text(json.dumps(out,indent=2))
