# Only a bounded software check of the new filter's stores/finite output.
exec(open('deployment/echo_stipa_quick_20261030/check_quick.py',encoding='utf-8-sig').read().split('rows=[];')[0].replace('Path(__file__).resolve().parent',"Path('deployment/echo_stipa_quick_20261030').resolve()"))
m=np.zeros(q.ARENA,np.float32);t=np.arange(q.N)/q.old.FS;m[q.OUT:q.OUT+q.N]=.1*np.sin(2*np.pi*1000*t);c,_=q.filt(3,0)
sp=q.old.install_stage(m,c,q.old.layout(q.N),base=q.BASE);m.view(np.uint32)[q.BASE+9]=512
for i in range(100000):
 st=ctypes.c_uint();fn(m.ctypes.data,sp['descriptor'],len(m),0,ctypes.byref(st));assert st.value&255==0,hex(st.value)
 if st.value&0x80000000:break
else:raise AssertionError('filter control did not finish')
a=m[q.OUT+2*q.N:q.OUT+2*q.N+q.N//q.DEC];assert np.isfinite(a).all() and np.min(a[100:])>=0 and .003<float(np.mean(a[100:]))<.007
result={'finiteEnvelope':True,'storedEnvelopePoints':len(a),'ended':True,'hardwareMeasured':False};(q.R/'FILTER_SOFTWARE_CHECK.json').write_text(json.dumps(result,indent=2));print(result)
