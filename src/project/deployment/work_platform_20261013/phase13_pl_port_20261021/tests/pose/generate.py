from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
P=Path(__file__).resolve().parent
rng=np.random.default_rng(13)
rows=[]
mount=np.array([[0,1,0],[-1,0,0],[0,0,1]])
for i in range(32):
    q=Rotation.from_euler('zyx',rng.uniform([-180,-60,-50],[180,60,50])).as_quat()
    q=np.clip(np.rint(q*32768),-32768,32767).astype(int)
    if i==0:q=np.array([0,0,0,32767])
    u=rng.normal(size=3);u/=np.linalg.norm(u);u=np.rint(u*16384).astype(int)
    if i==0:u=np.array([16384,0,0])
    predicted=Rotation.from_quat(q/np.linalg.norm(q)).as_matrix()@mount@u
    expected=np.rint(predicted).astype(int)
    # Cases30/31 exercise stale pose and invalid direction.
    pose=i!=30;valid=i!=31
    if not pose:expected=u
    if not valid:expected=np.zeros(3,int)
    fields=[*u,q[3],q[0],q[1],q[2],*expected]
    payload=sum((int(x)&65535)<<(16*k) for k,x in enumerate(fields))
    payload|=int(pose)<<160;payload|=int(valid)<<161
    rows.append(payload)
(P/'poses.mem').write_text(''.join(f'{x:041x}\n' for x in rows))
(P/'pose_path.svh').write_text(f'localparam DATA_FILE="{P.as_posix()}/poses.mem";\n')
