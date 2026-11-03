"""Pixel-bound regression for native Qt Canvas DPI. Runs in a fresh process."""
from __future__ import annotations
import argparse,json,os,sys,time
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--dpi',type=float,default=1);args=parser.parse_args()
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software';os.environ['QT_SCALE_FACTOR']=str(args.dpi)
os.environ.setdefault('QT_QPA_FONTDIR',r'C:\Windows\Fonts')
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem
from ui.viewmodels.theme_source import ThemeSource
app=QGuiApplication([]);engine=QQmlApplicationEngine();theme=ThemeSource('dark');engine.rootContext().setContextProperty('Theme',theme)
chart_url=QUrl.fromLocalFile(str(root/'ui/qml/components/charts')).toString()
engine.loadData(('import QtQuick\nimport "'+chart_url+'"\nWindow { width:300;height:200;visible:true; '
 'LineChart { objectName:"probe";anchors.fill:parent;showLegend:false; '
 'series:[{name:"probe",color:"#ff0000",points:[[0,0],[1,1]],width:2}]; '
 'xAxis:({min:0,max:1,scale:"linear"});yAxis:({min:0,max:1,scale:"linear"}) } }').encode())
if not engine.rootObjects():raise SystemExit('QML_LOAD_FAILED')
window=engine.rootObjects()[0]
end=time.monotonic()+.2
while time.monotonic()<end:app.processEvents();time.sleep(.005)
chart=window.findChild(QQuickItem,'probe');image=window.grabWindow();pixels=[]
for y in range(image.height()):
    for x in range(image.width()):
        color=image.pixelColor(x,y)
        if color.red()>180 and color.green()<45 and color.blue()<45:pixels.append((x,y))
assert pixels,'No red measurement trace rendered'
actual=[min(x for x,y in pixels),min(y for x,y in pixels),max(x for x,y in pixels),max(y for x,y in pixels)]
dpr=window.devicePixelRatio()
query=QQmlExpression(qmlContext(chart),chart,'[screenX(0),screenY(1),screenX(1),screenY(0)]')
coords=query.evaluate()[0]
if hasattr(coords,'toVariant'):coords=coords.toVariant()
assert not query.hasError(),query.error().toString()
expected=[v*dpr for v in coords]
ok=all(abs(a-b)<=4 for a,b in zip(actual,expected))
print(json.dumps({'dpi':dpr,'pixels':[image.width(),image.height()],'actualBounds':actual,'expectedBounds':expected,'pass':ok}))
window.close()
raise SystemExit(0 if ok else 1)
