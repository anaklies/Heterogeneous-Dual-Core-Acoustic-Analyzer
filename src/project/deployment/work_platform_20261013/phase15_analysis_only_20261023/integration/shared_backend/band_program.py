"""Build PL scalar microcode for one relative band-power statistic.
Python prepares descriptors only; deployed arithmetic runs in scalar_engine.
"""
import math
import numpy as np
PRIVATE=524288

def instruction(op,rd=0,ra=0,rb=0,imm=0,target=0):
    return [op|(rd<<8)|(ra<<13)|(rb<<18),imm,target,0]

def prepare_band(memory,sample_rate,low_hz,high_hz,channel=0,session=1,config=1,generation=1):
    if not 0<=channel<6 or not 0<=low_hz<high_hz<=sample_rate/2:
        raise ValueError('invalid channel or frequency band')
    if len(memory)<PRIVATE+12288:raise ValueError('arena too small')
    u=memory.view(np.uint32)
    bits=lambda x:int(np.array([x],np.float32).view(np.uint32)[0])
    first=math.ceil(low_hz*2048/sample_rate);last=math.floor(high_hz*2048/sample_rate)
    if first>last:raise ValueError('band contains no FFT bin')
    base=channel*8192+4097
    code=[instruction(14,imm=base+3*first),instruction(1,imm=bits(0)),
          instruction(1,2,imm=bits(sample_rate/2048)),
          instruction(2,1,ra=0,target=1),instruction(6,1,1,2),
          instruction(4,0,0,1),instruction(15,0,0,imm=3),
          instruction(16,ra=0,imm=base+3*(last+1),target=3),
          instruction(3,0,ra=1,target=1),instruction(0)]
    code_at=PRIVATE+128
    u[code_at:code_at+4*len(code)]=np.array(code,np.uint32).ravel()
    for slot in range(4):
        at=PRIVATE+slot*16
        u[at:at+16]=[0x414c5531,1,code_at,len(code),PRIVATE+2048+slot*80,
                      262144+slot*65536,49152,PRIVATE+8192+slot*64,16,64,2,
                      session,config,1,generation,0]
    return dict(descriptor=PRIVATE,first_bin=first,last_bin=last,
                output=PRIVATE+8192,units='relative FS squared',
                max_instructions=5*(last-first+1)+5)
