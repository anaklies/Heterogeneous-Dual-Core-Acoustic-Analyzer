"""Enrich measured PL plans with the actual runtime interface; no DSP/test."""
from pathlib import Path
import json,csv
HERE=Path(__file__).resolve().parent
r=json.loads((HERE/'registry/REGISTRY.json').read_text(encoding='utf-8'))
special={
 'io_pcm':{'samples':{'default':2048,'range':[2048,1000000],'type':'uint32','description':'2048 uses immutable P0 snapshot; larger captures a verified contiguous record'},'channels':{'default':6,'enum':[1,6],'description':'For long capture; channel selects mono input when channels=1'}},
 'stft':{'frames':{'default':8,'range':[1,16],'type':'uint32','description':'Actual retained PL PSD frames, with sample-index axis'}},
 'room_decay':{'stimulus':{'required':True,'enum':['clap','impulse']}},
 'room_clarity':{'stimulus':{'required':True,'enum':['clap','impulse']}},
 'spectral_decay':{'stimulus':{'required':True,'enum':['clap','impulse']}},
 'stipa_experimental':{'referenceJobId':{'required':True,'type':'string','description':'Completed io_pcm mono720000 capture of declared active reference'},'testSignalConfirmed':{'required':True,'requiredValue':True}},
 'relative_insulation':{'action':{'enum':['reference','measure'],'default':'measure'},'referenceJobId':{'required':'measure','type':'string'},'confirmed':{'required':'measure','requiredValue':True,'description':'Same excitation and measurement chain declared by user'},'channel':{'default':0,'enum':[0],'description':'Current named octave reference producer is channel0'}},
 'spectrum_freeze':{'action':{'enum':['reference','compare'],'default':'compare'},'referenceJobId':{'required':'compare','type':'string'},'channel':{'default':0,'range':[0,5],'type':'uint32','description':'Selected PL power snapshot channel; matching reference required'}},
 'relative_limit':{'action':{'enum':['reference','compare'],'default':'compare'},'referenceJobId':{'required':'compare','type':'string'},'channel':{'default':0,'range':[0,5],'type':'uint32','description':'Selected PL power snapshot channel; matching reference required'}},
 'frequency_time_weighting':{'timeResponse':{'default':False,'type':'bool','description':'false=A/C/Z spectral relative level; true=captured exact unweighted FAST/SLOW/LeqFS'}},
}
for f in r['features']:
 prep_ref=f.get('acquisitionPreparationPlan')
 if prep_ref:
  preparation=json.loads((HERE/'registry'/prep_ref['file']).read_text(encoding='utf-8'))
  for key in ('inputWords','inputWordOffset'):
   assert isinstance(prep_ref.get(key),int) and prep_ref[key]>0 and prep_ref[key]==preparation[key],(f['featureId'],key,'invalid acquisition preparation reference')
 fid=f['featureId'];f.setdefault('params',{}).update(special.get(fid,{}));f['supportedParameterSets']=[v['params'] for v in f.get('variants',[])]
 mutable=list(special.get(fid,{}))
 if f['mode']=='p0':
  f['params'].setdefault('channel',{'default':0,'range':[0,5],'type':'uint32'})
  mutable.append('channel')
 if fid=='directed_das':mutable+=['azimuth_deg','elevation_deg']
 f.setdefault('parameterPolicy',{})['runtimeMutableParams']=mutable
 f['schema']['producerLayout']=f.get('output',{}).get('metadata',f.get('output',{}))
 if fid in ('levels_core','levels_extended'):
  f['schema']={'kind':'scalars','fields':['rms_FS','peak_FS','peakToPeak_FS','mean_FS','rms_dBFS','crest','clipCount','nonzeroValid'],'axes':{'channels':6,'channelStrideWords':8},'units':'FS, dBFS, ratio, count','validity':'Same immutable PL frame; silence nonzeroValid0 suppresses dBFS'}
 if fid=='io_pcm':f['schema']={'kind':'waveform','encoding':'s24 signextended LE32','fields':['PCM24'],'axes':{'channels':'1 or6','channelMajor':True,'sampleIndex':'configuration/capture metadata'},'units':'digital signed24 counts','validity':'No silent overwrite or gap; finite device capture only'}
 if fid=='spatial_interface':f['schema']={'kind':'capability','fields':[],'axes':{},'units':'none','validity':'Interface description only; use directed_das/full_das for manual spatial measurements. No automaticDOA'}
 if fid=='noise_rating':
  extra={'referenceConfirmed':{'required':True,'requiredValue':True},'referenceOffsetDb':{'required':True,'range':[-200,200],'type':'float32'},'calibrationSource':{'required':True,'type':'nonempty string','description':'Explicit nominal reference explanation; no certified SPL claim'}}
  f['params'].update(extra);f['parameterPolicy']['runtimeMutableParams']+=list(extra)
 f['interface']={'start':'feature.start','status':'feature.get','result':'feature.result','stop':'feature.stop','source':'PL hardware data only; fixture explicitly labelled','hardwareAccepted':False}
r['interfaceVersion']='echo-features-1';r['networkVersion']=1;r['controlPort']=48120;r['binaryPort']=48121
(HERE/'registry/INTERFACE_REGISTRY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with (HERE/'51_FEATURE_CALLS.csv').open('w',encoding='utf-8-sig',newline='') as file:
 fields=['featureId','name','tier','mode','controlPort','startOp','params','inputRequirements','plProducer','plPlan','p1Route','plOutput','parameterPolicy','resultSchema','getOp','resultOp','stopOp','softwareState','hardwareState'];w=csv.DictWriter(file,fields);w.writeheader()
 for f in r['features']:w.writerow(dict(featureId=f['featureId'],name=f['name'],tier=f['tier'],mode=f['mode'],controlPort=48120,startOp='feature.start',params=json.dumps(f['params'],ensure_ascii=False),inputRequirements=json.dumps(f['input'],ensure_ascii=False),plProducer=f.get('producer',''),plPlan=json.dumps(f.get('executionPlan',{}),ensure_ascii=False),p1Route=json.dumps(f.get('defaultP1Route',{}),ensure_ascii=False),plOutput=json.dumps(f.get('output',{}),ensure_ascii=False),parameterPolicy=json.dumps(f['parameterPolicy'],ensure_ascii=False),resultSchema=json.dumps(f['schema'],ensure_ascii=False),getOp='feature.get',resultOp='feature.result',stopOp='feature.stop',softwareState='IMPLEMENTED_DEVICE_PATH',hardwareState='NOT_TESTED'))
lines=['# 51项调用接口清单','', '全部使用PS控制口48120，网络协议sixmic-analysis v1。新增功能操作feature.list/start/get/result/stop；不改变SMA1或MMIO v3。PC须将这5个操作加入允许列表。','', '调用方式统一为feature.start({featureId,params,controlToken})，取得jobId后以feature.get轮询；completed后feature.result分页读取原始u32结果及schema。stop只请求安全停止，须等canceled。','', '|序号|featureId|功能|执行路径|输入/调用前提|','|---|---|---|---|---|']
for i,f in enumerate(r['features'],1):
 req='；'.join(f.get('input',{}).get('requires',[]))
 if f['featureId'] in special:req+=('；' if req else '')+'额外参数：'+','.join(special[f['featureId']])
 lines.append(f"|{i}|`{f['featureId']}`|{f['name']}|{f['mode']}|{req or '已初始化的真实PL输入；按schema有效位显示'}|")
lines+=['','所有参数、支持的预编译组合、单位、索引、有效性及输入限制以INTERFACE_REGISTRY.json和51_FEATURE_CALLS.csv为准。所有硬件声学结果仍需在实物上确认；软件通路检查不证明数值精度。','', 'P1固定profile由已命名服务产生数据；非默认通道、配对等选择仅接受supportedParameterSets列出的组合，手动DAS角度等显式runtimeMutableParams除外。不得静默忽略或在PC重算不支持的值。']
(HERE/'51_FEATURE_CALLS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('INTERFACE_CATALOG_WRITTEN',len(r['features']))
