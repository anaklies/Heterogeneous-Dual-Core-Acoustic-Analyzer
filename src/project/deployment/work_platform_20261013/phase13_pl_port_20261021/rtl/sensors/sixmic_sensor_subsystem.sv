`timescale 1ns / 1ps

module sixmic_sensor_subsystem #(
    parameter integer CLK_HZ = 50000000,
    parameter [6:0] IMU_ADDRESS = 7'h50,
    parameter [6:0] SHT_ADDRESS = 7'h44,
    parameter COEFF_FILE = "rtl/sensors/air_coeff.mem"
)
(
    input wire clk, rst_n,
    input wire frame_start,
    input wire [31:0] frame_id,
    inout wire sensor_scl, sensor_sda,
    output wire snapshot_valid,
    output wire [31:0] snapshot_frame_id,
    output wire signed [15:0] frame_temperature_centi,
    output wire frame_temperature_valid,
    output wire [15:0] frame_humidity_raw,
    output wire frame_humidity_valid,
    output wire [31:0] frame_pressure_pa,
    output wire frame_pressure_valid,
    output wire frame_orientation_valid,
    output wire signed [15:0] frame_qw, frame_qx, frame_qy, frame_qz,
    output wire signed [31:0] frame_sound_speed_q16,
    output wire [31:0] frame_sound_speed_float,
    output wire [1:0] frame_environment_mode,
    output wire [15:0] frame_fault_flags,
    output wire [15:0] frame_sensor_error_count,
    output wire [15:0] environment_recovery_count
);
    wire signed [15:0] temperature_centi, qw, qx, qy, qz;
    wire temperature_valid, pressure_valid, orientation_valid, orientation_update;
    wire [15:0] humidity_raw, sensor_error_count;
    wire [31:0] pressure_pa;
    wire signed [15:0] unused_roll, unused_pitch, unused_yaw;
    wire [7:0] sensor_faults;

    sensor_i2c_hub #(.CLK_HZ(CLK_HZ), .IMU_ADDRESS(IMU_ADDRESS), .SHT_ADDRESS(SHT_ADDRESS)) hub (
        .clk(clk), .rst_n(rst_n), .scl(sensor_scl), .sda(sensor_sda),
        .temperature_centi(temperature_centi), .temperature_valid(temperature_valid),
        .humidity_raw(humidity_raw), .pressure_pa(pressure_pa), .pressure_valid(pressure_valid),
        .orientation_valid(orientation_valid), .orientation_update(orientation_update),
        .qw(qw), .qx(qx), .qy(qy), .qz(qz),
        .roll(unused_roll), .pitch(unused_pitch), .yaw(unused_yaw),
        .sensor_faults(sensor_faults), .error_count(sensor_error_count)
    );
    environment_frame_snapshot #(.COEFF_FILE(COEFF_FILE)) frame_snapshot (.*);
endmodule
