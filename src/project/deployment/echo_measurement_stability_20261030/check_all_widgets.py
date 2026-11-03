"""51-entry software decode/widget resilience check; no hardware or acoustic claims."""
import sys,json,importlib.util
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent
from PySide6.QtTest import QTest
R=Path(__file__).resolve().parent;ROOT=R.parents[1];APP=ROOT/'apps/sixmic-desktop';sys.path.insert(0,str(APP/'tests/frontend'))
from test_feature_runtime import words_for,schema_for
from ui.features import load_spec
from ui.features.decoder import decode_result
module=importlib.util.spec_from_file_location('entry',APP/'main.py');m=importlib.util.module_from_spec(module);module.loader.exec_module(m)
a,engine,bridge,vm,theme,images,qml=m.create_application(None,None);window=engine.rootObjects()[0]
spec=load_spec();gateway=json.loads((APP/'tests/frontend/fixtures/features/captured_host_gateway.json').read_text(encoding='utf8'));registry=json.loads((ROOT/'deployment/echo_feature_closure_20261025/registry/INTERFACE_REGISTRY.json').read_text(encoding='utf8'));registry={e['featureId']:e for e in registry['features']}
component=QQmlComponent(engine,QUrl.fromLocalFile(str(APP/'ui/qml/components/FeatureChart.qml')));assert not component.errors()
rows=[];warnings=[];engine.warnings.connect(lambda errors:warnings.extend(str(e) for e in errors))
for fid,feature in spec['features'].items():
 start=len(warnings);row={'featureId':fid,'input':'historical schema + zero/invalid-word fixture','hardwareAccepted':False}
 try:
  schema=schema_for(fid,gateway,registry);words=words_for(fid,gateway,registry);chart=decode_result(feature,{'schema':schema},words)
  item=component.create();assert item is not None;item.setParentItem(window.contentItem());item.setWidth(1000);item.setHeight(600);item.setProperty('workspaceOverride',{'featureId':fid,'sourceKind':'test-fixture'});item.setProperty('chart',chart);a.processEvents();QTest.qWait(20)
  row.update(decoded=True,widgetLoaded=True,chartKind=chart.get('kind'));item.setParentItem(None);item.deleteLater();a.processEvents()
 except Exception as e:row['error']=str(e)
 row['warnings']=warnings[start:];rows.append(row)
bridge.shutdown();out={'softwareOnly':True,'featureCount':len(rows),'rows':rows};(R/'SOFTWARE_FEATURE_MATRIX.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8');print('MATRIX',len(rows),'errors',sum('error'in r for r in rows),'warnings',len(warnings));print('\n'.join(warnings[:12]))
