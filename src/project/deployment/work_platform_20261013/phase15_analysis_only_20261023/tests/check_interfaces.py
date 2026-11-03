from pathlib import Path
import sys,json
P=Path(__file__).resolve().parents[1];sys.path.insert(0,str(P/'interfaces'))
from packet_codec import encode,decode,FIELDS
r=json.loads((P/'interfaces/FUNCTION_REGISTRY.json').read_text())
assert not r['automaticDOA'] and not(r['tierMasks']['P0']&(1<<8)) and r['actualHardwareCapabilityMask']==0
contract=json.loads((P/'interfaces/KERNEL_PORTS.json').read_text())
assert {x['base'] for x in contract['kernels']}=={0x44A30000,0x44A40000}
assert contract['kernels'][0]['offsets']['STATUS_DATA']==0x60
assert contract['kernels'][1]['offsets']['STATUS_DATA']==0x40
d=dict.fromkeys(FIELDS,0);d.update(protocol_version=2,session_id=3,config_generation=7,sequence=2**40,
    first_sample=2**41,sample_count=2048,sample_rate=48000,payload_type=2,payload_bytes=128,payload_offset=16)
wire=encode(d);assert len(wire)==64
assert decode(wire,1024,3,7,0)==d
rejected=0
for edit in [dict(protocol_version=1),dict(config_generation=6),dict(payload_bytes=1024),dict(valid=1),dict(payload_type=8),dict(sample_rate=44100)]:
    changed=dict(d);changed.update(edit)
    try:decode(encode(changed),1024,3,7,0)
    except ValueError:rejected+=1
    else:raise AssertionError(edit)
assert rejected==6
good=dict(d,valid=1,algorithm_version=1)
assert decode(encode(good),1024,3,7,1<<3)==good
try:decode(encode(good),1024,3,7,1<<24)
except ValueError:rejected+=1
else:raise AssertionError('unrelated event capability must not validate spectrum')
(P/'results/interfaces.json').write_text(json.dumps(dict(roundtrip64bit=True,rejected=6,
    automaticDOADisabled=True,actualHardwareCapabilityMask=0,livePSPCValidated=False),indent=2))
print('INTERFACE_PASS 64bit roundtrip, 7 rejections; no live PS/PC claim')
