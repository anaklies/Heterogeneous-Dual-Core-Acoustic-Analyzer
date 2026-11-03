from pathlib import Path
P=Path(__file__).resolve().parent
FPGA=P.parents[2]/'sixmic3D_fpga'
def load(name):return (FPGA/'pl/rtl'/name).read_text()
def replace(s,old,new):
    assert old in s,old;s=s.replace(old,new);return s
s=load('sensor_config_writer.sv')
s=replace(s,'module sensor_config_writer\n','module sensor_config_writer #(parameter HAS_AIR_SOUND_SPEED = 0)\n')
s=replace(s,'input  wire temperature_valid,','input  wire temperature_valid,\n    input wire signed [31:0] effective_temperature_q16,\n    input wire sound_speed_valid,')
s=replace(s,'reg [31:0] ratio, dt;','reg [31:0] ratio, dt, air_speed;')
s=replace(s,'dt <= 0;','dt <= 0;\n            air_speed <= 0;')
s=replace(s,"temp_q16 <= 32'sd1264844;","temp_q16 <= HAS_AIR_SOUND_SPEED && sound_speed_valid ? effective_temperature_q16 : 32'sd1264844;")
s=replace(s,'if (temp_usable)','if (temp_usable && !(HAS_AIR_SOUND_SPEED && sound_speed_valid))')
(P/'sensor_config_writer.sv').write_text(s)
s=load('sixmic_frontend_top.sv')
s=replace(s,'output wire temperature_valid,','output wire temperature_valid,\n    output wire [15:0] humidity_raw,\n    output wire [31:0] pressure_pa,\n    output wire pressure_valid,')
s=replace(s,'.temperature_centi(temperature_centi), .temperature_valid(temperature_valid),',
          '.temperature_centi(temperature_centi), .temperature_valid(temperature_valid),\n        .humidity_raw(humidity_raw), .pressure_pa(pressure_pa), .pressure_valid(pressure_valid),')
(P/'sixmic_frontend_top.sv').write_text(s)
s=load('sixmic_pl_top.sv')
s=replace(s,'wire reference_ready, reference_noisy;','wire reference_ready, reference_noisy;\n    wire [15:0] humidity_raw;\n    wire [31:0] pressure_pa;\n    wire pressure_valid;')
s=replace(s,'.temperature_valid(temperature_valid), .orientation_valid(orientation_valid),',
          '.temperature_valid(temperature_valid), .orientation_valid(orientation_valid),\n        .humidity_raw(humidity_raw), .pressure_pa(pressure_pa), .pressure_valid(pressure_valid),')
s=replace(s,'sensor_config_writer config_writer(','''reg signed [15:0] config_temperature;
    reg config_temperature_valid, config_rotation_valid;
    reg [287:0] config_rotation;
    wire air_done, air_busy;
    wire [31:0] air_speed;
    wire signed [31:0] air_q16, effective_temperature_q16;
    wire [1:0] air_mode;
    always @(posedge clk)
    begin
        if (!reset_processing_n)
        begin
            config_temperature <= 1930;config_temperature_valid <= 0;
            config_rotation <= 0;config_rotation_valid <= 0;
        end
        else if (config_capture)
        begin
            config_temperature <= temperature_centi;config_temperature_valid <= temperature_valid;
            config_rotation <= world_rotation_q16;config_rotation_valid <= world_rotation_valid;
        end
    end
    air_sound_speed #(.COEFF_FILE({COEFF_DIR,"/air_coeff.mem"})) air(
        .clk(clk), .rst_n(reset_processing_n), .start(config_capture),
        .temperature_centi(temperature_centi), .temperature_valid(temperature_valid),
        .humidity_raw(humidity_raw), .humidity_valid(temperature_valid && !sensor_faults[2] && !sensor_faults[1]),
        .pressure_pa(pressure_pa), .pressure_valid(pressure_valid && !sensor_faults[5]),
        .busy(air_busy), .done(air_done), .sound_speed_float(air_speed),
        .sound_speed_q16(air_q16), .effective_temperature_q16(effective_temperature_q16), .environment_mode(air_mode));
    sensor_config_writer #(.HAS_AIR_SOUND_SPEED(1)) config_writer(''')
s=replace(s,'.rst_n(reset_processing_n), .start(config_capture),\n        .temperature_centi(temperature_centi), .temperature_valid(temperature_valid),\n        .rotation_q16(world_rotation_q16), .rotation_valid(world_rotation_valid),',
          '.rst_n(reset_processing_n), .start(air_done),\n        .temperature_centi(config_temperature), .temperature_valid(config_temperature_valid),\n        .effective_temperature_q16(effective_temperature_q16), .sound_speed_valid(1\'b1),\n        .rotation_q16(config_rotation), .rotation_valid(config_rotation_valid),')
(P/'sixmic_pl_top.sv').write_text(s)
