from pathlib import Path
import numpy as np,json
P=Path(__file__).resolve().parent
def cramer(t,h,p):
    T=t+273.15;xc=.000425
    x=h*(1.00062+3.14e-8*p+5.6e-7*t*t)*np.exp(1.2811805e-5*T*T-.019509874*T+34.04926034-6353.6311/T)/p
    return 331.5024+.603055*t-.000528*t*t+(51.471935+.1495874*t-.000782*t*t)*x+(-1.82e-7+3.73e-8*t-2.93e-10*t*t)*p+(-85.20931-.228525*t+5.91e-5*t*t)*xc-2.835149*x*x-2.15e-13*p*p+29.179762*xc*xc+.000486*x*p*xc
temp=np.arange(31,dtype=float);dry=cramer(temp,0,101325)
delta=np.rint((dry-331.3-.606*temp)*65536).astype(np.int64)
humid=np.rint((cramer(temp,1,101325)-dry)*65536).astype(np.int64)
dp=np.rint((-1.82e-7+3.73e-8*temp-2.93e-10*temp*temp-2*2.15e-13*101325)*2**24).astype(np.int64)
values=np.stack([delta,humid,dp],axis=1).ravel();values=np.r_[values,[delta[-1],humid[-1],dp[-1]]]
(P/'air_coeff.mem').write_text(''.join(f'{int(x)&0xffffffff:08x}\n' for x in values))
max_error=0.;worst=None
hh=np.arange(0,65536,1024,dtype=np.int64)[:,None];pp=np.arange(75000,102001,1000,dtype=np.int64)[None,:]
for tc in range(3001):
    lo=tc//100;hi=min(lo+1,30);frac=tc%100
    dc=delta[lo]+np.trunc((delta[hi]-delta[lo])*frac/100).astype(np.int64)
    hc=humid[lo]+np.trunc((humid[hi]-humid[lo])*frac/100).astype(np.int64)
    base=21712077+(tc*39715)//100
    wet=(hc*hh//65535)*101325//pp
    correction=((pp-101325)*dp[lo])>>8
    approx=(base+dc+wet+correction)/65536
    error=np.abs(approx-cramer(tc/100,hh/65535,pp))
    e=float(error.max())
    if e>max_error:
        max_error=e;idx=np.unravel_index(error.argmax(),error.shape);worst=[tc/100,int(hh[idx[0],0]),int(pp[0,idx[1]])]
assert max_error<.015,max_error
(P/'approximation.json').write_text(json.dumps({'maxErrorMps':max_error,'worstTemperatureHumidityRawPressure':worst,'domain':'0..30 C, RH 0..100%, 75..102 kPa','temperatureStepTestC':.01,'humidityRawStep':1024,'pressureStepPa':1000,'ROMWords':96,'co2AssumedPpm':425},indent=2))
print('ROM prepared; maximum gridded error m/s:',max_error)
