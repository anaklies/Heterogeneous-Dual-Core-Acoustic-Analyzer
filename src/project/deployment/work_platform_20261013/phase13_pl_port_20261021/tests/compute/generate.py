from pathlib import Path
import json
import numpy as np
P=Path(__file__).resolve().parent
rng=np.random.default_rng(13211021)
stim=[]; expected=[]
for tag in range(1,101):
    n=int(rng.integers(1,385));a=rng.integers(-32768,32768,n,dtype=np.int64);b=rng.integers(-32768,32768,n,dtype=np.int64)
    total=int(np.dot(a,b));expected.append((tag<<48)|(total&((1<<48)-1)))
    for start in range(0,n,12):
        m=min(12,n-start);aa=sum((int(v)&65535)<<(16*i) for i,v in enumerate(a[start:start+m]));bb=sum((int(v)&65535)<<(16*i) for i,v in enumerate(b[start:start+m]));mask=(1<<m)-1
        stim.append((tag<<398)|(int(start==0)<<397)|(int(start+m==n)<<396)|(mask<<384)|(aa<<192)|bb)
# Orphan end packet must be marked invalid. Never counted as a valid dot.
stim.append((999<<398)|(1<<396)|(1<<384)|(2<<192)|3)
expected.append(1<<80)
(P/'stimulus.mem').write_text(''.join(f'{x:0108x}\n' for x in stim))
(P/'expected.mem').write_text(''.join(f'{x:021x}\n' for x in expected))
(P/'counts.svh').write_text(f'localparam integer INPUTS={len(stim)}, OUTPUTS={len(expected)};\nlocalparam DATA_DIR="{P.as_posix()}";\n')
(P/'golden.json').write_text(json.dumps(dict(seed=13211021,validDots=100,invalidDots=1,inputBeats=len(stim),signedWidth=16,lanes=12,accumulatorWidth=48),indent=2))
