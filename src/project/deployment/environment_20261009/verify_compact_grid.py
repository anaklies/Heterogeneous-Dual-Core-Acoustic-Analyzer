from pathlib import Path
import numpy as np,json
P=Path(__file__).resolve().parent
from generate_air_coeff import cramer
v=[int(x,16) for x in (P/'air_delta_coeff.mem').read_text().split()];coef=np.array([x-65536 if x>=32768 else x for x in v],np.int64).reshape(-1,3)
rh=np.r_[np.arange(0,65536,1024),65535][:,None];pp=np.arange(75000,102001,1000)[None,:]
maximum=0.;worst=None
for tc in range(3001):
    lo=tc//100;hi=min(lo+1,30);frac=tc%100
    dry=coef[lo,0]+np.trunc((coef[hi,0]-coef[lo,0])*frac/100).astype(np.int64)
    hum=coef[lo,1]+np.trunc((coef[hi,1]-coef[lo,1])*frac/100).astype(np.int64)
    corr=dry+(hum*rh//65535)*101325//pp+((pp-101325)*coef[lo,2]>>12)
    delta=np.sign(corr)*(np.abs(corr).astype(np.int64)<<20)//39715
    delta=np.sign(corr)*((np.abs(corr).astype(np.int64)<<20)//39715)
    tencoded=(tc*65536//100+delta)/65536
    actual=np.float32(331.3)+np.float32(.606)*tencoded.astype(np.float32)
    error=np.abs(actual-cramer(tc/100,rh/65535,pp));value=float(error.max())
    if value>maximum:
        maximum=value;ij=np.unravel_index(error.argmax(),error.shape);worst=[tc/100,int(rh[ij[0],0]),int(pp[0,ij[1]])]
assert maximum<.015,maximum
report={'maxKernelSpeedErrorMps':maximum,'worstTemperatureHumidityRawPressure':worst,'gridCases':3001*len(rh)*pp.shape[1],'temperatureStepC':.01,'humidityRawStep':1024,'pressureStepPa':1000,'includesFullHumidityEndpoint':True,'boundary':'bounded-model gridded numerical error, not actual sensor or localization error'}
(P/'compact_grid_accuracy.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
