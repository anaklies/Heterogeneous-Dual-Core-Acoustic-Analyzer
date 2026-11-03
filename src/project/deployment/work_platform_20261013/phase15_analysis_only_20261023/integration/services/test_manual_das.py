"""Native execution of production scalar microcode vs independent complex NumPy."""
from pathlib import Path
import ctypes,json,time
import numpy as np
from manual_das import MIC,manual_das,install_das
HERE=Path(__file__).resolve().parent
fn=ctypes.CDLL(str(HERE/'services_scalar.dll')).scalar_native
fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
rng=np.random.default_rng(20261023);mem=np.zeros(700000,np.float32);rows=[]
def case(name,az,el,first,count,coherent=False,slot=0,q14=None,valid=False):
    fs=48009.775390625;speed=344.2
    spec=install_das(mem,manual_das(az,el,fs,speed,first,count,quaternion_q14=q14,orientation_valid=valid))
    a=np.deg2rad(az);e=np.deg2rad(el);u=np.array([np.cos(e)*np.cos(a),np.cos(e)*np.sin(a),np.sin(e)])
    if valid and q14 is not None and np.linalg.norm(q14)>1e-6:
        w,xq,yq,zq=np.asarray(q14)/np.linalg.norm(q14)
        # Independent full rotation matrix; transpose maps global to local.
        rotation=np.array([[1-2*(yq*yq+zq*zq),2*(xq*yq-zq*w),2*(xq*zq+yq*w)],
          [2*(xq*yq+zq*w),1-2*(xq*xq+zq*zq),2*(yq*zq-xq*w)],
          [2*(xq*zq-yq*w),2*(yq*zq+xq*w),1-2*(xq*xq+yq*yq)]])
        u=rotation.T@u
    f=np.arange(1025)*fs/2048;steer=np.exp(2j*np.pi*f[:,None]*(np.asarray(MIC)@u)[None,:]/speed)
    x=(rng.normal(size=(1025,6))+1j*rng.normal(size=(1025,6)))*.7
    if coherent:x=steer*(rng.normal(size=(1025,1))+1j*rng.normal(size=(1025,1)))
    x=x.astype(np.complex64)
    for ch in range(6):
        off=262144+slot*65536+ch*8192
        mem[off:off+2050:2]=x[:,ch].real;mem[off+1:off+2050:2]=x[:,ch].imag
    t=time.perf_counter()
    for chunks in range(1,200000):
        status=ctypes.c_uint();fn(mem.ctypes.data,spec['descriptor']+slot*16,len(mem),slot,ctypes.byref(status))
        assert status.value&255==0,hex(status.value)
        if status.value&0x80000000:break
    else:raise AssertionError('did not end')
    out=mem[spec['output']:spec['output']+spec['output_words']].reshape(count,3).copy()
    y=(np.conj(steer)*x).mean(axis=1);factor=np.full(1025,2/(fs*768));factor[[0,1024]]*=.5
    gold=np.stack([y.real,y.imag,abs(y)**2*factor],axis=1)[first:first+count]
    assert np.isfinite(out).all()
    np.testing.assert_allclose(out[:,:2],gold[:,:2],rtol=5e-4,atol=2e-5)
    np.testing.assert_allclose(out[:,2],gold[:,2],rtol=8e-4,atol=1e-12)
    rows.append(dict(name=name,azimuth_deg=az,elevation_deg=el,first_bin=first,bins=count,
       compared=out.size,chunks=chunks,bytecode_instructions=spec['program_instructions'],
       native_seconds=time.perf_counter()-t,max_complex_absolute_error=float(abs(out[:,0]+1j*out[:,1]-y[first:first+count]).max()),
       max_psd_absolute_error=float(abs(out[:,2]-gold[:,2]).max())))
case('az0_el0_fullband',0,0,0,1025,True)
case('positive_y_small_elevation',90,7,1,128,True,1)
case('negative_azimuth',-137,-43,800,225,False,2)
case('full_circle_equivalent',360,0,0,48,True,3)
case('upper_pole',17,90,900,125,True)
case('lower_pole',-359,-90,500,96,False)
case('small_angles',.25,-.5,65,64,False)
case('imu_identity_q14',31,14,30,64,True,q14=[16384,0,0,0],valid=True)
case('imu_yaw90_q14',90,0,240,64,True,q14=[11585,0,0,11585],valid=True)
case('imu_pitch90_q14',0,0,600,64,True,q14=[11585,0,11585,0],valid=True)
case('imu_invalid_identity_fallback',25,-20,500,32,True,q14=[11585,0,0,11585],valid=False)
case('imu_zero_identity_guard',25,-20,500,32,True,q14=[0,0,0,0],valid=True)
for kwargs in ({'azimuth_deg':float('nan')},{'elevation_deg':91},{'sound_speed':0},{'first':1024,'count':2}):
    try:manual_das(**kwargs)
    except ValueError:pass
    else:raise AssertionError('invalid parameter accepted')
result=dict(verification='Native production PL scalar instruction execution vs independent NumPy complex steering; no RTL/board timing claim',
    cases=rows,total_compared=sum(r['compared'] for r in rows),parameter_rejections=4,
    limitations=['Manual local array direction only; automatic DOA remains removed.',
    'Optional raw Q14 quaternion normalized/conjugated in PL; hardware freshness/validity supplied by sensor integration and not established by this native test.',
    'Invalid/missing/zero quaternion uses identity local fallback; downstream must mark invalid global bearing.',
    'Relative beam PSD is not absolute SPL, source separation, or independent source power.',
    'Farfield model; nearfield amplitude/curvature and room reflections alter selectivity.',
    'Full 1025-bin service is optional P2 with pinned source slot; actual scalar RTL cost/refresh not established.',
    'Raw complex FFT input must come from 2048 periodic Hann FS-normalized production FFT.'],
    costs=dict(extra_fft=0,extra_evd=0,extra_matrix=0,private_allocation_bytes=24576*4,
      output_bytes_per_bin=12,source_snapshot_bytes=49152*4,
      worst_vm_dispatches_per_bin_upper_bound=1200,additional_steering_cache_bytes=0,
      source_pinning_required=True,trig='Runtime PL modulo reduction + degree18 cosine/degree19 sine polynomials'))
(HERE/'DAS_RESULTS.json').write_text(json.dumps(result,indent=2))
print('MANUAL_DAS_NATIVE_PASS',result['total_compared'])
