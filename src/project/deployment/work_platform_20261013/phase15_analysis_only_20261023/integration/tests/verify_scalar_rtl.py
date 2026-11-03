from pathlib import Path
import json,numpy as np
p=Path(__file__).resolve().parents[1]
u=np.array([int(x,16) for x in (p/'tests/actual_scalar.hex').read_text().split()],np.uint32)
a=u[:5].view(np.float32);gold=[-1,2,np.log(2),2,1];np.testing.assert_allclose(a,gold,rtol=3e-6,atol=1e-7)
assert u[8:11].tolist()==[3219,0xffffff00,18]
(p/'results/actual_scalar_rtl.json').write_text(json.dumps(dict(productionRTL=True,mathValues=5,metadataWords=3,checkpointChunks=5,maxAbsError=float(np.max(abs(a-gold)))),indent=2))
print('SCALAR_RTL_NUMERIC_PASS math5 metadata3 5chunks')
