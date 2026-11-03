`timescale 1ns/1ps
// Integration checkpoint only: capture -> STFT -> covariance.
// No source-coordinate output exists here; localization is still to be added.

module sixmic_frontend_top #(
    parameter COEFF_DIR = "pl/coeff"
)
(
    input  wire clk_50m,
    input  wire rst_n,
    input  wire processing_restart,
    input  wire mic1_sd,
    input  wire mic2_sd,
    input  wire mic3_sd,
    input  wire mic4_sd,
    input  wire mic5_sd,
    input  wire mic6_sd,
    output wire mic1_sck,
    output wire mic2_sck,
    output wire mic3_sck,
    output wire mic4_sck,
    output wire mic5_sck,
    output wire mic6_sck,
    output wire mic1_ws,
    output wire mic2_ws,
    output wire mic3_ws,
    output wire mic4_ws,
    output wire mic5_ws,
    output wire mic6_ws,
    output wire clock_locked,
    output wire algorithm_clk,
    output wire algorithm_rst_n,
    input  wire covariance_clear,
    input  wire covariance_read_enable,
    input  wire covariance_pause,
    input  wire covariance_read_imag_enable,
    input  wire [10:0] covariance_read_address,
    input  wire [10:0] covariance_read_imag_address,
    output wire signed [47:0] covariance_real,
    output wire signed [47:0] covariance_imag,
    output wire [31:0] observation_count,
    output wire covariance_busy,
    output wire short_valid,
    input  wire short_ready,
    output wire [2:0] short_channel,
    output wire [10:0] short_bin,
    output wire signed [31:0] short_real,
    output wire signed [31:0] short_imag,
    output wire [31:0] short_frame_samples,
    inout wire sensor_scl,
    inout wire sensor_sda,
    output wire signed [15:0] temperature_centi,
    output wire signed [15:0] imu_qw,
    output wire signed [15:0] imu_qx,
    output wire signed [15:0] imu_qy,
    output wire signed [15:0] imu_qz,
    output wire signed [15:0] imu_roll,
    output wire signed [15:0] imu_pitch,
    output wire signed [15:0] imu_yaw,
    output wire temperature_valid,
    output wire [15:0] humidity_raw,
    output wire [31:0] pressure_pa,
    output wire pressure_valid,
    output wire orientation_valid,
    output wire [15:0] sensor_error_count,
    output wire [287:0] world_rotation_q16,
    output wire world_rotation_valid,
    output wire clock_fault,
    output wire reference_clock_fault,
    output wire [3:0] clock_restart_count,
    output wire [7:0] sensor_faults,
    output wire diagnostic_sample_valid,
    output wire [143:0] diagnostic_pcm,
    output wire overrun,
    output wire window_clip,
    output wire fft_protocol_error
);

    reg [4:0] recovery_hold;

    always @(posedge algorithm_clk)
    begin
        if (!algorithm_rst_n)recovery_hold <= 0;
        else if (processing_restart)recovery_hold <= 16;
        else if (recovery_hold != 0)recovery_hold <= recovery_hold - 1;
    end
    wire processing_rst_n = algorithm_rst_n && recovery_hold == 0 && !processing_restart;
    wire signed [23:0] mic1_data, mic2_data, mic3_data, mic4_data, mic5_data, mic6_data;
    wire sample_valid;
    assign diagnostic_sample_valid = sample_valid;
    assign diagnostic_pcm = {mic6_data, mic5_data, mic4_data, mic3_data, mic2_data, mic1_data};
    wire clock_recovery_reset, buffered_reference, reference_clk;
    IBUF reference_input_buffer(.I(clk_50m), .O(buffered_reference));
    BUFG reference_global_buffer(.I(buffered_reference), .O(reference_clk));
    (* ASYNC_REG="TRUE" *)reg [1:0] clock_fault_sync;
    assign clock_fault = clock_fault_sync[1];

    always @(posedge algorithm_clk or negedge rst_n)
    begin
        if (!rst_n)clock_fault_sync <= 2'b11;
        else clock_fault_sync <= {clock_fault_sync[0], reference_clock_fault};
    end
    reg [5:0] heartbeat_divider;

    always @(posedge algorithm_clk)
    begin
        if (!algorithm_rst_n)heartbeat_divider <= 0;
        else heartbeat_divider <= heartbeat_divider + 1;
    end
    clock_domain_guard clock_guard(.ref_clk(reference_clk), .rst_n(rst_n), .heartbeat(heartbeat_divider[5]),
        .clock_locked(clock_locked), .clock_fault(reference_clock_fault),
        .reset_clock_generator(clock_recovery_reset),
        .restart_count(clock_restart_count));
    sixmic_capture_bridge #(.ENABLE_CLOCK_RECOVERY(1)) capture(.clk_50m(reference_clk), .*);
    wire spectrum_valid, spectrum_ready, spectrum_short, spectrum_last_channel;
    wire [2:0] spectrum_channel;
    wire [10:0] spectrum_bin;
    wire signed [31:0] spectrum_real, spectrum_imag;
    wire [31:0] spectrum_frame_samples;
    wire covariance_ready;
    assign short_valid = spectrum_valid && spectrum_short;
    assign short_channel = spectrum_channel;
    assign short_bin = spectrum_bin;
    assign short_real = spectrum_real;
    assign short_imag = spectrum_imag;
    assign short_frame_samples = spectrum_frame_samples;
    assign spectrum_ready = spectrum_short?short_ready:(covariance_pause?1'b1:covariance_ready);
    stft_6ch_shared #(.COEFF_DIR(COEFF_DIR)) spectra(
    .clk(algorithm_clk), .rst_n(processing_rst_n), .sample_valid(sample_valid),
        .pcm({mic6_data, mic5_data, mic4_data, mic3_data, mic2_data, mic1_data}),
        .spectrum_valid(spectrum_valid), .spectrum_ready(spectrum_ready),
        .spectrum_short(spectrum_short), .spectrum_channel(spectrum_channel),
        .spectrum_bin(spectrum_bin), .spectrum_real(spectrum_real), .spectrum_imag(spectrum_imag),
        .spectrum_frame_samples(spectrum_frame_samples), .spectrum_last_channel(spectrum_last_channel),
        .overrun(overrun), .window_clip(window_clip), .fft_protocol_error(fft_protocol_error));
    covariance_6ch covariance(
    .clk(algorithm_clk), .rst_n(processing_rst_n), .clear(covariance_clear),
        .spectrum_valid(spectrum_valid && !spectrum_short && !covariance_pause),
        .spectrum_ready(covariance_ready),
        .spectrum_short(spectrum_short), .spectrum_channel(spectrum_channel), .spectrum_bin(spectrum_bin),
        .spectrum_real(spectrum_real), .spectrum_imag(spectrum_imag),
        .read_enable(covariance_read_enable), .read_address(covariance_read_address),
        .read_imag_enable(covariance_read_imag_enable), .read_imag_address(covariance_read_imag_address),
        .read_real(covariance_real), .read_imag(covariance_imag),
        .observation_count(observation_count), .busy(covariance_busy));
    wire orientation_update;
    sensor_i2c_hub #(.CLK_HZ(49162010)) sensors(
    .clk(algorithm_clk), .rst_n(algorithm_rst_n), .scl(sensor_scl), .sda(sensor_sda),
        .temperature_centi(temperature_centi), .temperature_valid(temperature_valid),
        .humidity_raw(humidity_raw), .pressure_pa(pressure_pa), .pressure_valid(pressure_valid),
        .orientation_valid(orientation_valid), .orientation_update(orientation_update),
        .qw(imu_qw), .qx(imu_qx), .qy(imu_qy), .qz(imu_qz), .roll(imu_roll), .pitch(imu_pitch), .yaw(imu_yaw),
        .sensor_faults(sensor_faults), .error_count(sensor_error_count));
    wire rotation_busy, rotation_done, rotation_valid;
    assign world_rotation_valid = rotation_valid && orientation_valid;
    imu_rotation_q16 rotation(.clk(algorithm_clk), .rst_n(algorithm_rst_n),
        .start(orientation_update && !rotation_busy),
        .qw(imu_qw), .qx(imu_qx), .qy(imu_qy), .qz(imu_qz),
        .busy(rotation_busy), .done(rotation_done), .valid(rotation_valid), .matrix_q16(world_rotation_q16));
endmodule
