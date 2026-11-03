`timescale 1ns / 1ps
module tb_environment_frame_snapshot;
    reg clk = 0;
    always #10 clk = !clk;
    reg rst_n = 0, frame_start = 0;
    reg [31:0] frame_id = 0;
    reg signed [15:0] temperature_centi = 2500;
    reg temperature_valid = 1;
    reg [15:0] humidity_raw = 32768;
    reg [31:0] pressure_pa = 101325;
    reg pressure_valid = 1, orientation_valid = 1;
    reg signed [15:0] qw=32767, qx=0, qy=0, qz=0;
    reg [7:0] sensor_faults=0;
    reg [15:0] sensor_error_count=0;
    wire snapshot_valid;
    wire [31:0] snapshot_frame_id;
    wire signed [15:0] frame_temperature_centi, frame_qw, frame_qx, frame_qy, frame_qz;
    wire frame_temperature_valid, frame_humidity_valid, frame_pressure_valid, frame_orientation_valid;
    wire [15:0] frame_humidity_raw, frame_fault_flags, frame_sensor_error_count, environment_recovery_count;
    wire [31:0] frame_pressure_pa, frame_sound_speed_float;
    wire signed [31:0] frame_sound_speed_q16;
    wire [1:0] frame_environment_mode;
    environment_frame_snapshot dut (.*);

    // Deliberately undersized timeout exercises bounded recovery with the real arithmetic core.
    wire [15:0] recovery_count;
    environment_frame_snapshot #(.ENV_TIMEOUT_CYCLES(4)) recovery_dut (
        .clk(clk), .rst_n(rst_n), .frame_start(frame_start), .frame_id(frame_id),
        .temperature_centi(temperature_centi), .temperature_valid(temperature_valid),
        .humidity_raw(humidity_raw), .pressure_pa(pressure_pa), .pressure_valid(pressure_valid),
        .orientation_valid(orientation_valid), .qw(qw), .qx(qx), .qy(qy), .qz(qz),
        .sensor_faults(sensor_faults), .sensor_error_count(sensor_error_count),
        .environment_recovery_count(recovery_count)
    );

    // Elaborate the complete physical subsystem without fabricating I2C ACKs.
    tri1 sensor_scl, sensor_sda;
    sixmic_sensor_subsystem physical (
        .clk(clk), .rst_n(rst_n), .frame_start(frame_start), .frame_id(frame_id),
        .sensor_scl(sensor_scl), .sensor_sda(sensor_sda)
    );

    task pulse(input [31:0] id);
        begin
            @(negedge clk); frame_id=id; frame_start=1;
            @(negedge clk); frame_start=0;
        end
    endtask
    reg signed [31:0] held_speed;
    initial begin
        repeat(5) @(negedge clk);
        rst_n=1;
        repeat(800) @(negedge clk);
        pulse(32'd10);
        if (!snapshot_valid || snapshot_frame_id!=10 || !frame_temperature_valid ||
            !frame_humidity_valid || !frame_pressure_valid || !frame_orientation_valid ||
            frame_environment_mode!=3 || frame_temperature_centi!=2500 ||
            frame_humidity_raw!=32768 || frame_pressure_pa!=101325)
            $fatal(1,"valid sensor bundle failed");
        if (frame_sound_speed_q16<32'sd22544384 || frame_sound_speed_q16>32'sd22937600)
            $fatal(1,"unexpected 25C moist speed");
        held_speed=frame_sound_speed_q16;
        @(negedge clk);
        temperature_centi=1000; humidity_raw=60000; pressure_pa=90000;
        qw=23170; qx=0; qy=0; qz=23170;
        repeat(50) @(negedge clk);
        if (snapshot_frame_id!=10 || frame_temperature_centi!=2500 || frame_sound_speed_q16!=held_speed || frame_qz!=0)
            $fatal(1,"frame changed between boundaries");
        pulse(32'd11);
        // The completed job uses a coherent old environment; pose is current at frame boundary.
        if (snapshot_frame_id!=11 || frame_qz!=23170) $fatal(1,"frame id/pose failed");
        repeat(800) @(negedge clk);
        pulse(32'd12);
        if (frame_temperature_centi!=1000 || frame_humidity_raw!=60000 || frame_pressure_pa!=90000 || frame_environment_mode!=3)
            $fatal(1,"new environment job not committed");
        if (frame_sound_speed_q16>=held_speed) $fatal(1,"colder temperature did not reduce speed");

        @(negedge clk);
        temperature_valid=0; pressure_valid=0; orientation_valid=0;
        sensor_faults=8'h25; sensor_error_count=7;
        pulse(32'd13);
        if (frame_temperature_valid || frame_humidity_valid || frame_pressure_valid || frame_orientation_valid ||
            frame_environment_mode!=0 || frame_sound_speed_q16!=22478574 || frame_qw!=32767 || frame_qz!=0 ||
            frame_fault_flags[7:0]!=8'h25 || frame_sensor_error_count!=7)
            $fatal(1,"expired sensor safe fallback failed");
        repeat(800) @(negedge clk);
        @(negedge clk);
        temperature_centi=2000; humidity_raw=32768; pressure_pa=101325;
        temperature_valid=1; pressure_valid=1; orientation_valid=1;
        pulse(32'd14);
        repeat(800) @(negedge clk);
        pulse(32'd15);
        if (!frame_temperature_valid || !frame_pressure_valid || frame_temperature_centi!=2000 || frame_environment_mode!=3)
            $fatal(1,"sensor recovery failed");
        if (recovery_count==0 || environment_recovery_count!=0) $fatal(1,"watchdog isolation failed");
        $display("PASS ENVIRONMENT_SNAPSHOT valid atomic stale fallback recovery watchdog");
        $finish;
    end
    initial begin
        #200000;
        $fatal(1,"test timeout");
    end
endmodule
