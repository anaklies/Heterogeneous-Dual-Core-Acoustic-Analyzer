"""Frontend-only checks: chart space, retained-STFT mapping and real exports."""
from __future__ import annotations
import copy,json,math,time,wave
import subprocess,sys
from pathlib import Path
import pytest
from PySide6.QtCore import QObject,QPointF,QMetaObject,QUrl,qInstallMessageHandler
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlComponent,QQmlEngine,QQmlExpression,QJSEngine,qmlContext
from PySide6.QtQuick import QQuickItem

APP=Path(__file__).resolve().parents[2]

def pump(app,seconds=.15):
    end=time.monotonic()+seconds
    while time.monotonic()<end:app.processEvents();time.sleep(.005)

@pytest.fixture
def studio(qapp,tmp_path,monkeypatch):
    import main
    monkeypatch.setenv('SIXMIC_USER_DATA_DIR',str(tmp_path/'user'))
    messages=[]
    def handler(mode,context,text):
        if str(text).startswith(('QFontDatabase','FT_New_Face','Context2D: The font families','This plugin does not support propagateSizeHints')):return
        messages.append(str(text))
    previous=qInstallMessageHandler(handler)
    app,engine,bridge,vm,theme,images,_=main.create_application()
    window=engine.rootObjects()[0];window.showNormal();window.resize(1920,1080)
    yield app,engine,bridge,vm,window,messages
    vm.prepareExit();bridge.shutdown();window.close()
    qInstallMessageHandler(previous)

def display_workspace():
    return {'open':True,'featureId':'stft','page':'spectrum','name':'STFT','shortName':'STFT',
        'available':True,'state':'completed','sourceKind':'test-fixture','sourceLabel':'测试数据 · 非实测',
        'jobId':'test-only-1','units':'FS²/Hz','variants':[],
        'flow':{'actions':[],'confirmations':[],'steps':0,'note':''},
        'chart':{'kind':'stft','chartRevision':1,'frames':[{'time':100,'points':[[20,1],[100,2],[1000,3]]},{'time':101,'points':[[20,2],[100,3],[1000,4]]}],
          'xAxis':{'min':0,'max':2,'label':'频率','unit':'Hz'},'yAxis':{'min':0,'max':5,'label':'PSD','unit':'FS²/Hz'},
          'raster':{'matrix':[[3,4,5],[1,2,None]],'yUnit':'frame','rowTimes':[100,101],'min':0,'max':5}}}

def bind(studio,monkeypatch):
    app,engine,bridge,vm,window,messages=studio
    w=display_workspace()
    monkeypatch.setattr(vm._feature_facade,'workspace',lambda:copy.deepcopy(w))
    vm.setCurrentPage('spectrum');vm.featureChanged.emit();pump(app,.25)
    return w

def test_chart_has_room_and_stays_inside_small_and_large_windows(studio,monkeypatch):
    bind(studio,monkeypatch)
    app,engine,bridge,vm,window,messages=studio
    for width,height in [(1920,1080),(1280,800),(960,540),(800,500)]:
        window.resize(width,height);pump(app,.2)
        surfaces=[x for x in window.findChildren(QQuickItem,'analysisChartSurface') if x.isVisible()]
        assert surfaces
        surface=surfaces[-1];point=surface.mapToScene(QPointF(0,0))
        assert point.x()>=0 and point.y()>=0
        assert point.x()+surface.width()<=window.width()+1
        assert point.y()+surface.height()<=window.height()-25
        assert surface.height() >= (window.height()-80)*.60
    assert messages==[]

def test_stft_axes_nulls_and_view_mode_survive_data_refresh(studio,monkeypatch):
    w=bind(studio,monkeypatch)
    app,engine,bridge,vm,window,messages=studio
    chart=[x for x in window.findChildren(QQuickItem,'featureChart') if x.isVisible()][-1]
    display=chart.property('stftDisplay').toVariant()
    assert display['raster']['matrix']==[[1,3],[2,4],[None,5]]
    assert display['xAxis']['max']==1 and display['yAxis']['unit']=='Hz'
    assert display['colorScale']['unit']=='FS²/Hz' and display['colorScale']['max']==5
    chart.setProperty('threeDActive',True)
    w['chart']['chartRevision']=2;vm.featureChanged.emit();pump(app,.2)
    assert chart.property('threeDActive') is True
    info=chart.property('frameInfo').toVariant()
    assert info['frames'][0]['time']==0 and info['frames'][1]['time']==1
    assert info['frames'][0]['points'][2][1] is None
    assert messages==[]


def test_every_declared_feature_chart_kind_has_a_real_route(studio,monkeypatch):
    w=bind(studio,monkeypatch)
    app,engine,bridge,vm,window,messages=studio
    spec=json.loads((APP/'ui/config/feature_view_spec.json').read_text(encoding='utf-8'))
    kinds={f['chart'] for f in spec['features'].values()}
    for kind in kinds:
        w['chart']['kind']=kind
        vm.featureChanged.emit();pump(app,.025)
        chart=[x for x in window.findChildren(QQuickItem,'featureChart') if x.isVisible()][-1]
        assert chart.property('routeToken') != 'empty',kind
    assert messages==[]

def test_heatmap_does_not_draw_null_as_measured_zero(studio):
    app,engine,bridge,vm,window,messages=studio
    component=QQmlComponent(engine,QUrl.fromLocalFile(str(APP/'ui/qml/components/charts/HeatmapChart.qml')))
    item=component.create()
    assert item,component.errors()
    query=QQmlExpression(qmlContext(item),item,'sampleMatrix([[null,null],[null,null]],0.5,0.5)')
    value=query.evaluate()[0]
    assert not query.hasError() and math.isnan(value)
    item.deleteLater()


def test_small_screen_inspector_drawer_really_opens_and_closes(studio):
    app,engine,bridge,vm,window,messages=studio
    window.resize(960,540);pump(app,.15)
    assert QMetaObject.invokeMethod(window,'toggleInspector')
    pump(app,.3)
    drawer=window.findChild(QObject,'measurementDrawer')
    assert drawer and drawer.property('visible') is True
    close=[b for b in window.findChildren(QQuickItem,'collapseInspectorButton') if b.isVisible()]
    assert close and close[-1].width()>=44
    assert QMetaObject.invokeMethod(close[-1],'clicked')
    pump(app,.3)
    assert drawer.property('visible') is False
    assert messages==[]


def test_native_dpi_migration_does_not_override_system_scale(tmp_path,monkeypatch):
    import main,os
    folder=tmp_path/'ui';folder.mkdir()
    path=folder/'ui_settings.json'
    path.write_text(json.dumps({'uiScale':.75,'fontScale':.75,'presentation75Applied':True}),encoding='utf-8')
    monkeypatch.setenv('SIXMIC_USER_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('QT_SCALE_FACTOR','1.5')
    main.apply_saved_ui_scale()
    settings=json.loads(path.read_text(encoding='utf-8'))
    assert os.environ['QT_SCALE_FACTOR']=='1.5'
    assert settings['uiScale']==settings['fontScale']==1
    assert settings['nativeInstrumentUiApplied'] is True
    settings['fontScale']=1.05
    path.write_text(json.dumps(settings),encoding='utf-8')
    main.apply_saved_ui_scale()
    assert json.loads(path.read_text(encoding='utf-8'))['fontScale']==1.05


@pytest.mark.parametrize('dpi',[1,1.25,1.5,2])
def test_canvas_pixel_bounds_match_logical_chart_at_each_dpi(dpi):
    result=subprocess.run([sys.executable,str(APP/'ui/tools/verify_chart_dpi.py'),'--dpi',str(dpi)],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(result.stdout)['pass'] is True


def test_scientific_readout_keeps_tiny_nonzero_values(qapp):
    engine=QJSEngine()
    source=(APP/'ui/qml/components/charts/ChartUtil.js').read_text(encoding='utf-8').replace('.pragma library','')
    result=engine.evaluate(source+'\n[fmtReadout(1.23e-20),fmtReadout(0),fmtReadout(4294967295),fmtReadout(1.234,"%.2f")];')
    assert not result.isError()
    values=result.toVariant()
    assert float(values[0])>0
    assert values[1:]==['0','4294967295','1.23']

def test_measurement_export_and_png_use_actual_ui_hooks(studio,monkeypatch):
    w=bind(studio,monkeypatch)
    app,engine,bridge,vm,window,messages=studio
    raw={'featureId':'stft','jobId':w['jobId'],'sourceKind':'test-fixture','totalWords':2,
         'words':[0x3f800000,0x40000000],'configuration':{'generation':'9007199254740993'},'schema':{'encoding':'float32'}}
    monkeypatch.setattr(vm._feature_facade,'export_raw',lambda fid:copy.deepcopy(raw))
    vm.exportFeatureRaw('stft')
    until=time.monotonic()+3
    while not list((vm.user_root/'exports').glob('*/metadata.json')) and time.monotonic()<until:pump(app,.05)
    paths=list((vm.user_root/'exports').glob('*/metadata.json'))
    assert paths and list(paths[0].parent.glob('*raw_words.csv'))
    chart=[x for x in window.findChildren(QQuickItem,'featureChart') if x.isVisible()][-1]
    assert QMetaObject.invokeMethod(chart,'saveImage')
    until=time.monotonic()+3
    while not list((vm.user_root/'exports/charts').glob('*.png')) and time.monotonic()<until:pump(app,.05)
    png=list((vm.user_root/'exports/charts').glob('*.png'))
    assert png
    image=QImage(str(png[0]))
    assert image.height() >= int(chart.height())
    assert image.height() > chart.property('contentItem').height() # Includes title/source.
    assert messages==[]

def test_event_export_keeps_fixture_label_and_nonzero_captured_audio(studio,tmp_path):
    from test_measurement_exports import event_file
    app,engine,bridge,vm,window,messages=studio
    path,_,_=event_file(tmp_path)
    vm._events=[{'eventId':'7','sourceKind':'test-fixture','filePath':str(path)}]
    vm.exportEventData('7')
    until=time.monotonic()+3
    while not list((vm.user_root/'exports').glob('*/metadata.json')) and time.monotonic()<until:pump(app,.05)
    exported=list((vm.user_root/'exports').glob('*/metadata.json'))
    assert exported
    meta=json.loads(exported[0].read_text(encoding='utf-8'))
    assert meta['sourceKind']=='test-fixture' and meta['fixture'] is True
    audio=list(exported[0].parent.glob('*.wav'))
    assert audio
    with wave.open(str(audio[0]),'rb') as f:
        assert f.getsampwidth()==3 and any(f.readframes(f.getnframes()))
    assert messages==[]
