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

from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
checks={}
def prepare():
 w=engine.rootObjects()[0];w.showNormal();w.resize(1440,900);vm.setCurrentPage('bands');h.rt.open('frequency_time_weighting');h.rt.on_change(vm._feature_facade._emit_changed);vm._feature_facade._emit_changed();vm._schedule_changed();QTimer.singleShot(350,choose)
def choose():
 w=engine.rootObjects()[0];items=visual_items(w.contentItem());selectors=[o for o in items if o.objectName()=='measurementVariantSelector' and o.property('visible')];assert selectors
 combo=selectors[-1];assert combo.property('count')==4
 point=combo.mapToScene(combo.boundingRect().center());QTest.mouseClick(w,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(round(point.x()),round(point.y())));QTest.qWait(40);QTest.keyClick(w,Qt.Key.Key_Down);QTest.keyClick(w,Qt.Key.Key_Return);QTest.qWait(40)
 assert h.rt._selected_variants.get('frequency_time_weighting')==1
 h.rt.run('frequency_time_weighting');call=h.gw.take('start');assert call['args']['params']['weighting']=='C';assert not h.rt._variant_pending['frequency_time_weighting'];checks['selectorClickStartsOnlyC']=True
 # Keep a successful plot while data and action enabled states change.
 assert not warnings,warnings
 checks['qmlWarnings']=warnings;(R/'SELECTOR_INTERACTION_CHECK.json').write_text(json.dumps(checks,indent=2));w.grabWindow().save(str(R/'selector_verified.png'));application.quit()
QTimer.singleShot(200,prepare);QTimer.singleShot(4000,application.quit);application.exec();bridge.shutdown();assert checks.get('selectorClickStartsOnlyC');print(checks)
