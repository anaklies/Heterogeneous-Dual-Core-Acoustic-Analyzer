"""PL-only raw signed-PCM24 conversion after bit-preserving capture-buffer copy."""
from programs import Code

def convert_pcm24(count,offset):
    if count<1 or offset<0:raise ValueError('empty or invalid raw buffer')
    c=Code();c.u(0,0);c.u(1,0);c.f(2,1/8388608)
    start=len(c.words)
    c.emit(20,2,0,imm=offset,target=2)
    # Raw writer guarantees sign-extended signed24. No PS signal normalization.
    c.emit(22,0,2);c.emit(6,0,0,2);c.store(0,0,offset)
    c.addi(0,0,1);c.loop(0,count,start);c.emit(0)
    return c,offset+count,dict(service='PCM24 format conversion',units='FS',capture_format='sign extended s24 in LE32')
