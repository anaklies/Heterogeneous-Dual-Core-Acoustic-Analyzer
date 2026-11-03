from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from html import escape
import math

OUT=Path(__file__).resolve().parents[1]/'data/architecture'
OUT.mkdir(parents=True,exist_ok=True)
W,H,S=1680,1120,2
im=Image.new('RGB',(W*S,H*S),'#f3f6fb');d=ImageDraw.Draw(im)
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',f'<rect width="{W}" height="{H}" fill="#f3f6fb"/>']
def box(x,y,w,h,fill,stroke='#d5deeb',radius=18):
 d.rounded_rectangle([x*S,y*S,(x+w)*S,(y+h)*S],radius=radius*S,fill=fill,outline=stroke,width=2*S)
 svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
def text(x,y,t,size=23,color='#23364e',bold=False,anchor='left'):
 font=ImageFont.truetype('C:/Windows/Fonts/'+('msyhbd.ttc' if bold else 'msyh.ttc'),size*S)
 if anchor=='middle':x-=d.textlength(t,font=font)/S/2
 d.text((x*S,y*S),t,font=font,fill=color)
 svg.append(f'<text x="{x}" y="{y+size*.91}" font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{escape(t)}</text>')
def arrow(points,color='#47627f',both=False,width=3):
 d.line([(int(x*S),int(y*S)) for x,y in points],fill=color,width=width*S,joint='curve')
 svg.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+f'" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"/>')
 def tip(a,b):
  vx,vy=b[0]-a[0],b[1]-a[1];l=math.hypot(vx,vy);ux,uy=vx/l,vy/l
  p=[b,(b[0]-12*ux-5*uy,b[1]-12*uy+5*ux),(b[0]-12*ux+5*uy,b[1]-12*uy-5*ux)]
  d.polygon([(int(x*S),int(y*S)) for x,y in p],fill=color)
  svg.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in p)+f'" fill="{color}"/>')
 tip(points[-2],points[-1])
 if both:tip(points[1],points[0])

text(65,35,'ECHO｜双核共享计算架构与功能总览',38,bold=True)
text(67,91,'一套采集链 · 两个共享计算核 · 45项声学分析功能',23,'#61758d')
box(65,155,285,140,'#e5efff','#a9c4e9')
text(90,175,'六路数字麦克风',26,bold=True)
text(90,223,'INMP441 · 同步I²S',21)
text(90,255,'六通道连续采集 · 48 kHz',19)

box(385,155,1230,685,'#ffffff','#9cb4d3',23)
text(415,175,'Zynq-7020 · PL共享计算',28,'#25496e',True)
text(1190,182,'核心声学运算在FPGA完成',18,'#61758d')
box(425,235,1150,75,'#edf3fa')
text(450,247,'同步采集 → FIFO / 跨时钟域 → PCM环形缓存与窗口',25,bold=True)
text(450,280,'持续保留输入数据，向共享计算核提供一致的数据窗口',18,'#61758d')
arrow([(350,225),(367,225),(367,272),(425,272)])

box(425,345,1150,80,'#e7eefb','#b5c8e7')
text(450,355,'统一任务调度器',25,bold=True)
text(450,391,'P0 必需实时任务    /    P1 周期任务    /    P2 用户调用任务',21,'#42658b')
arrow([(1000,310),(1000,345)])

box(425,480,525,166,'#e7f6f0','#87c2ab')
text(450,495,'共享核 ①  FFT变换核',27,'#1c6552',True)
text(450,541,'六通道复用 · FFT / IFFT',23)
text(450,582,'频谱基础量 + 高级分析的变换服务',20,'#47756a')
box(1050,480,525,166,'#e9efff','#a6b5e6')
text(1075,495,'共享核 ②  标量分析核',27,'#3a4b8b',True)
text(1075,541,'加载算法指令 · 分块执行与恢复',23)
text(1075,582,'统计、频带、相关、包络及房间指标',20,'#596a9e')
arrow([(687,425),(687,480)],'#377f6c')
arrow([(1312,425),(1312,480)],'#596eac')
arrow([(950,560),(1050,560)],both=True)
text(1000,522,'协同',17,'#61758d',anchor='middle')

box(425,710,1150,85,'#edf3fa')
text(450,721,'共享数据与结果区 · DDR',25,bold=True)
text(450,759,'PCM / FFT窗口 / 算法状态 / 事件音频  ｜  帧号、时间戳、版本与有效性',19,'#61758d')
arrow([(687,646),(687,710)],both=True)
arrow([(1312,646),(1312,710)],both=True)

box(65,340,285,500,'#ffffff')
text(90,362,'45项功能 · 7组',27,bold=True)
groups=['采集、电平与输入质量','频谱、时频与频带分析','多通道相关、相干与相位','周期、谐波与调制分析','房间衰减与清晰度','频谱对照及噪声评价','环境变化事件与音频留证']
for i,g in enumerate(groups):
 y=423+i*53
 d.ellipse([90*S,(y+8)*S,98*S,(y+16)*S],fill='#6b88aa')
 svg.append(f'<circle cx="94" cy="{y+12}" r="4" fill="#6b88aa"/>')
 text(109,y,g,19)

box(385,905,640,155,'#e9f0fa','#b2c4dd')
text(412,920,'PS · 双核ARM / Linux',26,bold=True)
text(412,966,'7寸触摸屏 · 参数控制 · 传感器读数',22)
text(412,1004,'事件文件 / SD存储 · 网络服务 · 故障管理',20,'#526d8d')
box(1195,905,420,155,'#ffffff','#b2c4dd')
text(1220,920,'PC · ECHO分析软件',26,bold=True)
text(1220,966,'实时图表 · 功能调用',22)
text(1220,1004,'事件下载 · 数据导出',22)
arrow([(705,795),(705,905)],both=True)
text(727,855,'AXI / MMIO + DDR结果',18,'#61758d')
arrow([(1025,988),(1195,988)],both=True)
text(1110,918,'PS以太网',19,'#42658b',anchor='middle')
text(1110,948,'48120 / 48121',17,'#61758d',anchor='middle')
text(65,920,'共享的价值',23,bold=True)
text(65,963,'算法轮流使用同一套硬件，',18,'#61758d')
text(65,996,'按任务分配计算与缓存，',18,'#61758d')
text(65,1029,'兼顾功能数量与资源开销。',18,'#61758d')
svg.append('</svg>')
(OUT/'ECHO_双核共享架构与功能总览.svg').write_text('\n'.join(svg),encoding='utf-8')
im.save(OUT/'ECHO_双核共享架构与功能总览.png',dpi=(220,220))
print(OUT)
