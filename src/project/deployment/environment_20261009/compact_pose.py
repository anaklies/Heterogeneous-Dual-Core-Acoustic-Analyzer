from pathlib import Path
P=Path(__file__).resolve().parent
p=P/'imu_rotation_q16.sv';s=p.read_text()
s=s.replace('reg [255:0] pending_matrix;','''reg [143:0] pending_matrix;
    wire [255:0] expanded_pending;
    generate for(genvar e=0;e<8;e=e+1) begin: expand_pose
        assign expanded_pending[e*32+:32]={{14{pending_matrix[e*18+17]}},pending_matrix[e*18+:18]};
    end endgenerate''')
s=s.replace('pending_matrix[index * 32 +: 32] <= negative?-$signed(quotient[31:0]):quotient[31:0];',
            'pending_matrix[index * 18 +: 18] <= negative?-$signed(quotient[17:0]):quotient[17:0];')
s=s.replace('pending_matrix};','expanded_pending};')
assert 'index * 32' not in s
p.write_text(s)
p=P/'sensor_i2c_hub.sv';s=p.read_text()
s=s.replace('output wire orientation_valid,','output wire orientation_valid,\n    output reg orientation_update,')
s=s.replace('imu_seen <= 0;','imu_seen <= 0;\n            orientation_update <= 0;')
s=s.replace('            start <= 0;\n            // A single','            start <= 0;\n            orientation_update <= 0;\n            // A single')
s=s.replace('imu_age <= 0;','imu_age <= 0;\n                        orientation_update <= 1;')
p.write_text(s)
p=P/'sixmic_frontend_top.sv';s=p.read_text()
s=s.replace('    sensor_i2c_hub #','    wire orientation_update;\n    sensor_i2c_hub #')
s=s.replace('.orientation_valid(orientation_valid),','.orientation_valid(orientation_valid), .orientation_update(orientation_update),')
a=s.index('    reg [22:0] orientation_poll;');b=s.index('    imu_rotation_q16 rotation',a)
s=s[:a]+s[b:]
s=s.replace('orientation_valid && orientation_poll == 4916200 && !rotation_busy','orientation_update && !rotation_busy')
p.write_text(s)
p=P/'tb_sensor_environment.sv';s=p.read_text().replace('wire temperature_valid, orientation_valid, pressure_valid;','wire temperature_valid, orientation_valid, pressure_valid, orientation_update;');p.write_text(s)
p=P/'sensor_config_writer.sv';s=p.read_text()
s=s.replace('reg [28:0] temp_dividend, temp_quotient;','reg [28:0] temp_dividend;\n    reg [21:0] temp_quotient;')
s=s.replace('wire [28:0] temp_next_quotient = {temp_quotient[27:0],','wire [21:0] temp_next_quotient = {temp_quotient[20:0],')
s=s.replace("{3'b0, temp_next_quotient}","{10'b0, temp_next_quotient}")
p.write_text(s)
print('Exact 18-bit normalized pose storage, sensor update strobe and bounded temperature quotient.')
