"""Offline synthetic display QA only. Never connects to hardware."""
import sys,struct,json,time,importlib.util
from pathlib import Path
from PySide6.QtCore import QTimer,Qt,QPoint,QPointF
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
R=Path(__file__).resolve().parent;ROOT=R.parents[1];APP=ROOT/'apps/sixmic-desktop';sys.path.insert(0,str(APP/'tests/frontend'))
from test_feature_runtime import Harness,CONFIG
from ui.features import load_spec
from ui.features.runtime import _Job
from ui.features.decoder import decode_result
module=importlib.util.spec_from_file_location('echo_entry',APP/'main.py');m=importlib.util.module_from_spec(module);module.loader.exec_module(m)
application,engine,bridge,vm,theme,images,qml=m.create_application(None,None)
vm._settings['windowWidth']=1440;vm._settings['windowHeight']=900;vm._settings['windowMaximized']=False
h=Harness(load_spec(),instrument_mode=True);vm._feature_facade._runtime=h.rt;vm._fixture_active=True;vm._source='test-fixture'
warnings=[];engine.warnings.connect(lambda rows:warnings.extend(str(x) for x in rows));out={'source':'synthetic-software-fixture','hardwareTested':False}

def visual_items(item):
 result=[]
 for child in item.childItems():result.append(child);result+=visual_items(child)
 return result
count=0;ids=None;geos=None
def prepare():
 window=engine.rootObjects()[0];window.showNormal();window.resize(1440,900)
 vm._dashboard={'levels':[{'label':f'MIC{i+1}','value':-.1 if i==0 else -40.-i,'valid':True,'color':theme.channelColors[i]} for i in range(6)],'sampleRateHz':48000}
 vm.setCurrentPage('overview');vm._schedule_changed();QTimer.singleShot(350,check)
def check():
 global count,ids,geos
 from shiboken6 import getCppPointer
 window=engine.rootObjects()[0];items=visual_items(window.contentItem());labels=sorted([x for x in items if x.objectName().startswith('overviewMicValue')],key=lambda x:x.objectName())
 assert len(labels)==6
 assert all(x.property('visible') and x.property('text')!='—' for x in labels)
 now=[getCppPointer(x)[0] for x in labels];g=[(x.x(),x.y(),x.width(),x.height()) for x in labels]
 if ids is not None:assert ids==now and geos==g
 ids=now;geos=g;count+=1
 if count<12:
  d=dict(vm._dashboard);d['levels']=[dict(v,value=(-.1 if count%2 else -90.) if i==0 else v['value']) for i,v in enumerate(d['levels'])];vm._dashboard=d;vm._schedule_changed();QTimer.singleShot(35,check)
 else:
  window.grabWindow().save(str(R/'dashboard_values_fixed.png'));out.update({'readouts':6,'alternatingHighLevelUpdates':count,'instancesAndGeometryStable':True});vm.setCurrentPage('room');h.rt.open('stipa_experimental');h.rt.confirm('stipa_experimental','measurementMode','quick');h.rt.on_change(vm._feature_facade._emit_changed);vm._feature_facade._emit_changed();vm._schedule_changed();QTimer.singleShot(350,mode)
def mode():
 window=engine.rootObjects()[0];items=visual_items(window.contentItem());controls=[x for x in items if x.objectName()=='stipaMeasurementMode' and x.property('visible')];assert len(controls)==1 and controls[0].property('currentIndex')==1
 assert vm._feature_facade._runtime.workspace()['chart']['stage']['total']==15
 assert vm._feature_facade._runtime.workspace()['chart']['indexLabel']=='快速调制保持指数'
 assert not warnings,warnings
 window.grabWindow().save(str(R/'quick_mode.png'));out.update({'quickSelectorLoaded':True,'warnings':warnings});(R/'UI_CHECK.json').write_text(json.dumps(out,indent=2));application.quit()
QTimer.singleShot(250,prepare)
QTimer.singleShot(5000,application.quit)
application.exec();bridge.shutdown();assert out.get('quickSelectorLoaded');print(json.dumps(out,indent=2))
