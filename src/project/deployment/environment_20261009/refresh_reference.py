from pathlib import Path
P=Path(__file__).resolve().parent;F=P.parents[2]/'sixmic3D_fpga'
p=P/'pl_adaptive_mode.sv';s=p.read_text()
s=s.replace('output reg use_cnn','output reg use_cnn,\n    output reg clear_reference')
s=s.replace('use_cnn<=0;evaluate<=0;','use_cnn<=0;evaluate<=0;clear_reference<=0;')
s=s.replace('            evaluate<=0;','            evaluate<=0;clear_reference<=0;')
s=s.replace('if(!reference_qualified)use_cnn<=0;','if(!reference_qualified)begin use_cnn<=0;have_reference<=0;end')
s=s.replace('                if(use_cnn && reference_scaled<current_scaled)', '''                if({2'b0,reference_energy} > {current_energy,2'b0})
                begin
                    // Old loud reference no longer describes the room.
                    // Discard it before whitening can create false peaks.
                    use_cnn<=0;have_reference<=0;clear_reference<=1;
                end
                else if(use_cnn && reference_scaled<current_scaled)''')
p.write_text(s)
for name in ['pl_noise_floor.sv','pl_background_covariance.sv']:
    s=(F/'pl/rtl'/name).read_text()
    s=s.replace('input  wire rst_n,','input  wire rst_n,\n    input wire clear_reference,')
    s=s.replace('if (!rst_n)','if (!rst_n || clear_reference)')
    (P/name).write_text(s)
p=P/'sixmic_pl_top.sv';s=p.read_text()
s=s.replace('wire adaptive_use_cnn;','wire adaptive_use_cnn, clear_reference;')
s=s.replace('.use_cnn(adaptive_use_cnn));','.use_cnn(adaptive_use_cnn), .clear_reference(clear_reference));')
s=s.replace('pl_noise_floor reference_floor(.clk(clk), .rst_n(reset_processing_n),','pl_noise_floor reference_floor(.clk(clk), .rst_n(reset_processing_n), .clear_reference(clear_reference),')
s=s.replace('pl_background_covariance spatial_reference(.clk(clk), .rst_n(reset_processing_n),','pl_background_covariance spatial_reference(.clk(clk), .rst_n(reset_processing_n), .clear_reference(clear_reference),')
s=s.replace('if (short_arm && !spatial_reference_valid)', 'if ((short_arm && !spatial_reference_valid) || clear_reference)')
s=s.replace('if (!(short_arm && !spatial_reference_valid)) case','if (!((short_arm && !spatial_reference_valid) || clear_reference)) case')
p.write_text(s)
p=P/'tb_adaptive_mode.sv';s=p.read_text().replace('wire use_cnn;','wire use_cnn,clear_reference;reg cleared=0;')
s=s.replace('pl_adaptive_mode dut(.*);','pl_adaptive_mode dut(.*);\n    always @(posedge clk)if(clear_reference)cleared<=1;')
s=s.replace('        reference_qualified=0;repeat(3)@(negedge clk);','        window(20);if(use_cnn || !cleared)$fatal(1,"obsolete loud reference was not discarded");\n        reference_qualified=0;repeat(3)@(negedge clk);')
p.write_text(s)
print('Obsolete strong background is safely discarded, and spectral/covariance references reacquire together.')
