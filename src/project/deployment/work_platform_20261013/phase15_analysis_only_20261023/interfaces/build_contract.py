"""Derive control offsets from the actual exported HLS driver headers."""
from pathlib import Path
import hashlib,json,re
P=Path(__file__).resolve().parents[1];ROOT=P.parents[2]
specs=[('analysis','p18_analysis_extended','analysis_dma_safe',0x44A30000),
       ('fft','p18_shared_fft','analysis_fft2048',0x44A40000)]
rows=[];defines=['#ifndef SIXMIC_ANALYSIS_KERNEL_REGS_H','#define SIXMIC_ANALYSIS_KERNEL_REGS_H']
for name,build,top,base in specs:
    header=ROOT/'tmp'/build/'hls/impl/ip/drivers'/f'{top}_v1_0/src'/f'x{top}_hw.h'
    text=header.read_text();offsets={}
    for key,value in re.findall(r'#define\s+\w+_CONTROL_ADDR_(\w+)\s+(0x[0-9a-fA-F]+)',text):
        offsets[key]=int(value,16);defines.append(f'#define SIXMIC_{name.upper()}_{key} {value}u')
    rows.append(dict(name=name,top=top,base=base,clockHz=50000000,
                     offsets=offsets,header=str(header),headerSHA256=hashlib.sha256(header.read_bytes()).hexdigest()))
defines.append('#endif')
(P/'interfaces/kernel_registers.h').write_text('\n'.join(defines)+'\n')
(P/'interfaces/KERNEL_PORTS.json').write_text(json.dumps(dict(protocolVersion=2,kernels=rows,
    automaticDOA=False,actualHardwareCapabilityMask=0,algorithmVersion=0,wholeBoardAccepted=False,
    oldJobBridgeCompatibleWithoutChanges=False,
    bridgeRequirement='CONTROL_MIN=0x44a30000,CONTROL_MAX=0x44a4ffff; read status from kernel+0x60/0x40, not DDR; DDR is unreachable from JOB',
    arenaUnits='float32 words',pointers='32bit physical DMA addresses, not process virtual pointers'),indent=2))
print('KERNEL_CONTRACT actual generated headers: analysis status=0x60, FFT status=0x40')
