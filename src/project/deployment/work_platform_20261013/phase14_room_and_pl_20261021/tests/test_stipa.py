from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from algorithms.stipa_experimental import combine_mtf,modulation_depth,measure,FS


def test_mtf_limits_and_uniform_half_modulation():
    assert abs(combine_mtf(np.ones((7,2)))['estimate']-1)<1e-12
    assert combine_mtf(np.zeros((7,2)))['estimate']==0
    assert abs(combine_mtf(np.full((7,2),.5))['estimate']-.5)<1e-12


def test_joint_modulation_finite_duration():
    t=np.arange(3917)/200
    e=3*(1+.5*np.sin(2*np.pi*.63*t)+.4*np.cos(2*np.pi*3.15*t))
    m,valid=modulation_depth(e,200,[.63,3.15])
    assert valid and np.allclose(m,[.5,.4],atol=1e-12)


def test_reject_arbitrary_speech_or_short_measurement():
    x=np.zeros(FS)
    assert not measure(x,x)['valid']
    assert not measure(x,x,test_signal_confirmed=True)['valid']
