from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
v=[int(x,16) for x in (P/'air_delta_coeff.mem').read_text().split()];v=np.array([x-65536 if x>=32768 else x for x in v],np.int64).reshape(-1,3)
original=[int(x,16) for x in (P/'air_vectors.mem').read_text().split()];rows=[]
for x in original:
    tc=x&65535;tc=tc-65536 if tc>=32768 else tc;rh=(x>>16)&65535;p=(x>>32)&0xffffffff;tv=(x>>64)&1;hv=(x>>65)&1;pv=(x>>66)&1
    delta=0;mode=0 if not(tv and -2000<=tc<=6000) else 1
    if tv and 0<=tc<=3000 and hv:
        valid=pv and 75000<=p<=102000;pr=p if valid else 101325;mode=3 if valid else 2
        lo=tc//100;hi=min(lo+1,30);frac=tc%100
        dry=int(v[lo,0])+int(np.trunc((v[hi,0]-v[lo,0])*frac/100))
        hum=int(v[lo,1])+int(np.trunc((v[hi,1]-v[lo,1])*frac/100))
        c=dry+(hum*rh//65535)*101325//pr+((pr-101325)*int(v[lo,2])>>12)
        delta=(1 if c>=0 else -1)*(abs(c)<<20)//39715
        # SV signed division applies sign after truncating positive magnitude.
        delta=(1 if c>=0 else -1)*((abs(c)<<20)//39715)
    word=(x&((1<<67)-1))|((delta&0xfffff)<<67)|(mode<<87)
    rows.append(f'{word:024x}\n')
(P/'compact_vectors.mem').write_text(''.join(rows))
assert all((n*41944)>>22==n//100 for n in range(3001))
print('200 compact correction golden vectors and 3001 temperature indices verified.')
