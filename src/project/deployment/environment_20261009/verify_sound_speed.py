from pathlib import Path
import csv,struct,json
import numpy as np
from generate_air_coeff import cramer
P=Path(__file__).resolve().parent
rows=list(csv.DictReader((P/'config_environment_vectors.csv').open()))
errors=[];results=[]
for row in rows:
    t=int(row['temp_centi'])/100;h=int(row['rh_raw'])/65535;p=int(row['pressure_pa']);flags=int(row['flags']);mode=int(row['mode'])
    effective=struct.unpack('<f',struct.pack('<I',int(row['config0'],16)))[0]
    # Exact existing C/HLS constants and operation precision.
    speed=float(np.float32(331.3)+np.float32(.606)*np.float32(np.clip(effective,-20,60)))
    if mode>=2:reference=float(cramer(t,h,p if mode==3 else 101325))
    else:reference=331.3+.606*(t if flags&1 and -20<=t<=60 else 19.3)
    error=abs(speed-reference);errors.append(error)
    results.append(dict(row,computedKernelSpeedMps=speed,referenceSpeedMps=reference,errorMps=error))
assert max(errors)<.015,max(errors)
report={'cases':len(rows),'maxActualKernelSpeedErrorMps':max(errors),'meanErrorMps':float(np.mean(errors)),
    'boundary':'200 actual RTL config snapshots decoded through unchanged MUSIC float formula; not physical sensor calibration','results':results}
(P/'actual_sound_speed.json').write_text(json.dumps(report,indent=2))
print('PASS actual RTL config -> MUSIC formula, maximum speed error m/s',max(errors))
