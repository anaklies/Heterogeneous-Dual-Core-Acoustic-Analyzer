from pathlib import Path
import sys,json
import numpy as np
from scipy import signal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from algorithms.room_ir import reverberation_time
P=Path(__file__).resolve().parents[1];M=P.parent/'phase12m_product_algorithm_acceptance_20261021'
rows=[]
for room in range(3):
    path=M/f'data/rir/Mroom{room}_0.npz';x=np.load(path)['full'][0]
    old=json.loads(path.with_suffix('.json').read_text())['T20'][0]
    filtered=signal.sosfilt(signal.butter(4,[250,8000],btype='bandpass',fs=48000,output='sos'),x)
    new=reverberation_time(filtered,48000,onset_sample=0,include_curve=False)
    estimate=new['fits']['T20']['estimateSeconds']
    difference=abs(estimate-old['RT60FromT20']) if estimate is not None else None
    assert difference is not None and difference<.02,(room,difference)
    rows.append(dict(room=room,frequencyBandHz=[250,8000],oldT20=old['RT60FromT20'],newT20=estimate,
                     absoluteDifferenceSeconds=difference,notNewIndependentRoom=True))
(P/'tests/room_band_alignment.json').write_text(json.dumps(dict(rows=rows,scope='matchingfrequencybands only; fullbandRT60 cannotbecompared to250..8000HzlegacyT20'),indent=2))
print('MATCHED_BAND_T20_PASS',max(r['absoluteDifferenceSeconds'] for r in rows))
