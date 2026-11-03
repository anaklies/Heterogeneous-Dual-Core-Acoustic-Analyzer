"""Bounded lifecycle tests, synthetic fixtures only, no acoustic claims."""
import copy,struct
from test_feature_runtime import Harness,CONFIG,spec,gateway_capture,registry,words_for,schema_for
from pc_client.live_fft import decode_live_frame,LIVE_WORDS

def test_p0_auto_runs_without_start_button(spec):
    h=Harness(spec,instrument_mode=True);h.rt.open('fft');h.tick(.05)
    assert h.gw.count('start')==1
    assert h.gw.take('start')['args']['featureId']=='fft'

def test_repeated_updates_keep_chart_and_stop(spec,gateway_capture,registry):
    h=Harness(spec,instrument_mode=True);h.rt.open('fft');h.tick(.05)
    data=words_for('fft',gateway_capture,registry);schema=schema_for('fft',gateway_capture,registry)
    for i in range(12):
        call=h.gw.take('start');cfg=dict(CONFIG,sourceFrame=str(i+1));jid=f'live-job-{i}'
        h.respond_start(call,jid,state='completed',configuration=cfg)
        h.deliver_result(jid,'fft',data,schema,configuration=cfg)
        assert h.workspace()['state']=='running'
        assert h.workspace()['chart']['series']
        assert len(h.rt._jobs)<=2
        if i<11:h.tick(.06)
    starts=h.gw.count('start');chart=h.workspace()['chart']['chartRevision'];h.rt.stop('fft');h.tick(1)
    assert h.gw.count('start')==starts
    assert h.workspace()['state']=='stopped'
    assert h.workspace()['chart']['chartRevision']==chart

def test_big_keeps_running_on_live_page_but_stops_for_next_big(spec):
    h=Harness(spec,instrument_mode=True);h.rt.on_page_changed('periodic');h.start('fundamental','big-1')
    h.rt.on_page_changed('spectrum')
    assert h.gw.count('stop')==0
    assert h.rt._background_feature=='fundamental'
    h.rt.open('cepstrum')
    assert h.gw.count('stop')==1
    assert h.gw.take('stop')['args']['jobId']=='big-1'

def test_stopping_missing_job_is_idempotent(spec):
    h=Harness(spec,instrument_mode=True);h.start('fundamental','big-1');h.rt.stop('fundamental');h.respond_error('stop','job_not_found',job_id='big-1')
    assert h.workspace()['state']=='stopped'
    assert 'fundamental' not in h.rt._live_requested

def test_live_wire_preserves_large_sample_indices():
    first=9007199254740993;h=[0x3154464c,1,123,4,1,0,0x473b89c6,2048,first&0xffffffff,first>>32,1025,3075,48,12288,0,0]
    payload=struct.pack('<16I',*h)+bytes((LIVE_WORDS-16)*4)
    meta,body=decode_live_frame(payload,123,4,0)
    assert meta['firstSampleIndex']==str(first)
    assert len(body)==(LIVE_WORDS-16)*4

def test_streamed_level_changes_are_not_single_shot(spec):
    h=Harness(spec,instrument_mode=True);h.rt.open('levels_core');h.rt.set_live_stream_active(True);h.tick(.05)
    assert h.gw.count('start')==0
    for i in range(3):
        levels=[.01+i*.01,.03,.06,0.,-40.+i*3,3.,0.,1.]*6
        body=bytes(3075*4)+struct.pack('<48f',*levels)+bytes(12288*4)
        meta={'frame':i+1,'config':1,'session':1,'channel':0,'sampleRateHz':48009.77,'firstSampleIndex':str(i*2048),'lastSampleIndex':str((i+1)*2048-1),'gap':False,'streamId':9}
        h.rt.ingest_live_frame(meta,body)
        assert h.workspace()['state']=='running'
        assert h.workspace()['freshness']['sourceFrame']==str(i+1)
    old=h.workspace()['chart']['chartRevision'];h.rt.stop('levels_core');h.rt.ingest_live_frame(meta,body)
    assert h.workspace()['chart']['chartRevision']==old
    assert h.workspace()['state']=='stopped'


def test_finished_capture_phase_is_not_reported_as_recording(spec):
    h=Harness(spec,instrument_mode=True);h.start('zoom_fft','zoom-status')
    h.tick();h.respond_get('zoom-status','running',progress={'phase':'computing','capturedSamples':4159,'requiredSamples':4159})
    assert '正在采集' not in h.workspace()['message']
    assert '计算' in h.workspace()['message']


def test_identical_p1_read_keeps_chart_without_redownloading(spec,gateway_capture,registry):
    h=Harness(spec,instrument_mode=True);h.start('psd','p1-first')
    h.tick();h.respond_get('p1-first','completed',configuration=CONFIG)
    h.deliver_result('p1-first','psd',words_for('psd',gateway_capture,registry),schema_for('psd',gateway_capture,registry),configuration=CONFIG)
    chart=h.workspace()['chart']['chartRevision'];downloads=h.gw.count('result')
    h.tick(.1);call=h.gw.take('start');h.respond_start(call,'p1-second',state='running',configuration=CONFIG)
    h.tick();h.respond_get('p1-second','completed',configuration=CONFIG)
    assert h.gw.count('result')==downloads
    assert h.workspace()['chart']['chartRevision']==chart
    assert h.rt._cached_p1_downloads_skipped==1


def test_room_views_reuse_same_pl_summary_without_new_capture(spec):
    h=Harness(spec,instrument_mode=True)
    values=[0.0]*48032
    for i,v in enumerate([1,.5,.7,50,1,3,1,6,1]):values[i]=v
    raw=struct.pack('<48032f',*values)
    schema={'actualProducerLayout':{'service':'room_ir_unfiltered','samples':24000,'sample_rate':48000,'ir_offset':32,'decay_offset':24032}}
    source={'featureId':'room_decay','jobId':'original-device-job','raw_bytes':raw,'roomSchema':schema,'sourceFeatureId':'room_decay','sourceKind':'test-fixture','configuration':dict(CONFIG),'capturedAt':500.0,'completedAt':510.0,'chart':{},'progress':{},'totalWords':48032}
    h.rt._results['room_decay']=source;h.rt._raw_total=len(raw);h.rt._raw_order=['room_decay']
    starts=h.gw.count('start');h.rt.open('room_clarity');view=h.rt._results['room_clarity']
    assert h.gw.count('start')==starts
    assert view['jobId']=='original-device-job' and view['sourceFeatureId']=='room_decay'
    assert view['capturedAt']==500 and view['raw_bytes'] is raw
    assert [r['label'] for r in view['chart']['scalarRows']]==['C50','C80','D50']
    h.rt.open('spectral_decay');assert 'spectral_decay' not in h.rt._results
