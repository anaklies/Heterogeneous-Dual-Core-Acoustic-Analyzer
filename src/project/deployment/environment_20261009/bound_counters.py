from pathlib import Path
P=Path(__file__).resolve().parent;F=P.parents[2]/'sixmic3D_fpga'
p=P/'covariance_6ch.sv';s=p.read_text();assert 'integer i, j, pair_index;' in s
s=s.replace('integer i, j, pair_index;', 'reg [2:0] i, j;\n    reg [4:0] pair_index;')
p.write_text(s)
for name,width in [('cnn_v3_fixed.sv','$clog2(FREQ * TIME * 8 + 2)'),('cnn_v3_tiled.sv','$clog2(TOTAL_FREQ * 160 + 2)')]:
    s=(F/'pl/rtl'/name).read_text();assert 'reg [31:0] loaded;' in s
    s=s.replace('reg [31:0] loaded;',f'reg [{width}-1:0] loaded;')
    (P/name).write_text(s)
s=(F/'pl/rtl/pl_health_monitor.sv').read_text()
s=s.replace('reg [31:0] sample_age, stage_age, cooldown_count;', '''reg [$clog2(SAMPLE_TIMEOUT+1)-1:0] sample_age;
    reg [$clog2(STAGE_TIMEOUT+1)-1:0] stage_age;
    reg [$clog2(COOLDOWN+1)-1:0] cooldown_count;''')
(P/'pl_health_monitor.sv').write_text(s)
print('Bounded address/sample counters to their reachable maxima; signal/sample precision unchanged.')
