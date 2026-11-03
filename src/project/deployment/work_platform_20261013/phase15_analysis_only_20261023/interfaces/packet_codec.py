"""Analysis descriptor codec only. No device/network side effects."""
import struct
WIRE=struct.Struct('<4I2Q8I')
FIELDS=('protocol_version','algorithm_version','session_id','config_generation',
        'sequence','first_sample','sample_count','sample_rate','payload_type',
        'payload_bytes','payload_offset','status','error_flags','valid')
CAPABILITIES_BY_PAYLOAD={
    1:(1<<1)|(1<<10)|(1<<25)|(1<<26),
    2:(1<<3)|(1<<4)|(1<<5)|(1<<6)|(1<<13)|(1<<14),
    3:(1<<11)|(1<<12)|(1<<21),
    4:(1<<18)|(1<<19)|(1<<37)|(1<<38),
    5:1<<24,
    6:(1<<46)|(1<<47)|(1<<48)|(1<<49)|(1<<50)|(1<<51),
    7:(1<<17)|(1<<35)|(1<<36)}
def encode(fields):
    return WIRE.pack(*(fields[k] for k in FIELDS))
def decode(data,arena_bytes,session_id,config_generation,capability_mask):
    if len(data)!=WIRE.size:raise ValueError('descriptor must be 64 bytes')
    d=dict(zip(FIELDS,WIRE.unpack(data)))
    if d['protocol_version']!=2:raise ValueError('protocol mismatch')
    if d['session_id']!=session_id or d['config_generation']!=config_generation:raise ValueError('stale result')
    if not 1<=d['payload_type']<=7 or d['sample_rate']!=48000 or d['valid'] not in (0,1):raise ValueError('invalid result type or sample clock')
    if d['payload_offset']>arena_bytes or d['payload_bytes']>arena_bytes-d['payload_offset']:raise ValueError('payload bounds')
    if d['valid'] and (d['status'] or d['error_flags'] or not(capability_mask & CAPABILITIES_BY_PAYLOAD[d['payload_type']]) or not d['algorithm_version']):raise ValueError('unaccepted or faulted result')
    return d
