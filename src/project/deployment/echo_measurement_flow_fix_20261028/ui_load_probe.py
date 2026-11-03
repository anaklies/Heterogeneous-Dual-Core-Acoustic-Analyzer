import os,time,json
from pathlib import Path
os.environ['SIXMIC_USER_DATA_DIR']=str(Path('deployment/echo_measurement_flow_fix_20261028/ui_probe_user').resolve())
from main import create_application
from PySide6.QtCore import QTimer
app,engine,bridge,vm,*_=create_application(argv=['echo-probe']);rt=vm._feature_facade._runtime;start=time.monotonic();seq=['frequency_tracking','frequency_drift','flatness','spectral_kurtosis'];step=-1;at=0;out=[]
def tick():
 global step,at
 now=time.monotonic()
 if now-start>25:app.quit();return
 if not vm._feature_facade._feature_api.get('enabled'):return
 if step<0 or now-at>3:
  if step>=0:
   w=vm._feature_facade.workspace();out.append({'feature':seq[step],'state':w.get('state'),'error':w.get('error'),'message':w.get('message'),'rows':len((w.get('chart')or{}).get('scalarRows',[])),'series':len((w.get('chart')or{}).get('series',[]))});vm.stopFeature(seq[step]);print(out[-1],flush=True)
  step+=1
  if step>=len(seq):Path('deployment/echo_measurement_flow_fix_20261028/UI_LOAD_BEFORE.json').write_text(json.dumps(out,indent=2));app.quit();return
  vm.setCurrentPage('periodic');vm.openFeatureEntry(seq[step]);vm.runFeature(seq[step]);at=now
t=QTimer();t.setInterval(100);t.timeout.connect(tick);t.start();QTimer.singleShot(100,lambda:vm.connectDevice('192.168.77.2',48120,48121));app.exec()
