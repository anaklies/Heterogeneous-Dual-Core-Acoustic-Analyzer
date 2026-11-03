`timescale 1ns/1ps
module tb_environment_config;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0;
    reg signed [15:0] temperature_centi=2000;
    reg temperature_valid=1,humidity_valid=1,pressure_valid=1;
    reg [15:0] humidity_raw=32768;reg [31:0] pressure_pa=101325;
    wire air_busy,air_done;wire [31:0] sound_speed_float;wire signed [31:0] sound_speed_q16,effective_temperature_q16;wire [1:0] environment_mode;
    wire busy,done,world_frame_valid,temp_compensated,write_valid;reg write_ready=1;
    wire [3:0] write_address;wire [31:0] write_float;
    reg [287:0] rotation_q16={32'd65536,32'd0,32'd0,32'd0,32'd65536,32'd0,32'd0,32'd0,32'd65536};
    reg rotation_valid=1;reg [7:0] observations=20,background_observations=20;
    reg background_enabled=0;reg [31:0] background_ratio_float=0,dt_float=32'h3e800000;
    air_sound_speed #(.COEFF_FILE("air_coeff.mem")) air(.clk(clk),.rst_n(rst_n),.start(start),
        .temperature_centi(temperature_centi),.temperature_valid(temperature_valid),.humidity_raw(humidity_raw),.humidity_valid(humidity_valid),
        .pressure_pa(pressure_pa),.pressure_valid(pressure_valid),.busy(air_busy),.done(air_done),
        .sound_speed_float(sound_speed_float),.sound_speed_q16(sound_speed_q16),.effective_temperature_q16(effective_temperature_q16),.environment_mode(environment_mode));
    sensor_config_writer #(.HAS_AIR_SOUND_SPEED(1)) dut(.start(air_done),.sound_speed_valid(1'b1),.*);
    integer count=0;
    always @(posedge clk)if(write_valid && write_ready)
    begin
        if(write_address==0 && write_float==32'h41a00000)$fatal(1,"uncorrected physical temperature was sent to legacy kernel");
        if(write_address==14 && write_float!=0)$fatal(1,"legacy configuration slot 14 changed");
        count=count+1;
    end
    initial
    begin
        repeat(4)@(negedge clk);rst_n=1;start=1;@(negedge clk);start=0;
        wait(done);@(negedge clk);
        if(count!=16 || !temp_compensated || environment_mode!=3)$fatal(1,"environment configuration incomplete");
        $display("PASS corrected speed encoded into actual MUSIC configuration; physical telemetry separate; Q16 speed %0d, effective temperature %0d",sound_speed_q16,effective_temperature_q16);
        $finish;
    end
    initial begin #100000;$fatal(1,"environment/config integration deadlock");end
endmodule
