import json,time,winsound
from pathlib import Path
from sixmic_backend.session import DeviceSession
from pc_client.client import FeatureClient
R=Path(__file__).resolve().parent;d={k:R/'event_user'/k for k in ['logs','data','events','recordings','exports','config']}
for p in d.values():p.mkdir(parents=True,exist_ok=True)
s=DeviceSession(host='192.168.77.2',user_dirs=d);out={};jid=None
try:
 s.connect();c=FeatureClient(s);c.list_features();out['before']=s.list_events();old={e['eventId'] for e in out['before']}
 j=c.start_feature('event_trigger');jid=j['jobId'];time.sleep(3);out['running']=c.get_feature(jid)
 winsound.PlaySound(str(R/'pulse_test.wav'),winsound.SND_FILENAME|winsound.SND_ASYNC);time.sleep(4)
 out['after']=s.list_events();new=[e for e in out['after'] if e['eventId'] not in old]
 if new:out['download']=s.download_event(int(new[-1]['eventId']))
 print('EVENT_RESULT',out['running']['state'],out['running'].get('progress'),len(new),flush=True)
except Exception as e:out['error']=str(e);print(e,flush=True)
finally:
 if jid:
  try:out['stop']=c.stop_feature(jid)
  except Exception as e:out['stopError']=str(e)
 winsound.PlaySound(None,0);s.close();(R/'EVENT_BOARD_FINAL.json').write_text(json.dumps(out,indent=2),encoding='utf8')
