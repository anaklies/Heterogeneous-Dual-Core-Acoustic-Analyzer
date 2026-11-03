from test_feature_runtime import Harness,spec

def test_auto_input_is_capability_gated_and_locked(spec):
 h=Harness(spec,instrument_mode=True)
 h.rt._auto_input_features={'fft'}
 h.rt.run('fft');call=h.gw.take('start')
 assert call['args']['params']['autoChannel'] is True
 h.respond_start(call,'auto-fft',extra={'selectedChannel':2,'autoSelected':True})
 assert h.rt._input_channels['fft']=={'channel':2,'auto':True}
 h.rt.stop('fft')
 assert 'fft' not in h.rt._input_channels

def test_late_start_cannot_restore_stopped_selection(spec):
 h=Harness(spec,instrument_mode=True)
 h.rt._auto_input_features={'fft'}
 h.rt.run('fft');call=h.gw.take('start');h.rt.stop('fft')
 h.respond_start(call,'late-fft',extra={'selectedChannel':2,'autoSelected':True})
 assert 'fft' not in h.rt._input_channels
