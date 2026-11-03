"""Generate a plain-Verilog BD module-reference wrapper from the live top ABI.
No Vivado execution. Changes are confined to this board directory.
"""
import pathlib,re,json,hashlib
here=pathlib.Path(__file__).resolve().parent
source=here.parent/'instrument_top.sv'
s=source.read_text(); header=s[s.index('module instrument_top(')+len('module instrument_top('):s.index('\n);')]
ports=[]
for decl in header.split(','):
    # compact ANSI declarations can share a direction and width
    decl=decl.strip()
    m=re.match(r'(input|output|inout)\s+wire\s*(\[[^]]+\])?\s*(\w+)$',decl)
    if m: direction,width,name=m.groups(); width=width or ''; previous=(direction,width)
    else:
        m=re.fullmatch(r'(\w+)',decl)
        if not m: raise ValueError(decl)
        name=m.group(1); direction,width=previous
    ports.append((direction,width,name))
original_ports=list(ports)
ports += [('output','[7:0]','feature_arlen'),('output','[2:0]','feature_arsize'),('output','[1:0]','feature_arburst')]
lines=['// Generated from instrument_top.sv; do not hand edit.','module instrument_bd(']
for i,(direction,width,name) in enumerate(ports):
    attrs=[]
    if name in ('clk_compute','clk_audio'):
        attrs.append(f'X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 {name} CLK"')
        if name=='clk_compute': attrs.append('X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF RAW:WIN:FFT:SCALAR:FEATURE:HOST, ASSOCIATED_RESET rst_n, FREQ_HZ 50000000"')
        else: attrs.append('X_INTERFACE_PARAMETER = "FREQ_HZ 49162011"')
    elif name=='rst_n': attrs=['X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 rst_n RST"','X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW"']
    elif name=='irq': attrs=['X_INTERFACE_INFO = "xilinx.com:signal:interrupt:1.0 irq INTERRUPT"','X_INTERFACE_PARAMETER = "SENSITIVITY LEVEL_HIGH"']
    elif '_' in name:
        bus,suffix=name.split('_',1)
        if bus in ['raw','win','fft','scalar','feature','host']:
            attrs=[f'X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 {bus.upper()} {suffix.upper()}"']
            first={'raw':'awaddr','win':'awaddr','fft':'awaddr','scalar':'awaddr','feature':'araddr','host':'awaddr'}
            if suffix==first[bus]:
                protocol='AXI4LITE' if bus=='host' else 'AXI4'; mode='WRITE_ONLY' if bus in ('raw','win') else 'READ_ONLY' if bus=='feature' else 'READ_WRITE'
                attrs.append(f'X_INTERFACE_PARAMETER = "PROTOCOL {protocol}, DATA_WIDTH 32, ADDR_WIDTH {12 if bus=="host" else 32}, READ_WRITE_MODE {mode}, HAS_BURST {0 if bus=="host" else 1}, MAX_BURST_LENGTH {1 if bus=="feature" else 16}, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1"')
    if attrs: lines.append(' (* '+', '.join(attrs)+' *)')
    lines.append(f' {direction} wire {width} {name}'+(',' if i<len(ports)-1 else ''))
lines+=[');',' instrument_top u_core(', ',\n'.join('  .'+n+'('+n+')' for _,_,n in original_ports), ' );', " assign feature_arlen=8'd0; assign feature_arsize=3'd2; assign feature_arburst=2'b01;",'endmodule','']
(here/'instrument_bd.v').write_text('\n'.join(lines))
(here/'WRAPPER_ABI.json').write_text(json.dumps({'topSHA256':hashlib.sha256(source.read_bytes()).hexdigest(),'ports':len(ports),'status':'generated-not-Vivado-validated'},indent=2))
print('Generated',len(ports),'ports')
