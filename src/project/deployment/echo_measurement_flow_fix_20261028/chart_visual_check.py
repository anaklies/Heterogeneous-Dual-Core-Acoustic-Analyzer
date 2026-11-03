import os,json,struct
from pathlib import Path
os.environ['SIXMIC_USER_DATA_DIR']=str(Path('deployment/echo_measurement_flow_fix_20261028/visual_user').resolve())
from main import create_application
from PySide6.QtCore import QUrl,QTimer
from PySide6.QtQml import QQmlComponent
from ui.features.decoder import decode_result
R=Path(__file__).resolve().parent;ROOT=R.parents[1];spec=json.loads((ROOT/'apps/sixmic-desktop/ui/config/feature_view_spec.json').read_text(encoding='utf-8'))['features'];meta=json.loads((R/'PATH_CHECK.json').read_text())
app,engine,bridge,vm,*_=create_application(argv=['chart-visual-test']);engine.rootObjects()[0].hide()
component=QQmlComponent(engine);url=(ROOT/'apps/sixmic-desktop/ui/qml/components').as_uri()
component.setData(('import QtQuick\nimport QtQuick.Window\nimport "'+url+'"\nWindow {width:1200;height:760;visible:true;color:"#0f1214";FeatureChart {anchors.fill:parent;anchors.margins:16;chart:qaPayload;workspaceOverride:({available:true,featureId:"gcc_phat"});sourceKindOverride:"test-fixture";sourceLabelOverride:"图表结构检查 · 保存数据"}}').encode(),QUrl())
charts=[]
row=next(r for r in meta if r['featureId']=='gcc_phat');raw=(R/'gcc_phat.bin').read_bytes();chart=decode_result(spec['gcc_phat'],row['metadata'],struct.unpack('<2048I',raw));charts.append(('gcc',chart))
charts.append(('trend',{'kind':'scalar-trend','available':True,'title':'趋势结构检查（合成测试数据）','subtitle':'不作为实测验收','series':[{'name':'当前功率','points':[[i,i%5*.00001]for i in range(20)]}],'scalarRows':[{'label':'power_FS2','displayLabel':'当前功率','value':.00004,'valid':True,'unit':'FS²'}],'xAxis':{'min':0,'max':20,'unit':'s'},'yAxis':{'min':0,'max':.00005,'unit':'FS²'},'chartRevision':'ui-test'}))
items=[];result=[]
def show(i):
 if i>=len(charts):(R/'CHART_VISUAL_CHECK.json').write_text(json.dumps(result,indent=2));app.quit();return
 name,data=charts[i];engine.rootContext().setContextProperty('qaPayload',data);item=component.create();items.append(item)
 if item is None:result.append({'name':name,'errors':[str(e)for e in component.errors()]});app.quit();return
 def snap():
  ok=item.grabWindow().save(str(R/(name+'_view.png')));result.append({'name':name,'saved':ok});item.hide();show(i+1)
 QTimer.singleShot(600,snap)
QTimer.singleShot(0,lambda:show(0));app.exec()
