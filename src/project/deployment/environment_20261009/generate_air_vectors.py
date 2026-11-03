from pathlib import Path
import numpy as np,json
P=Path(__file__).resolve().parent
coef=[int(v,16) for v in (P/'air_coeff.mem').read_text().split()]
coef=np.array([v-2**32 if v>=2**31 else v for v in coef],np.int64).reshape(-1,3)
def expected(tc,rh,p,tv,hv,pv):
    ok=tv and -2000<=tc<=6000;t=tc if ok else 1930
    mode=0 if not ok else 1
    q=21712077+(1 if t>=0 else -1)*(abs(t)*39715//100)
    if ok and 0<=t<=3000 and hv:
        valid=pv and 75000<=p<=102000;mode=3 if valid else 2;pr=p if valid else 101325
        lo=t//100;hi=min(lo+1,30);frac=t%100
        dc=int(coef[lo,0])+int(np.trunc((coef[hi,0]-coef[lo,0])*frac/100))
        hc=int(coef[lo,1])+int(np.trunc((coef[hi,1]-coef[lo,1])*frac/100))
        q+=dc+(hc*rh//65535)*101325//pr+((pr-101325)*int(coef[lo,2])>>8)
    return q, (135<<23)|((q>>1)&0x7fffff),mode
cases=[]
for t in [-2000,0,1,1930,2000,2549,2999,3000,3500,6000]:
    for rh,p in [(0,101325),(32768,95000),(65535,75000),(50000,102000)]:cases.append((t,rh,p,1,1,1))
cases +=[(2000,32768,101325,0,1,1),(2000,32768,101325,1,0,1),(2000,32768,0,1,1,0),
         (2000,32768,74000,1,1,1),(2000,32768,102001,1,1,1),(-2500,65535,101325,1,1,1)]
rng=np.random.default_rng(60261009)
for _ in range(154):cases.append((int(rng.integers(0,3001)),int(rng.integers(0,65536)),int(rng.integers(75000,102001)),1,1,1))
rows=[]
for t,h,p,tv,hv,pv in cases:
    q,f,m=expected(t,h,p,tv,hv,pv)
    word=(t&0xffff)|(h<<16)|(p<<32)|(tv<<64)|(hv<<65)|(pv<<66)|(q<<67)|(f<<99)|(m<<131)
    rows.append(f'{word:034x}\n')
(P/'air_vectors.mem').write_text(''.join(rows))
print('200 air compensation vectors with sensor/domain fallbacks prepared.')
