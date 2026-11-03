from pathlib import Path
import numpy as np,json,re
I=Path(__file__).resolve().parents[1];T=I/'tests'
a=np.array([int(x,16) for x in (T/'actual_fft.hex').read_text().split()],dtype=np.uint32).view(np.float32);g=np.loadtxt(T/'stream_golden.txt',dtype=np.float32)[:7179]
assert len(a)==7179
tol=np.full(7179,2e-5);tol[:4096]=4e-5
for k in range(1025):tol[4097+3*k]=1e-11;tol[4098+3*k]=1e-9
err=np.abs(a-g);bad=~np.isfinite(a)|(err>tol+np.abs(g)*3e-4)
assert not bad.any(),[(int(i),float(a[i]),float(g[i])) for i in np.flatnonzero(bad)[:8]]
log=(I/'results/direct_fft_safe_sim.log').read_text();cycles=int(re.search(r'cycles=(\d+) reads=',log)[1])
assert 'Fatal:' not in log and 'cannot be opened for reading' not in log and 'INVALID_COMPLEX_REJECTED_WITHOUT_RESET' in log
report={'actualProductionRTL':True,'invalidComplexThenValidWithoutReset':True,'valuesChecked':len(a),'mismatches':int(bad.sum()),'maxAbsoluteError':float(err.max()),'cyclesWithAXIStallsOneChannel':cycles,'sixChannelCyclesDerived':6*cycles,'windowBudgetCycles':2132900,'sampleRate':49162010/1024,'publicationRateTheoreticalHz':49162010/1024/4096,'fullRuntimeContinuousRTLTested':False,'physicalBoardTested':False}
(I/'results/actual_fft_rtl.json').write_text(json.dumps(report,indent=2))
print('ACTUAL_PRODUCTION_FFT_RTL_NUMERIC_PASS values=',len(a),'cycles=',cycles,'max_error=',float(err.max()))
