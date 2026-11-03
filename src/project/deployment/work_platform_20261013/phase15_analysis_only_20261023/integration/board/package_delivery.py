"""Copy the gated engineering candidate; do not build, simulate or program hardware."""
from pathlib import Path
import csv, hashlib, json, re, shutil, zipfile

ROOT = Path(__file__).resolve().parents[5]
I = Path(__file__).resolve().parents[1]
P15 = I.parent
OUT = ROOT / 'deployment/releases/SixMic3D_PL_Analysis_RC1_20261024'
REPORTS = ROOT / 'tmp/p24_shared_instrument_board/reports'

def copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for data in iter(lambda: f.read(1024*1024), b''):
            h.update(data)
    return h.hexdigest()

def main():
    log = (I/'results/finish_delivery.log').read_text(errors='replace')
    if '\nDELIVERY_BIT_XSA_ARCHIVE_DONE\n' not in log.replace('\r',''):
        raise SystemExit('No completed build/export marker; no release freeze performed')
    required = ['sixmic_analysis_rc1.bit','sixmic_analysis_rc1.xsa','recoverable_project.zip']
    for name in required:
        if not (OUT/'hardware'/name).is_file():
            raise SystemExit('Missing real generated artifact: '+name)
    for name in ['sixmic_analysis_rc1.xsa','recoverable_project.zip']:
        with zipfile.ZipFile(OUT/'hardware'/name) as z:
            if z.testzip() is not None:
                raise SystemExit('Corrupt archive: '+name)
    utilization=(REPORTS/'utilization.rpt').read_text()
    def used(label):
        m=re.search(r'^\|\s*'+re.escape(label)+r'\s*\|\s*([\d.]+)',utilization,re.M)
        if not m: raise SystemExit('Missing utilization '+label)
        v=float(m[1]);return int(v) if v.is_integer() else v
    timing=(REPORTS/'timing.rpt').read_text()
    m=re.search(r'WNS\(ns\).*?\n\s*-.*?\n\s*([\d.-]+)\s+([\d.-]+)\s+\d+\s+\d+\s+([\d.-]+)\s+([\d.-]+)',timing,re.S)
    if not m: raise SystemExit('Missing timing summary')
    wns,tns,whs,ths=map(float,m.groups())
    if min(wns,whs)<0 or tns!=0 or ths!=0: raise SystemExit('Timing gate not met')
    cdc=(REPORTS/'cdc.rpt').read_text(); counts=[0,0,0,0]
    for line in cdc.splitlines():
        if re.match(r'^(Warning|Info|Critical)',line):
            nums=re.findall(r'(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$',line)
            if nums:
                values=list(map(int,nums[0]));counts=[a+b for a,b in zip(counts,values[:4])]
    if counts[2] or counts[3]: raise SystemExit('CDC unsafe/unknown endpoints')
    drc=(REPORTS/'drc.rpt').read_text()
    if re.search(r'\|\s*[^|]+\|\s*(?:Error|Critical Warning)\s*\|',drc):
        raise SystemExit('DRC severity requires review')
    meta=json.loads((I/'RUNTIME_CANDIDATE.json').read_text())
    meta.update(candidate='analysis-rc1-20261024',scope='shared PL engineering candidate; physical verification pending',
                hardwareVersion='0x82000001',protocolVersion=3,capabilities='0x00000003',
                bitstreamGenerated=True,xsaGenerated=True,recoverableProjectGenerated=True,
                releaseStatus='ENGINEERING_RC',s7Complete=False,readyToFlash=False,
                automaticDOA=False,programImplementationComplete=True,
                allAlgorithmsPorted=False,physicalBoardTested=False)
    meta['resources']={'scope':'same complete routed design used for delivered bitstream and XSA',
        'LUT':used('Slice LUTs'),'LUTpercent':round(used('Slice LUTs')/53200*100,2),
        'FF':used('Slice Registers'),'Slice':used('Slice'),
        'SlicePercent':round(used('Slice')/13300*100,2),'DSP':used('DSPs'),
        'BRAM36Equivalent':used('Block RAM Tile'),'controlSets':used('Unique Control Sets'),
        'WNSns':wns,'TNSns':tns,'WHSns':whs,'THSns':ths,'placeRoute':True,
        'CDCendpoints':counts[0],'CDCsafe':counts[1],'CDCunsafe':counts[2],'CDCunknown':counts[3],
        'DRCerrors':0,'externalInputDelayMissing':8,'externalOutputDelayMissing':8,
        'externalElectricalTimingClosed':False,'methodologyWarningsRetained':True}
    meta['validation'].update(timingModelFFTJobCycles=260000,timingFeatureModelCycles=200000,
        timingModelMaxProcessingCycles=1760015,timingControlWindows=6,timingControlPublications=3,
        timingControlOutputHz=50000000/4265800,actualScalar512Cycles=24889,
        actualScalarMemoryDense512Cycles=29905,eventRecorderJointRTL=True,
        FFTslotHeaderRTL=True,rawCursorRTL=True,fullRuntimeContinuousPCM_RTL=False)
    meta['STIPA']={'fullNativeGraph':'PASS','samplesPerTrace':720000,'stages':101,
        'chunks':4893057,'CPUSeconds':254.8013016,'index':0.5000050068,
        'fullRTLGraph':False,'physicalBoard':False,'realtime':False,'certified':False}
    meta['remaining']=[
      'External I2S/I2C/LCD electrical timing: 8 inputs and 8 outputs lack board delay bounds; not signed off',
      'Physical capture, sensors, LCD, PS watchdog reset and sustained board operation not tested',
      'Linux reserved-memory/UIO/PS gateway and PetaLinux2023.1 versus XSA2025.2 compatibility not verified',
      'All-service complete RTL performance not claimed; STIPA remains slow experimental captured-data task']
    meta['optimization']={'strategy':'one shared FFT/IFFT and bounded scalar core; area-oriented shared DDR AXI',
        'priorRoutedLUT':43029,'priorRoutedFF':46457,'priorRoutedSlice':13256,
        'LUTsaved':43029-used('Slice LUTs'),'FFsaved':46457-used('Slice Registers'),
        'SliceSaved':13256-used('Slice'),'precisionReduced':False,
        'noFurtherTinyGainSearch':True,'controlPackingExperiment':'rejected: no area gain'}
    (I/'RUNTIME_CANDIDATE.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    path=I/'FUNCTION_EXECUTION_MAP.csv'
    with path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);fields=list(reader.fieldnames);rows=list(reader)
    for field in ['sharedBackendInRoutedDesign','executionMode']:
        if field not in fields: fields.append(field)
    for row in rows:
        row['sharedBackendInRoutedDesign']='True' if row['id']!='srpdnn_main' else 'False'
        row['executionMode']='P2_USER_SELECTED' if row['tier']=='P2' else 'P1_CAROUSEL'
        if row['id'] in {'io_pcm','levels_core','data_continuity','fft','stft','signal_quality','levels_extended','event_trigger','spatial_interface'}:
            row['executionMode']='P0_BUILTIN'
        if row['id']=='psd': row['executionMode']='P0_PERIODOGRAM_PLUS_P1_WELCH'
        if row['id']=='srpdnn_main': row['executionMode']='REMOVED'
        row['wholeBoardAccepted']='False'
        if row['hardwareState']=='CONNECTED_PHYSICAL_CANDIDATE':
            row['integrationStatus']='FINAL_RC1_ROUTED_BIT_XSA; physical-board functional verification NOT TESTED'
        if row['id']=='frequency_time_weighting': row['newMicroprogram']='noise_services.py + recorded_time_response.py'
        if row['id']=='stipa_experimental': row['newMicroprogram']='stipa_graph.py + stipa_offline.py'
        if row['id']=='signal_quality': row['name']='输入有效性与新鲜度（无自动方向）'
        if row['id']=='spatial_interface': row['name']='分析结果与手动空间图接口'
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    # Preserve source-relative includes; no native test DLL is a production DSP dependency.
    suffixes={'.sv','.v','.xdc','.cpp','.h','.vh','.cfg','.tcl','.py','.ps1','.c','.md','.csv'}
    for f in I.rglob('*'):
        if not f.is_file() or f.suffix.lower() not in suffixes:
            continue
        rel=f.relative_to(I)
        if any(x in {'results','__pycache__'} for x in rel.parts):
            continue
        copy(f,OUT/'source'/f.relative_to(ROOT))
    deps=[
      'deployment/environment_20261009/sensor_i2c_hub.sv',
      'deployment/environment_20261009/i2c_transaction_master.sv',
      'deployment/environment_20261009/air_sound_speed.sv',
      'deployment/environment_20261009/air_coeff.mem',
      'deployment/work_platform_20261013/phase14_room_and_pl_20261021/pl_system/hls_job_bridge.sv',
      'deployment/work_platform_20261013/phase14_room_and_pl_20261021/pl_system/axi_activity_guard.sv',
      'deployment/work_platform_20261013/phase14_room_and_pl_20261021/pl_system/analysis_dma/memory_ports.h',
      'deployment/work_platform_20261013/phase13_pl_port_20261021/rtl/control/pcm_axi_ring_writer.sv',
      'deployment/work_platform_20261013/phase13_pl_port_20261021/rtl/control/mic_health.sv',
      'pl/board/i2s_timing_gen.v','pl/board/i2s_rx_6ch.v']
    for rel in deps:
        copy(ROOT/rel,OUT/'source'/rel)
    for folder, extensions in [(P15/'event',{'.sv','.v'}),(P15/'fft',{'.h'})]:
        for f in folder.iterdir():
            if f.is_file() and f.suffix in extensions:
                copy(f,OUT/'source'/f.relative_to(ROOT))
    for folder in ['p20_scalar','p20_stream_fft']:
        archives=list((ROOT/'tmp'/folder/'hls/impl/ip').glob('*.zip'))
        if len(archives)!=1: raise SystemExit('Expected one HLS IP export: '+folder)
        copy(archives[0],OUT/'hardware/hls_ip'/archives[0].name)
    for f in (I/'profiles/default').iterdir():
        if f.is_file(): copy(f,OUT/'profiles/default'/f.name)
    profile=json.loads((OUT/'profiles/default/PROFILE.json').read_text())
    if digest(OUT/'profiles/default/profile_init.smi')!=profile['image_sha256']:
        raise SystemExit('Profile initializer hash mismatch')
    for name in ['libsixmic_host_arm.a','sixmic-supervisor-arm','HOST_ARM_COMMANDS.json','ARM_BUILD_COMMAND.json']:
        copy(I/'host'/name,OUT/'sdk'/name)
    for f in (I/'host').iterdir():
        if f.suffix in {'.c','.h','.md'}: copy(f,OUT/'sdk'/f.name)
    for name in ['README.md','easter-egg.json','easter-egg.lcd','easter-egg.png',
                 'sixmic_lcd_player.cpp','sixmic-lcd-player','sixmic-lcd-easter-egg.service',
                 'hardware_evidence.json','verification.json']:
        copy(P15/'lcd'/name,OUT/'lcd'/name)
    for f in REPORTS.glob('*.rpt'):
        if not f.name.startswith('synth_'):
            copy(f,OUT/'evidence/implementation'/f.name)
    copy(ROOT/'tmp/p24_shared_instrument_board/project/instrument_board.runs/synth_1/design_1_wrapper_utilization_synth.rpt',
         OUT/'evidence/implementation/synth_utilization.rpt')
    # Existing evidence only; do not launch another algorithm test.
    logs=['shared_budget.log','direct_complex_safe_sim.log','direct_scalar_batch_safe_sim.log',
          'direct_scalar_memory_batch_safe_sim.log','tb_event_chain_cursor_sim.log','sensor_disconnected.log']
    for name in logs:
        copy(I/'results'/name,OUT/'evidence'/name)
    records=['actual_fft_rtl.json','actual_scalar_rtl.json','scalar_math.json',
             'final_invocation_native.json','final_profile_mode_native.json',
             'event_chain_validation.json','profile_layout_native.json','stipa_full_native.json',
             'control_packing_decision.json','frequency_drift_native.json',
             'statistics_native.json','recorded_time_response_native.json',
             'linear_periodic_native.json','room_bands_native.json','das_map_native.json']
    for name in records:
        copy(I/'results'/name,OUT/'evidence'/name)
    copy(I/'results/finish_delivery.log',OUT/'evidence/finish_delivery.log')
    for name in ['RUNTIME_CANDIDATE.json','FUNCTION_EXECUTION_MAP.csv','DATA_AND_SCHEDULING.md']:
        copy(I/name,OUT/name)
    # This is a portable *hardware* archive. ARM/Linux startup compatibility is not asserted.
    copy(ROOT/'tmp/p24_shared_instrument_board/routed.dcp',OUT/'hardware/routed.dcp')
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name!='SHA256SUMS.txt')
    manifest=''.join(f'{digest(p)}  {p.relative_to(OUT).as_posix()}\n' for p in files)
    (OUT/'SHA256SUMS.txt').write_text(manifest,encoding='utf-8')
    print(json.dumps({'status':'PACKAGED','files':len(files),'bytes':sum(p.stat().st_size for p in files),
                      'directory':str(OUT),'physicalBoardTested':False},ensure_ascii=False))

if __name__=='__main__': main()
