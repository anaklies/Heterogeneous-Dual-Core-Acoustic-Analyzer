`timescale 1ns / 1ps

// One clock domain. Publish complete environment and pose records at a frame boundary.
// Sensor validity means a recent accepted digital sample, not physical calibration.
module environment_frame_snapshot #(
    parameter COEFF_FILE = "rtl/sensors/air_coeff.mem",
    parameter integer ENV_TIMEOUT_CYCLES = 2048
)
(
    input wire clk,
    input wire rst_n,
    input wire frame_start,
    input wire [31:0] frame_id,
    input wire signed [15:0] temperature_centi,
    input wire temperature_valid,
    input wire [15:0] humidity_raw,
    input wire [31:0] pressure_pa,
    input wire pressure_valid,
    input wire orientation_valid,
    input wire signed [15:0] qw, qx, qy, qz,
    input wire [7:0] sensor_faults,
    input wire [15:0] sensor_error_count,
    output reg snapshot_valid,
    output reg [31:0] snapshot_frame_id,
    output reg signed [15:0] frame_temperature_centi,
    output reg frame_temperature_valid,
    output reg [15:0] frame_humidity_raw,
    output reg frame_humidity_valid,
    output reg [31:0] frame_pressure_pa,
    output reg frame_pressure_valid,
    output reg frame_orientation_valid,
    output reg signed [15:0] frame_qw, frame_qx, frame_qy, frame_qz,
    output reg signed [31:0] frame_sound_speed_q16,
    output reg [31:0] frame_sound_speed_float,
    output reg [1:0] frame_environment_mode,
    output reg [15:0] frame_fault_flags,
    output reg [15:0] frame_sensor_error_count,
    output reg [15:0] environment_recovery_count
);
    localparam integer CW = $clog2(ENV_TIMEOUT_CYCLES + 1) > 0 ? $clog2(ENV_TIMEOUT_CYCLES + 1) : 1;
    localparam signed [31:0] DEFAULT_SPEED_Q16 = 32'sd22478574;
    localparam [31:0] DEFAULT_SPEED_FLOAT = 32'h43ab7f76;
    reg request_pending, waiting, core_start, core_reset;
    reg [CW-1:0] wait_count;
    reg signed [15:0] job_temp, cache_temp;
    reg [15:0] job_humidity, cache_humidity;
    reg [31:0] job_pressure, cache_pressure;
    reg job_temp_valid, job_pressure_valid, cache_temp_valid, cache_pressure_valid;
    reg cache_ready, timeout_seen;
    reg signed [31:0] cache_speed_q16;
    reg [31:0] cache_speed_float;
    reg [1:0] cache_mode;
    wire core_busy, core_done;
    wire signed [31:0] core_speed_q16, unused_effective_temperature;
    wire [31:0] core_speed_float;
    wire [1:0] core_mode;
    wire core_rst_n = rst_n && !core_reset;
    wire cache_current = cache_ready && cache_temp_valid == temperature_valid &&
                         cache_pressure_valid == pressure_valid;

    initial begin
        if (ENV_TIMEOUT_CYCLES < 1) $error("ENV_TIMEOUT_CYCLES must be positive");
    end

    air_sound_speed #(.COEFF_FILE(COEFF_FILE)) model (
        .clk(clk), .rst_n(core_rst_n), .start(core_start),
        .temperature_centi(job_temp), .temperature_valid(job_temp_valid),
        .humidity_raw(job_humidity), .humidity_valid(job_temp_valid),
        .pressure_pa(job_pressure), .pressure_valid(job_pressure_valid),
        .busy(core_busy), .done(core_done), .sound_speed_float(core_speed_float),
        .sound_speed_q16(core_speed_q16), .effective_temperature_q16(unused_effective_temperature),
        .environment_mode(core_mode)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            request_pending <= 1'b1;
            waiting <= 1'b0;
            core_start <= 1'b0;
            core_reset <= 1'b0;
            wait_count <= 0;
            job_temp <= 16'sd1930;
            job_humidity <= 0;
            job_pressure <= 0;
            job_temp_valid <= 0;
            job_pressure_valid <= 0;
            cache_temp <= 16'sd1930;
            cache_humidity <= 0;
            cache_pressure <= 0;
            cache_temp_valid <= 0;
            cache_pressure_valid <= 0;
            cache_ready <= 0;
            timeout_seen <= 0;
            cache_speed_q16 <= DEFAULT_SPEED_Q16;
            cache_speed_float <= DEFAULT_SPEED_FLOAT;
            cache_mode <= 0;
            snapshot_valid <= 0;
            snapshot_frame_id <= 0;
            frame_temperature_centi <= 16'sd1930;
            frame_temperature_valid <= 0;
            frame_humidity_raw <= 0;
            frame_humidity_valid <= 0;
            frame_pressure_pa <= 0;
            frame_pressure_valid <= 0;
            frame_orientation_valid <= 0;
            frame_qw <= 16'sd32767;
            frame_qx <= 0;
            frame_qy <= 0;
            frame_qz <= 0;
            frame_sound_speed_q16 <= DEFAULT_SPEED_Q16;
            frame_sound_speed_float <= DEFAULT_SPEED_FLOAT;
            frame_environment_mode <= 0;
            frame_fault_flags <= 16'h0f00;
            frame_sensor_error_count <= 0;
            environment_recovery_count <= 0;
        end else begin
            snapshot_valid <= 0;
            core_start <= 0;
            core_reset <= 0;
            if (frame_start) request_pending <= 1;

            // An expired accepted sample must not remain advertised as compensated.
            // A validity transition invalidates the old cache until a new job completes.
            if (waiting) begin
                if (core_done) begin
                    cache_temp <= job_temp;
                    cache_humidity <= job_humidity;
                    cache_pressure <= job_pressure;
                    cache_temp_valid <= job_temp_valid;
                    cache_pressure_valid <= job_pressure_valid;
                    cache_speed_q16 <= core_speed_q16;
                    cache_speed_float <= core_speed_float;
                    cache_mode <= core_mode;
                    cache_ready <= 1;
                    waiting <= 0;
                    wait_count <= 0;
                end else if (wait_count >= ENV_TIMEOUT_CYCLES-1) begin
                    waiting <= 0;
                    core_reset <= 1;
                    cache_ready <= 0;
                    timeout_seen <= 1;
                    request_pending <= 1;
                    wait_count <= 0;
                    if (environment_recovery_count != 16'hffff)
                        environment_recovery_count <= environment_recovery_count + 1;
                end else wait_count <= wait_count + 1;
            end else if (request_pending && !core_busy && !core_reset && !core_start) begin
                job_temp <= temperature_centi;
                job_humidity <= humidity_raw;
                job_pressure <= pressure_pa;
                job_temp_valid <= temperature_valid;
                job_pressure_valid <= pressure_valid;
                core_start <= 1;
                waiting <= 1;
                wait_count <= 0;
                // A simultaneous frame request is retained as one latest-value job.
                request_pending <= frame_start;
            end

            if (frame_start) begin
                snapshot_valid <= 1;
                snapshot_frame_id <= frame_id;
                frame_temperature_centi <= cache_temp;
                frame_humidity_raw <= cache_humidity;
                frame_pressure_pa <= cache_pressure;
                frame_temperature_valid <= cache_temp_valid && temperature_valid && cache_ready;
                frame_humidity_valid <= cache_temp_valid && temperature_valid && cache_ready;
                frame_pressure_valid <= cache_pressure_valid && pressure_valid && cache_ready;
                frame_sound_speed_q16 <= cache_current ? cache_speed_q16 : DEFAULT_SPEED_Q16;
                frame_sound_speed_float <= cache_current ? cache_speed_float : DEFAULT_SPEED_FLOAT;
                frame_environment_mode <= cache_current ? cache_mode : 0;
                frame_orientation_valid <= orientation_valid;
                frame_qw <= orientation_valid ? qw : 16'sd32767;
                frame_qx <= orientation_valid ? qx : 0;
                frame_qy <= orientation_valid ? qy : 0;
                frame_qz <= orientation_valid ? qz : 0;
                frame_fault_flags <= {3'b000, timeout_seen, !cache_current,
                                      !orientation_valid, !pressure_valid, !temperature_valid,
                                      sensor_faults};
                frame_sensor_error_count <= sensor_error_count;
            end
        end
    end
endmodule
