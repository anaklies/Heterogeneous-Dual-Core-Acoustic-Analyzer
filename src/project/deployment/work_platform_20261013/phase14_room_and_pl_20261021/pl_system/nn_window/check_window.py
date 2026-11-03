"""Oneexistingfullwindow, newwrapper+aggregate only. No primitive/model rerun."""
from pathlib import Path
import hashlib,json,subprocess,time
import numpy as np
from scipy.special import expit
P=Path(__file__).resolve().parent
B=P.parents[2]
FIX=B/'phase13_pl_port_20261021/nn/fixed'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

# The exponenttablecovers[-16,0], not the sigmoidtable's[-8,8].
grid=np.arange(-16384,1,4)
lut=np.rint(np.exp(grid/1024)*(1<<24)).astype(np.uint32)
(P/'exp_lut.h').write_text('#ifndef SIXMIC_EXP_NEG_Q24_H\n#define SIXMIC_EXP_NEG_Q24_H\n#include <cstdint>\nstatic const std::uint32_t EXP_NEG_Q24[4097]={'+','.join(str(int(v)) for v in lut)+'};\n#endif\n',encoding='ascii')
command=['D:/mingw64/bin/g++.exe','-std=c++17','-O2','-fno-fast-math',str(P/'nn_window.cpp'),str(P/'run.cpp'),'-o',str(P/'nn_window.exe')]
r=subprocess.run(command,capture_output=True,text=True)
(P/'compile.log').write_text(r.stdout+r.stderr);r.check_returncode()
source=FIX/'room0_speech_input_q11.bin'
start=time.perf_counter();subprocess.run([str(P/'nn_window.exe'),str(source),str(P/'window_output.bin')],check=True);elapsed=time.perf_counter()-start
raw=(P/'window_output.bin').read_bytes();old=np.fromfile(FIX/'room0_speech_output_q.bin','<i2')
network=np.frombuffer(raw[:76576*2],'<i2');assert np.array_equal(network,old)
vector=np.frombuffer(raw[76576*2:76576*2+1890*4],'<f4').reshape(15,2,63)
offset=76576*2+1890*4
meta=np.frombuffer(raw[offset:offset+5*8],'<u8');counters=np.frombuffer(raw[offset+5*8:],'<u8')
goldc=np.loadtxt(FIX/'room0_speech_stats.txt',dtype=np.uint64);assert np.array_equal(counters,goldc)
phase=network[:51030].reshape(15,2,63,27)
support=network[51030:76545].reshape(15,63,27)
activity=network[76545:76572]
number=network[-4:]
table=np.rint(expit(np.arange(-8192,8193,4)/1024)*32768).astype(np.int64)
def integer_sigmoid(x):
    x=np.asarray(x).astype(np.int32);address=np.clip(x,-8192,8192)+8192
    i=address>>2;fraction=address&3
    value=(table[i]*(4-fraction)+table[np.minimum(i+1,4096)]*fraction+2)>>2
    return np.where(x>8192,32768,np.where(x<-8192,0,value))
ss=integer_sigmoid(support).sum(0)
act=integer_sigmoid(activity)
weight=np.where(ss>=15*16384,(ss*act[None]+245760)//491520,0)
mass=weight.sum();assert int(meta[0])==int(mass)
integer_v=(phase.astype(np.int64)*weight[None,None]).sum(-1)
expected=integer_v.astype(np.float32)*np.float32(63/(8192*mass)) if mass else np.zeros_like(vector)
assert np.array_equal(expected,vector)
sf=expit(support.astype(np.float64)/1024).mean(0)
af=expit(activity.astype(np.float64)/1024)
w_float=sf*(sf>=.5)*af[None]
fmass=w_float.sum()
float_vector=np.sum(phase.astype(np.float64)/8192*w_float[None,None],axis=-1)*(63/fmass) if fmass else np.zeros_like(vector)
support_differences=int(np.sum((ss>=15*16384)!=(sf>=.5)))
e=np.exp(number.astype(float)/1024-np.max(number.astype(float)/1024));active=1-e[0]/e.sum()
assert abs(meta[1]/32768-active)<2/32768
assert bool(meta[2])==(active>=.5)
result=dict(status='PASS',case='existingMroom0_speech',networkOutputInt16=76576,networkBitExact=True,
    counterCount=18,countersBitExact=True,normalizedVectorElements=1890,integerAggregationExact=True,
    weightMassQ15=int(meta[0]),weightMassFloatReference=float(fmass),
    weightMassRelativeError=float(abs(meta[0]/32768-fmass)/fmass) if fmass else 0,
    maximumNormalizedVectorDifferenceVsFloat=float(np.max(abs(vector-float_vector))),
    supportGateDifferences=support_differences,windowActivityQ15=int(meta[1]),windowActivityFloat=float(active),
    activeGate=bool(meta[2]),effectiveTF=int(meta[3]),aggregationSigmoidClamps=int(meta[4]),
    CPUSeconds=elapsed,notHardwareCycles=True,sourceInputSHA256=sha(source),
    inheritedV4SHA256=sha(B/'phase13_pl_port_20261021/nn/hls_parallel/variant4/srpdnn_v4.cpp'),
    HLSFullSystem10Hz=False)
(P/'C_ACCEPTANCE.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
