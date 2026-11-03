import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'algorithms'))
import numpy as np
import pytest
from scipy import signal
import noise_metrics as nm


def test_weighting_analytic_and_digital_response():
    f=np.array([31.5,63,125,250,500,1000,2000,4000,8000])
    for weight in ['A','C','Z']:
        sos=nm.weighting_sos(weight)
        _,h=signal.sosfreqz(sos,worN=f,fs=48000)
        actual=20*np.log10(abs(h));gold=nm.analog_weighting_db(f,weight)
        assert max(abs(actual-gold))<.6,(weight,actual-gold)
        assert abs(actual[5])<1e-9
    assert abs(float(nm.analog_weighting_db([1000],'A')[0]))<.002
    assert abs(float(nm.analog_weighting_db([1000],'C')[0]))<.002


def test_weighting_streaming_matches_one_block():
    rng=np.random.default_rng(14);x=rng.normal(0,.01,(12000,6))
    for weight in ['A','C','Z']:
        one=nm.FrequencyWeighting(weight).process(x)
        filt=nm.FrequencyWeighting(weight)
        chunks=np.concatenate([filt.process(x[:4000]),filt.process(x[4000:8000]),filt.process(x[8000:])])
        assert np.allclose(one,chunks,rtol=0,atol=0)


@pytest.mark.parametrize('response,tau',[('FAST',.125),('SLOW',1.)])
def test_time_weighted_step_and_state(response,tau):
    x=np.ones(48000)*.1;engine=nm.TimeWeightedPower(response)
    p=np.r_[engine.process(x[:24000])['powerFS2'][:,0],engine.process(x[24000:])['powerFS2'][:,0]]
    gold=.01*(1-np.exp(-np.arange(1,48001)/(48000*tau)))
    assert np.allclose(p,gold,rtol=1e-10,atol=1e-12)


def test_digital_equivalent_level_gain_and_zero():
    t=np.arange(48000)/48000;x=.2*np.sin(2*np.pi*1000*t)
    a=nm.equivalent_level(x);b=nm.equivalent_level(x*10**(-10/20))
    assert abs(a['equivalentLevelDBFS'][0]-20*np.log10(.2/np.sqrt(2)))<1e-10
    assert abs(a['equivalentLevelDBFS'][0]-b['equivalentLevelDBFS'][0]-10)<1e-10
    assert nm.equivalent_level(np.zeros(100))['equivalentLevelDBFS']==[None]


def test_percentile_exceedance_not_ordinary_percentile():
    x=np.arange(-90,-40,dtype=float)
    r=nm.level_statistics(x,.1)
    assert r['L10DBFS']==np.percentile(x,90)
    assert r['L90DBFS']==np.percentile(x,10)
    assert r['L10DBFS']>=r['L50DBFS']>=r['L90DBFS']
    assert abs(r['equivalentLevelDBFS']-10*np.log10(np.mean(10**(x/10))))<1e-12


def test_relative_insulation_same_chain_ten_db():
    x=np.random.default_rng(912).normal(0,.01,(48000,2))
    metadata=dict(gain_id='fixedgain',measurement_chain_id='same_selected_mics',source_configuration_id='unchanged_testsource',sample_rate=48000)
    r=nm.relative_insulation(x,x/np.sqrt(10),metadata,metadata)
    assert r['valid'].all()
    assert np.max(abs(r['relativeBandLevelDifferenceDB']-10))<1e-10
    with pytest.raises(ValueError):
        nm.relative_insulation(x,x,metadata,dict(metadata,gain_id='different'))


def test_noise_rating_rejects_uncalibrated_dbfs():
    assert not nm.noise_curve_rating(np.full(9,-60))['valid']
    reference=nm.nr_curves([39,40,41])
    level=reference['levelsDBSPL'][1]
    cal=dict(mode='calibrated',source='explicit synthetic bandSPL,not realmic')
    r=nm.noise_curve_rating(level,input_unit='dBSPL',calibration=cal)
    assert r['valid'] and r['rating']==40 and not r['estimated']
    nominal=nm.nominal_inmp441_offset(-26)
    r=nm.noise_curve_rating(level-120,calibration=nominal)
    assert r['valid'] and r['rating']==40 and r['estimated']


def test_nr_table_values_and_critical_band():
    table=nm.nr_curves([20,30])
    assert table['levelsDBSPL'][1,5]==30
    assert table['levelsDBSPL'][1,1]==59.1  #35.4+.790*30
    values=nm.nr_curves([30,31])['levelsDBSPL'][0]
    values=values-2;values[8]+=3
    r=nm.noise_curve_rating(values,input_unit='dBSPL',calibration=dict(mode='calibrated',source='synthetic'))
    assert r['rating']>30 and r['criticalBandHz']==8000


def test_nc_public_table_and_calibration_guard():
    cal=dict(mode='nominal',source='operator nominal',offsetDB=120)
    table=nm.nc_curves()
    assert table['levelsDBSPL'].shape==(12,8)
    values=table['levelsDBSPL'][4]
    assert values.tolist()==[60,52,45,40,36,34,33,32]
    assert not nm.noise_curve_rating(values-120,family='NC')['valid']
    r=nm.noise_curve_rating(values-120,family='NC',calibration=cal)
    assert r['valid'] and r['rating']==35 and r['estimated']
    r=nm.noise_curve_rating(values+.1,family='NC',input_unit='dBSPL',calibration=cal)
    assert r['rating']==40  # Conservative5-unit table, no hidden interpolation.
    # Synthetic supplied curve tests the engine only;not named realANSI values.
    curves=dict(name='NC',centerHz=[63,125],ratings=[15,20],levelsDBSPL=[[40,30],[45,35]],reference='synthetic fixture,notANSI table')
    r=nm.noise_curve_rating([44,34],centers=[63,125],family='NC',input_unit='dBSPL',calibration=cal,curves=curves)
    assert r['valid'] and r['rating']==20 and r['estimated']


def test_bad_inputs_and_missing_bands():
    with pytest.raises(ValueError):nm.weighting_sos('B')
    with pytest.raises(ValueError):nm.FrequencyWeighting('A').process([np.nan])
    with pytest.raises(ValueError):nm.TimeWeightedPower('FAST',44100)
    with pytest.raises(ValueError):nm.level_statistics([1,2],0)
    with pytest.raises(ValueError):
        nm.noise_curve_rating([30],centers=[1000],input_unit='dBSPL',calibration=dict(mode='calibrated',source='synthetic'))
