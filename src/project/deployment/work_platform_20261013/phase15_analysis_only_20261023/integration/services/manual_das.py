"""Manual far-field DAS PL microcode; no automatic direction detector.

Phase8 bench8.steer convention: a=exp(+j*2*pi*f*mic.dot(u)/c), y=a.H X/6.
Coordinates copied verbatim from phase2 ml_api.MIC as inherited by Phase8/9.
The assembler emits geometry/constants and raw requested angles, never host trig.
All angle conversion, trigonometry, delays and beam arithmetic execute in scalar PL.
"""
import math
from programs import Code, install

MIC=((0,.1299038106,-.076),(-.1125,-.0649519053,-.076),(.1125,-.0649519053,-.076),
     (0,.1299038106,.076),(-.1125,-.0649519053,.076),(.1125,-.0649519053,.076))

def _trig(c):
    """f0 radians -> f1 cos,f2 sin. Reduce to [-pi,pi], Taylor 18/19.

    f3..5 scratch. Bounded by input angle <=2pi or phase <170 radians
    for admitted fs<=96kHz, c>=300m/s and fixed microphone coordinates.
    """
    c.f(4,math.pi); c.f(5,2*math.pi)
    start=len(c.words); b=c.emit(19,a=4,b=0,target=0); leave=c.emit(17,imm=0)
    c.words[b][2]=len(c.words); c.emit(5,0,0,5); c.emit(17,imm=start)
    c.words[leave][1]=len(c.words)
    c.f(4,-math.pi); start=len(c.words)
    b=c.emit(19,a=0,b=4,target=0); leave=c.emit(17,imm=0)
    c.words[b][2]=len(c.words); c.emit(4,0,0,5); c.emit(17,imm=start)
    c.words[leave][1]=len(c.words)
    c.emit(6,3,0,0)
    for dest,odd in ((1,0),(2,1)):
        c.f(dest,(-1)**9/math.factorial(18+odd))
        for k in range(8,-1,-1):
            c.emit(6,dest,dest,3);c.f(4,(-1)**k/math.factorial(2*k+odd));c.emit(4,dest,dest,4)
        if odd:c.emit(6,2,2,0)

def manual_das(azimuth_deg=0., elevation_deg=0., sample_rate=48000., sound_speed=343.42,
               first=1,count=128, quaternion_q14=None, orientation_valid=False,_angle_register=None):
    """Output count triplets: beam complex real/imag raw Hann FFT and PSD FS²/Hz.

    Full positive spectrum optional count=1025 first=0; not a promise of 10Hz.
    Single-frame PSD, no statistical averaging or source separation implied.
    Default direction is local array frame, +X az0,+Y az90,+Z el90.
    Optional quaternion is sensor orientation array->global, raw qw,qx,qy,qz Q14.
    PL normalizes it and applies its conjugate to the requested global direction.
    Invalid orientation uses identity/local fallback; it is not a global bearing.
    """
    if not all(map(math.isfinite,(azimuth_deg,elevation_deg,sample_rate,sound_speed))):raise ValueError('finite parameters required')
    if not -360<=azimuth_deg<=360 or not -90<=elevation_deg<=90:raise ValueError('angle range')
    if not 8000<=sample_rate<=96000 or not 300<=sound_speed<=380:raise ValueError('fs/c range')
    if first<0 or count<1 or first+count>1025:raise ValueError('bin range')
    if quaternion_q14 is not None and (len(quaternion_q14)!=4 or any(not isinstance(v,(int,)) or abs(v)>32768 for v in quaternion_q14)):
        raise ValueError('four signed raw Q14 integers required')
    rotate=bool(orientation_valid and quaternion_q14 is not None)
    c=Code();c.u(0,0);c.u(1,first*2);c.u(2,first);c.u(3,0)
    if _angle_register is None:c.f(0,azimuth_deg)
    else:c.history(0,_angle_register,0)
    c.f(4,math.pi/180);c.emit(6,0,0,4);_trig(c)
    c.f(4,0);c.emit(4,17,1,4);c.emit(4,18,2,4)
    if _angle_register is None:c.f(0,elevation_deg)
    else:c.history(0,_angle_register,1)
    c.f(4,math.pi/180);c.emit(6,0,0,4);_trig(c)
    c.emit(6,17,17,1);c.emit(6,18,18,1);c.f(4,0);c.emit(4,19,2,4)
    if rotate:
        # Normalization and conjugation execute in PL, not in the assembler.
        c.f(0,0)
        for k,value in enumerate(quaternion_q14):
            c.f(20+k,value);c.emit(6,1,20+k,20+k);c.emit(4,0,0,1)
        c.f(1,1e-12);bad=c.emit(19,a=0,b=1,target=0)
        c.emit(8,0,0)
        for k in range(4):c.emit(7,20+k,20+k,0)
        c.f(0,-1)
        for k in range(21,24):c.emit(6,k,k,0)
        # t=2*q.xyz cross v; v_local=v+qw*t+q.xyz cross t.
        c.f(4,2)
        for dest,i,j in ((24,1,2),(25,2,0),(26,0,1)):
            c.emit(6,0,21+i,17+j);c.emit(6,1,21+j,17+i)
            c.emit(5,dest,0,1);c.emit(6,dest,dest,4)
        for axis,i,j in ((0,1,2),(1,2,0),(2,0,1)):
            c.emit(6,0,21+i,24+j);c.emit(6,1,21+j,24+i);c.emit(5,0,0,1)
            c.emit(6,1,20,24+axis);c.emit(4,0,0,1);c.emit(4,27+axis,17+axis,0)
        c.f(0,0)
        for axis in range(3):c.emit(4,17+axis,27+axis,0)
        c.words[bad][2]=len(c.words)
    for ch,xyz in enumerate(MIC):
        c.f(20+ch,0)
        for axis,pos in enumerate(xyz):
            c.f(4,pos);c.emit(6,5,17+axis,4);c.emit(4,20+ch,20+ch,5)
        c.f(4,sound_speed);c.emit(7,20+ch,20+ch,4)
    start=len(c.words);c.emit(18,26,2);c.f(4,2*math.pi*sample_rate/2048);c.emit(6,26,26,4)
    c.f(10,0);c.f(11,0)
    for ch in range(6):
        c.emit(6,0,26,20+ch);_trig(c)
        c.load(6,1,ch*8192);c.load(7,1,ch*8192+1)
        c.emit(6,8,6,1);c.emit(6,9,7,2);c.emit(4,8,8,9);c.emit(4,10,10,8)
        c.emit(6,8,7,1);c.emit(6,9,6,2);c.emit(5,8,8,9);c.emit(4,11,11,8)
    c.f(4,1/6);c.emit(6,10,10,4);c.emit(6,11,11,4)
    c.store(10,0);c.store(11,0,1)
    c.emit(6,12,10,10);c.emit(6,13,11,11);c.emit(4,12,12,13)
    c.f(4,2/(sample_rate*768));c.emit(6,12,12,4)
    # DC and Nyquist are not doubled.
    c.u(4,1);dc=c.emit(16,a=2,imm=1,target=0);c.u(4,0)
    c.words[dc][2]=len(c.words);nyq=c.emit(16,a=2,imm=1024,target=0);c.u(4,1)
    c.words[nyq][2]=len(c.words);nohalf=c.emit(16,a=4,imm=1,target=0)
    c.f(4,.5);c.emit(6,12,12,4);c.words[nohalf][2]=len(c.words)
    c.store(12,0,2);c.addi(0,0,3);c.addi(1,1,2);c.addi(2,2,1)
    c.loop(2,first+count,start);c.emit(0)
    assert len(c.words)<=1024
    return c,3*count,dict(service='manual_local_farfield_das',azimuth_deg=azimuth_deg,
        elevation_deg=elevation_deg,sample_rate=sample_rate,sound_speed=sound_speed,first_bin=first,bins=count,
        fields=['beam_fft_real_FS','beam_fft_imag_FS','beam_psd_FS2_per_Hz'],imu_transform=rotate,
        requested_frame='global' if rotate else 'array_local',orientation_valid=bool(orientation_valid),
        orientation_fallback=not rotate,quaternion_q14=quaternion_q14,
        quaternion_convention='array->global; apply normalized conjugate in PL; zero quaternion uses identity fallback',
        automatic_doa=False,math_reference='Phase8 bench8.steer; y=a.H*X/6',window='2048 periodic Hann; energy768')

def install_das(memory,specification,**kwargs):
    return install(memory,specification,**kwargs)
