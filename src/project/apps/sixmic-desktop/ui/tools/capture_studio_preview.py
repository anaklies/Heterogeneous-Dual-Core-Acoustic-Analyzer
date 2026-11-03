"""Native Qt presentation fixtures only. No device calls, no algorithm/board evidence."""
from __future__ import annotations
import argparse, copy, json, math, os, sys, time
from pathlib import Path

APP_ROOT=Path(__file__).resolve().parents[2]
REPO=APP_ROOT.parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--output',default=str(APP_ROOT/'docs/frontend/screenshots/studio_redesign_20261026'))
parser.add_argument('--dpi',type=float,default=1)
parser.add_argument('--all',action='store_true')
args=parser.parse_args()
OUT=Path(args.output);OUT.mkdir(parents=True,exist_ok=True)
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software'
os.environ['QT_QPA_FONTDIR']=r'C:\Windows\Fonts'
os.environ['QT_SCALE_FACTOR']=str(args.dpi)
os.environ['SIXMIC_USER_DATA_DIR']=str(OUT/'_userdata')
sys.path[:0]=[str(APP_ROOT),str(APP_ROOT/'backend')]
from PySide6.QtCore import QPointF, QUrl, qInstallMessageHandler
from PySide6.QtGui import QImage,QPainter,QColor,QFont
from PySide6.QtQuick import QQuickItem
import main as appmain

messages=[]
def handler(mode,context,message):
    if str(message).startswith(('QFontDatabase','Context2D: The font families','FT_New_Face','This plugin does not support propagateSizeHints')):return
    messages.append(str(message))
qInstallMessageHandler(handler)
app,engine,bridge,vm,theme,images,_=appmain.create_application()
def pump(seconds=.12):
    until=time.monotonic()+seconds
    while time.monotonic()<until:app.processEvents();time.sleep(.006)
theme.set_mode('dark');theme.set_font_scale(1)
vm.setInspectorCollapsed(True)
spec=json.loads((APP_ROOT/'ui/config/feature_view_spec.json').read_text(encoding='utf-8'))
colors=theme.channelColors
selected={'fid':'fft'}
freqs=[20*1000**(i/511) for i in range(512)]
def axis(lo,hi,label,unit='',scale='linear'):return {'min':lo,'max':hi,'label':label,'unit':unit,'scale':scale}
def line(name,points,c=0,**extra):return {'name':name,'points':points,'color':colors[c%6],**extra}
def spectrum(c=0):
    return [[f,-78+34*math.exp(-((math.log10(f)-2.65)/.7)**2)+13*math.exp(-((math.log10(f)-3.25)/.17)**2)+3*math.sin(i*.31+c)+1.6*math.sin(i*1.91+c)] for i,f in enumerate(freqs)]
def chart_for(fid):
    f=spec['features'][fid];kind=f['chart']
    chart={'kind':kind,'title':f['shortZh'],'subtitle':'','units':f.get('units',''),'chartRevision':1,
           'xAxis':axis(20,20000,'频率','Hz','log'),'yAxis':axis(-100,0,'电平','dBFS'),
           'series':[line('CH1',spectrum(),0)],'scalarRows':[]}
    if kind in ('spectrum','zoom-spectrum','beam-spectrum'):
        if fid in ('frequency_tracking','frequency_drift','centroid','flatness','spectral_flux','energy_change','band_tracking'):
            chart['xAxis']=axis(0,10,'时间','s')
            chart['yAxis']=axis(0,1,'相对值','')
            chart['series']=[line(f['shortZh'],[[i/25,.45+.12*math.sin(i*.071)+.19*math.exp(-((i-130)/13)**2)] for i in range(251)])]
        else:chart['series']=[line('CH1',spectrum(),0),line('CH2',[[x,y-4+2*math.sin(i*.032)] for i,(x,y) in enumerate(spectrum(1))],1)]
    if kind in ('spectral-decay','room-decay','room-clarity'):
        chart['xAxis']=axis(0,.8,'时间','s');chart['yAxis']=axis(-80,0,'衰减','dB')
        chart['series']=[line('衰减曲线',[[i/500,-min(76,i*.2)+.4*math.sin(i*.2)] for i in range(401)])]
        chart['scalarRows']=[{'label':'EDT','value':.42,'unit':'s','valid':True},{'label':'T20','value':.46,'unit':'s','valid':True},{'label':'T30','value':.48,'unit':'s','valid':True}]
    if kind=='lag-series':
        chart['xAxis']=axis(-20,20,'时延','ms');chart['yAxis']=axis(-1,1,'相关幅度','relative')
        chart['series']=[line('CH1 / CH2',[[i/10, math.exp(-((i/10-2.3)/1.2)**2)*math.cos(i*.17)-.12*math.exp(-((i/10+4)/2)**2)] for i in range(-200,201)])]
        chart['markers']=[{'x':2.3,'y':.8,'label':'2.3 ms'}]
    if kind in ('bands','bars-readout','harmonic-bars','insulation-bars','noise-rating'):
        centers=[31.5,63,125,250,500,1000,2000,4000,8000,16000]
        chart['categories']=[{'label':str(f),'centerFrequency':f,'value':-69+35*math.exp(-((i-4.8)/2.8)**2)+math.sin(i*1.4)*3,'valid':True} for i,f in enumerate(centers)]
        chart['xMode']='centerFrequency';chart['yAxis']=axis(-80,0,'频带电平','dBFS')
        chart['scalarRows']=[{'label':'总电平','value':-30.5,'unit':'dBFS','valid':True}]
        if kind=='harmonic-bars':
            chart['xAxis']=axis(1,8,'谐波阶次');chart['xMode']='category'
            chart['categories']=[{'label':'H'+str(i+1),'value':-18-i*7,'valid':True} for i in range(8)]
        if kind=='noise-rating':
            chart['curves']=[{'name':'参考曲线','points':[[f,-45+i*1.2] for i,f in enumerate(centers)]}]
    if kind=='waveform':
        chart.update({'series':[],'sampleRate':48009.775390625,'startSampleIndex':'9007199254740993','stacked':True,
            'channels':[{'name':'CH'+str(c+1),'color':colors[c], 'visible':True,'values':[.5*math.sin(i*.08+c)+.12*math.sin(i*.37+c) for i in range(1600)]} for c in range(6)]})
    if kind=='level-bars':
        chart['meters']=[{'label':'CH'+str(c+1),'color':colors[c],'value':-12-c*3,'peak':-9-c*3,'valid':True,'clip':False} for c in range(6)]
        chart['scale']={'min':-60,'max':0,'label':'电平','unit':'dBFS'}
    if kind=='stft':
        frames=[]
        for r in range(16):
            pts=[]
            for i in range(1025):
                f=20+(20000-20)*i/1024;lf=math.log10(f)
                db=-96+53*math.exp(-((lf-2.18)/.13)**2)*math.exp(-r/25)+42*math.exp(-((lf-2.85)/.1)**2)*math.exp(-r/14)+30*math.exp(-((lf-3.3)/.13)**2)*math.exp(-r/10)+2*math.sin(i*.6+r*.3)
                pts.append([f,db])
            frames.append({'time':r*.05,'sampleIndex':str(9007199254740993+r*2400),'points':pts})
        matrix=[[frames[c]['points'][r][1] for c in range(16)] for r in range(1025)]
        chart.update({'series':[],'frames':frames,'raster':{'matrix':matrix,'min':-100,'max':-20,'palette':'inferno'},
            'xAxis':axis(0,.75,'时间','s'),'yAxis':axis(20,20000,'频率','Hz','log'),
            'frequencyAxis':axis(20,20000,'频率','Hz','log'),'timeAxis':axis(0,.75,'时间','s'),
            'colorScale':{'min':-100,'max':max(p[1] for fr in frames for p in fr['points']),'palette':'magma','label':'PSD','unit':'dBFS/Hz'}})
    if kind=='das-map':
        az=[i*10 for i in range(36)];el=[-90+i*10 for i in range(19)]
        matrix=[[-42+38*math.exp(-((a-70)/40)**2-((e-20)/32)**2)+15*math.exp(-((a-245)/48)**2-((e+30)/30)**2) for a in az] for e in el]
        chart.update({'series':[],'raster':{'matrix':matrix,'azimuths':az,'elevations':el,'min':-45,'max':0,'palette':'viridis'},
            'points':[{'azimuthDeg':a,'elevationDeg':e,'power':matrix[j][i],'valid':True} for j,e in enumerate(el) for i,a in enumerate(az)],
            'azimuthRange':{'min':0,'max':360},'elevationRange':{'min':-90,'max':90},
            'colorScale':{'min':-45,'max':0,'palette':'viridis','label':'相对功率','unit':'dB'},'caption':'手动扫描 · 阵列本地坐标'})
    if kind in ('pair-spectra','coherence-phase','weighting'):
        chart['panels']=[{'title':'相干性' if kind=='coherence-phase' else 'CH1 / CH2 功率谱','series':[line('CH1 / CH2',[[f,.85-.32*math.exp(-((math.log10(f)-3.1)/.12)**2)+.02*math.sin(i*.17)] for i,f in enumerate(freqs)])],
            'xAxis':axis(20,20000,'频率','Hz','log'),'yAxis':axis(0,1,'相干性','')},
            {'title':'相位差','series':[line('相位',[[f,1.2*math.sin(math.log(f)*.7)] for f in freqs],2)],
             'xAxis':axis(20,20000,'频率','Hz','log'),'yAxis':axis(-math.pi,math.pi,'相位','rad')}]
    if kind=='ab-spectrum':
        chart['series']=[line('A reference',spectrum(),0,role='reference'),line('B current',[[x,y+4*math.exp(-((math.log10(x)-3.05)/.22)**2)] for x,y in spectrum()],1,role='current')]
        chart['deltaYAxis']=axis(-12,12,'差值','dB');chart['referenceLines']=[{'y':-40,'label':'相对阈值','dashed':True}]
    if kind in ('scalars','statistics'):
        chart['series']=[];chart['scalarRows']=[{'label':'采样连续性','value':'有效','unit':'','valid':True},{'label':'输入新鲜度','value':'新鲜','unit':'','valid':True},{'label':'有效样本','value':2048,'unit':'samples','valid':True},{'label':'采样缺口','value':0,'unit':'','valid':True}]
    if kind=='capability':chart.update({'series':[],'text':'提供设备结果与手动空间扫描的数据接口。此项目不执行自动声源定位。'})
    if kind=='events':chart.update({'series':[],'durationSeconds':120,'events':[{'position':.2,'label':'事件 01','kind':'info'},{'position':.57,'label':'事件 02','kind':'warn'}]})
    if kind=='stipa':chart.update({'series':[],'indexValue':.68,'indexValid':True,'indexUnit':'','stages':{'index':101,'total':101,'note':'示例阶段完成'},'scalarRows':[{'label':'实验指数','value':.68,'unit':'','valid':True}]})
    return chart

cache={fid:chart_for(fid) for fid in spec['features']}
facade=vm._feature_facade
original_entries=facade.entries
def entries(page):
    rows=original_entries(page)
    for r in rows:r.update({'available':True,'disabledReason':'','state':'completed','stateLabel':'已有结果','hasResult':True})
    return rows
facade.entries=entries
def workspace():
    fid=facade._runtime._open_feature or selected['fid'];f=spec['features'][fid]
    chart=cache[fid]
    return {'open':True,'featureId':fid,'page':f['page'],'name':f['name'],'shortName':f['shortZh'],'available':True,
        'state':'completed','stateLabel':'测量完成','sourceKind':'test-fixture','sourceLabel':'测试数据 · 非实测',
        'units':chart.get('units',''),'chart':chart,'variants':[],'references':{'hasReference':True},
        'flow':{'actions':[{'id':'run','label':'开始测量','enabled':True},{'id':'refresh','label':'重新读取','enabled':True},{'id':'save','label':'保存图像','enabled':True},{'id':'export','label':'导出数据','enabled':True}], 'confirmations':[], 'steps':0,'note':''},
        'validity':'此图使用前端展示夹具，仅验证布局和渲染，不代表设备或声学验收。','notes':[], 'hardwareState':'NOT_TESTED'}
facade.workspace=workspace
vm._source='test-fixture';vm._fixture_active=True
vm._connection['state']='connected';vm._connection['host']='展示夹具'
vm._events=[{'eventId':'9007199254740993','sourceKind':'test-fixture','frames':24000,'fileState':'stored'}, {'eventId':'9007199254740994','sourceKind':'test-fixture','frames':18000}]
vm._wave_ring=[c['values'] for c in chart_for('io_pcm')['channels']]
vm._audio_meta={'sampleRateHz':48009.775390625}
vm.dataChanged.emit()
window=engine.rootObjects()[0];window.showNormal();window.setMinimumSize(__import__('PySide6.QtCore',fromlist=['QSize']).QSize(1,1))
shots=[];bounds=[]
def grab(name,fid=None,size=(1920,1080),surface3d=False):
    if fid:
        selected['fid']=fid
        vm.setCurrentPage(spec['features'][fid]['page']);vm.openFeatureEntry(fid)
    window.resize(round(size[0]/args.dpi),round(size[1]/args.dpi));pump(.16)
    if surface3d:
        charts=[c for c in window.findChildren(QQuickItem,'featureChart') if c.isVisible() and c.property('kind')=='stft']
        if charts:
            charts[-1].setProperty('threeDActive',True)
        pump(.2)
    image=window.grabWindow();path=OUT/(name+'.png');image.save(str(path))
    surface=window.findChild(QQuickItem,'analysisChartSurface')
    if surface:
        p=surface.mapToScene(QPointF(0,0));bounds.append({'name':name,'x':p.x(),'y':p.y(),'w':surface.width(),'h':surface.height(),'window':[window.width(),window.height()]})
    shots.append({'name':name,'featureId':fid,'path':str(path),'pixels':[image.width(),image.height()],'sourceKind':'test-fixture','presentationOnly':True})

for fid in (list(spec['features']) if args.all else ['fft','stft','octave','coherence_phase','full_das','room_decay','stipa_experimental','event_trigger','io_pcm']):
    grab(fid,fid)
grab('waterfall','stft',surface3d=True)
grab('spectrum_1280','fft',(1280,800));grab('periodic_1280','fundamental',(1280,800))
for page in ['overview','recording','settings','diagnostics','about']:
    vm.setCurrentPage(page);pump(.1);grab(page,size=(1280,800))

hero=['fft','waterfall','stft','full_das']
sheet=QImage(1600,960,QImage.Format.Format_RGB32);sheet.fill(QColor('#080a0c'));p=QPainter(sheet)
for i,name in enumerate(hero):
    shot=QImage(str(OUT/(name+'.png')));x=(i%2)*800;y=(i//2)*480
    p.drawImage(x,y,shot.scaled(800,450));p.setPen(QColor('#c9d6de'));p.setFont(QFont('Segoe UI',12));p.drawText(x+12,y+472,name+' · TEST FIXTURE')
p.end();sheet.save(str(OUT/'preview_overview.png'))
manifest={'sourceKind':'test-fixture','hardwareState':'NOT_TESTED','presentationOnly':True,'dpi':args.dpi,'shots':shots,'chartBounds':bounds,'qmlWarnings':messages}
(OUT/'preview_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
vm.prepareExit();bridge.shutdown()
print(json.dumps({'shots':len(shots),'warnings':messages[:16],'output':str(OUT)},ensure_ascii=False))
sys.exit(1 if messages else 0)
