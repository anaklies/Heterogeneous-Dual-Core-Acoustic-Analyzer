from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy import signal
import pytest
from algorithms.excitation import logarithmic_sweep,recover_ir


def test_known_linear_paths_recovered_without_true_IR_input():
    x,_=logarithmic_sweep(.5)
    h=np.zeros(2400);h[48]=.8;h[480]=.25;h[1600]=-.1
    y=signal.fftconvolve(x,h)
    result=recover_ir(y,x,.05)
    got=result['impulseResponse']
    assert np.argmax(abs(got))==48
    assert abs(got[480]/got[48]-.25/.8)<.015
    assert abs(got[1600]/got[48]+.1/.8)<.015


def test_missing_tail_rejected():
    x,_=logarithmic_sweep(.5)
    with pytest.raises(ValueError):recover_ir(x,x,.1)
