import copy,struct
from types import SimpleNamespace
from test_feature_runtime import Harness,CONFIG,spec,gateway_capture,registry,words_for,schema_for
from ui.features.decoder import decode_result
def word(v):return struct.unpack('<I',struct.pack('<f',v))[0]

def test_energy_history_is_bounded_display_of_new_results(spec):
 h=Harness(spec,instrument_mode=True);fid='energy_change'
 for frame in range(185):
  j=SimpleNamespace(owner=fid,feature_id=fid,job_id=str(frame),configuration=dict(CONFIG,sourceFrame=str(frame+1),config=frame+1,generation=str(frame+1)),total_words=6,schema={},source_kind='test-fixture',progress={},variant_id='')
  rows=[{'label':'power_FS2','value':frame/100,'valid':True,'unit':'FS²'},{'label':'delta_FS2','value':.01,'valid':True,'unit':'FS²'}]
  h.rt._store_result(j,{'scalarRows':rows,'series':[]},{},b'0'*24)
 result=h.rt._results[fid];assert result['chart']['kind']=='scalar-trend'
 assert len(result['chart']['series'][0]['points'])==180
 assert result['chart']['series'][0]['points'][-1][1]==1.84

def test_reference_start_removes_continuous_due(spec):
 h=Harness(spec,instrument_mode=True);fid='relative_insulation'
 h.rt._live_requested.add(fid);h.rt._live_due[fid]=1
 h.rt._start_reference_action(fid)
 assert fid not in h.rt._live_requested and fid not in h.rt._live_due
 assert fid in h.rt._auto_stopped

def test_gcc_plot_orders_physical_window_and_exposes_delay(spec):
 data=[word(0)]*2048;data[5]=word(.8);data[200]=word(100)
 chart=decode_result(spec['features']['gcc_phat'],{'schema':{'actualProducerLayout':{'sample_rate':48000,'output_count':2048}}},data)
 assert chart['scalarRows'][0]['unit']=='ms'
 assert abs(chart['scalarRows'][0]['value']-5/48)<1e-7
 pts=chart['series'][0]['points'];assert pts==sorted(pts)
 assert max(abs(x) for x,y in pts)<1

def test_phase_does_not_render_low_coherence_noise(spec):
 fields=['sum_xx','sum_yy','sum_real','sum_imag','Sxx','Syy','CSD_real','CSD_imag','coherence','phase_rad','valid']
 values=[word(5)]+[word(x) for x in [1,1,1,0,1,1,1,0,.2,2,1,1,1,1,0,1,1,1,0,.9,1,1]]
 chart=decode_result(spec['features']['coherence_phase'],{'schema':{'actualProducerLayout':{'stride':11,'bins':2,'fields':fields,'sample_rate':48000}}},values)
 assert chart['scalarRows'][0]['value']==5
 assert len(chart['panels'][0]['series'][0]['points'])==2
 assert len(chart['panels'][1]['series'][0]['points'])==1

def test_empty_monitor_never_looks_like_waiting_for_connection(spec):
 h=Harness(spec,instrument_mode=True);h.start('event_trigger','monitor')
 chart=h.workspace()['chart'];assert '变化监测运行中' in chart['emptyReason']
