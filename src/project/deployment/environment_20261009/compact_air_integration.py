from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
old=(P/'air_coeff.mem').read_text().split();values=[int(v,16) for v in old]
values=[v-2**32 if v>=2**31 else v for v in values]
coef=[]
for i,v in enumerate(values):coef.append(int(np.rint(v/16)) if i%3!=2 else v)
assert all(-32768<=v<=32767 for v in coef)
(P/'air_delta_coeff.mem').write_text(''.join(f'{v&0xffff:04x}\n' for v in coef))
s=(P/'sensor_config_writer.sv').read_text()
s=s.replace('input wire signed [31:0] effective_temperature_q16,','input wire signed [19:0] temperature_correction_q16,')
s=s.replace('reg [31:0] ratio, dt, air_speed;','reg [31:0] ratio, dt;\n    reg air_ready;\n    reg signed [19:0] air_delta;')
s=s.replace('reg [1:0] state;','reg [2:0] state;').replace('TEMP_DIVIDE = 3;','TEMP_DIVIDE = 3, AIR_WAIT = 4;')
s=s.replace('air_speed <= 0;','air_ready <= 0;air_delta <= 0;')
s=s.replace('temp_q16 <= HAS_AIR_SOUND_SPEED && sound_speed_valid ? effective_temperature_q16 : 32\'sd1264844;',"temp_q16 <= 32'sd1264844;\n                air_ready <= 0;\n                if(HAS_AIR_SOUND_SPEED)state <= AIR_WAIT;")
s=s.replace('if (temp_usable && !(HAS_AIR_SOUND_SPEED && sound_speed_valid))','if (temp_usable)')
s=s.replace('            done <= 0;','''            done <= 0;
            if (HAS_AIR_SOUND_SPEED && busy && sound_speed_valid)
            begin air_ready <= 1;air_delta <= temperature_correction_q16;end''')
s=s.replace('                    state <= PREPARE;\n                end\n            end\n            PREPARE:', '''                    state <= HAS_AIR_SOUND_SPEED ? AIR_WAIT : PREPARE;
                end
            end
            AIR_WAIT:if (air_ready || sound_speed_valid)
            begin
                temp_q16 <= temp_q16 + $signed(sound_speed_valid ? temperature_correction_q16 : air_delta);
                state <= PREPARE;
            end
            PREPARE:''')
(P/'sensor_config_writer.sv').write_text(s)
s=(P/'sixmic_pl_top.sv').read_text();a=s.index('    reg signed [15:0] config_temperature;');b=s.index('    localization_backend_axi #',a)
s=s[:a]+'''    wire air_done, air_busy;
    wire signed [19:0] temperature_correction_q16;
    wire [1:0] air_mode;
    air_speed_correction #(.COEFF_FILE({COEFF_DIR,"/air_delta_coeff.mem"})) air(
        .clk(clk), .rst_n(reset_processing_n), .start(config_capture),
        .temperature_centi(temperature_centi), .temperature_valid(temperature_valid),
        .humidity_raw(humidity_raw), .humidity_valid(temperature_valid && !sensor_faults[2] && !sensor_faults[1]),
        .pressure_pa(pressure_pa), .pressure_valid(pressure_valid && !sensor_faults[5]),
        .busy(air_busy), .done(air_done), .temperature_correction_q16(temperature_correction_q16), .environment_mode(air_mode));
    sensor_config_writer #(.HAS_AIR_SOUND_SPEED(1)) config_writer(.clk(clk), .rst_n(reset_processing_n), .start(config_capture),
        .temperature_centi(temperature_centi), .temperature_valid(temperature_valid),
        .temperature_correction_q16(temperature_correction_q16), .sound_speed_valid(air_done),
        .rotation_q16(world_rotation_q16), .rotation_valid(world_rotation_valid),
        .observations(observation_count > 200?8'd200:observation_count[7:0]),
        .background_observations(8'd20), .background_enabled(config_mode && adaptive_use_cnn),
        .background_ratio_float((config_mode && adaptive_use_cnn)?32'h3f800000:32'd0), .dt_float(dt_float),
        .busy(), .done(config_done), .world_frame_valid(world_frame_valid), .temp_compensated(temp_compensated),
        .write_valid(config_write_valid), .write_ready(config_write_ready), .write_address(config_write_address), .write_float(config_write_float));
''' +s[b:]
(P/'sixmic_pl_top.sv').write_text(s)
print('Config writer shares physical-temperature conversion and pose epoch; compact correction block prepared.')
