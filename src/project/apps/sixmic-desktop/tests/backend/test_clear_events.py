from types import SimpleNamespace
import pytest
from sixmic_backend.session import DeviceSession
from sixmic_backend.errors import BackendError

def test_clear_scope_and_exports_preserved(tmp_path):
 root=tmp_path/'events';root.mkdir()
 event=root/'event-00000000000000000001';event.mkdir();(event/'event.smc').write_bytes(b'test')
 other=root/'other';other.mkdir();(other/'keep').write_text('keep')
 exported=tmp_path/'exports';exported.mkdir();(exported/'saved.wav').write_bytes(b'keep')
 audio=root/'录音';audio.mkdir();(audio/'time.wav').write_bytes(b'test')
 calls=[]
 class Control:
  def request(self,op,args):
   calls.append((op,args))
   if op=='event.list':return {'events':[{'eventId':'1'},{'eventId':'2'}]}
   return {'discarded':True}
 s=DeviceSession.__new__(DeviceSession);s._pending_event_download=None;s.control=Control();s._control_token='token';s.paths={'events':root};s.event_manager=SimpleNamespace(_known={},_downloaded={})
 result=s.clear_events(True,True)
 assert result['deviceRemoved']==2 and result['localRemoved']==1 and not result['failed']
 assert not event.exists() and (other/'keep').exists() and (exported/'saved.wav').exists()
 assert not audio.exists()
 assert [a['eventId'] for op,a in calls if op=='event.discard']==['1','2']

def test_clear_refuses_active_download():
 s=DeviceSession.__new__(DeviceSession);s._pending_event_download=(1,'a',32)
 with pytest.raises(BackendError) as e:s.clear_events()
 assert e.value.code=='busy'
