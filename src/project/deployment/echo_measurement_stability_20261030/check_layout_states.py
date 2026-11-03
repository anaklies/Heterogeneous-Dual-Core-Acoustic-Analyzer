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

from ui.features.runtime import _Job
cases=[('relative_limit','spectrum','statistics'),('frequency_time_weighting','bands','weighting'),('room_decay','room','room-decay')]
ci=0;si=0;baseline=None;plots_base=None;results=[];waits=0
def prepare_case():
 global si,baseline,plots_base,waits
 waits=0
 si=0;baseline=None;plots_base=None;fid,page,kind=cases[ci];h.rt._jobs.clear();h.rt._results.clear();h.rt._live_requested.clear();vm.setCurrentPage(page);h.rt.open(fid);h.rt._variants.pop(fid,None)
 panel={'render':'line','title':'设备数值','series':[{'name':'PL数值','points':[[0,-50],[1,-30]],'color':'#57C8FF'}],'xAxis':{'min':0,'max':1,'unit':'s'},'yAxis':{'min':-120,'max':0,'unit':'dBFS'}}
 chart={'kind':kind,'title':'布局测试','series':panel['series'],'panels':[dict(panel),dict(panel)] if fid!='room_decay' else [dict(panel)],'scalarRows':[{'label':'数值'+str(i),'value':1.,'unit':'dB','valid':True} for i in range(5)],'xAxis':panel['xAxis'],'yAxis':panel['yAxis']}
 h.rt._results[fid]={'chart':chart,'raw_bytes':b'', 'capturedAt':0,'sourceKind':'test-fixture','configuration':CONFIG}
 h.rt.on_change(vm._feature_facade._emit_changed);vm._feature_facade._emit_changed();vm._schedule_changed();QTimer.singleShot(220,cycle)
def cycle():
 global si,baseline,ci,plots_base,waits
 fid,page,kind=cases[ci];window=engine.rootObjects()[0];ws=[x for x in visual_items(window.contentItem()) if x.objectName()=='featureWorkspace' and x.property('featureId')==fid]
 if not ws and waits<4:
  waits+=1;h.rt._open_feature=fid;vm._feature_facade._emit_changed();vm._schedule_changed();QTimer.singleShot(100,cycle);return
 assert ws,(fid,vm.currentPage,h.rt._open_feature,warnings)
 surfaces=[x for x in visual_items(ws[-1]) if x.objectName()=='analysisChartSurface'];assert surfaces
 o=surfaces[0];geom=(round(o.x(),2),round(o.y(),2),round(o.width(),2),round(o.height(),2))
 if baseline is None:baseline=geom
 assert geom==baseline,(fid,si,baseline,geom)
 plots=sorted([(x.objectName(),round(x.x(),2),round(x.y(),2),round(x.width(),2),round(x.height(),2)) for x in visual_items(ws[-1]) if x.isVisible() and x.objectName() in {'chartLine','panelLineChart','abTopChart','abDeltaChart','readoutLineChart','noiseLineChart'}])
 if plots_base is None:plots_base=plots
 if plots!=plots_base:
  def plain(v):return v.toVariant() if hasattr(v,'toVariant') else v
  print('PLOT_DIAG',fid,si,'runtime panels',len(h.rt.workspace()['chart'].get('panels',[])),'qml panels',len(plain(ws[-1].property('currentChart')).get('panels',[])),[(x.objectName(),len(plain(x.property('panels')) or [])) for x in visual_items(ws[-1]) if x.objectName() in ['chartReadoutLine','chartPanel']],flush=True)
 assert plots==plots_base,(fid,si,plots_base,plots)
 si+=1
 if si<12:
  job=_Job(job_id='layout-job',owner=fid,feature_id=fid,state=['queued','starting','accepted','running','completed','failed'][si%6],configuration=CONFIG)
  h.rt._jobs['layout-job']=job;h.rt._messages[fid]={'zh':'正在采集与处理 '+('很长的设备状态 '*si)};vm._feature_facade._emit_changed();vm._schedule_changed();QTimer.singleShot(25,cycle)
 else:
  results.append({'feature':fid,'stateChanges':12,'geometryStable':True,'internalPlotsStable':True,'geometry':geom})
  window.grabWindow().save(str(R/(fid+'_layout.png')));ci+=1
  if ci<len(cases):prepare_case()
  else:
   assert not warnings,warnings;(R/'LAYOUT_STATE_CHECK.json').write_text(json.dumps({'softwareOnly':True,'results':results,'qmlWarnings':warnings},indent=2));application.quit()
def start():
 w=engine.rootObjects()[0];w.showNormal();w.resize(1440,900);prepare_case()
QTimer.singleShot(250,start);QTimer.singleShot(6000,application.quit)
application.exec();bridge.shutdown();assert len(results)==3;print(json.dumps(results,indent=2))
