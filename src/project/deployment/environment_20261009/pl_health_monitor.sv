`timescale 1ns/1ps
// Diagnostics are evidence of an abnormal stream, not an identity sensor.
// Silence and identical source waveforms may resemble a disconnected/wired-together mic.

module pl_health_monitor #(
    parameter CLK_HZ = 49162010,
    STUCK_SAMPLES = 4096,
    CLIP_SAMPLES = 8,
    parameter SAMPLE_TIMEOUT = CLK_HZ / 10,
    STAGE_TIMEOUT = CLK_HZ * 12,
    parameter COOLDOWN = CLK_HZ / 5,
    MAX_RETRIES = 3
)
(
    input  wire clk,
    input  wire rst_n,
    input  wire clear_latched,
    input  wire sample_valid,
    input  wire [143:0] pcm,
    input  wire orientation_valid,
    input  wire temperature_valid,
    input  wire [7:0] sensor_faults,
    input  wire overrun,
    input  wire window_clip,
    input  wire fft_error,
    input  wire pipeline_error,
    input  wire backend_busy,
    input  wire backend_done,
    input  wire [3:0] backend_fault,
    input  wire result_frame_committed,
    output wire [31:0] active_faults,
    output reg [31:0] latched_faults,
    output reg recovery_request,
    output wire coordinates_permitted,
    output reg [3:0] restart_count
);

    localparam SW = $clog2(STUCK_SAMPLES + 1), CW = $clog2(CLIP_SAMPLES + 1);
    reg [23:0] previous[0:5];
    reg [SW - 1:0] constant_count[0:5], duplicate_count[0:4];
    reg [CW - 1:0] clip_count[0:5];
    reg have_sample;
    reg [$clog2(SAMPLE_TIMEOUT+1)-1:0] sample_age;
    reg [$clog2(STAGE_TIMEOUT+1)-1:0] stage_age;
    reg [$clog2(COOLDOWN+1)-1:0] cooldown_count;
    reg recovery_latched;
    wire sample_missing = sample_age >= SAMPLE_TIMEOUT;
    wire stage_stalled = backend_busy && stage_age >= STAGE_TIMEOUT;
    wire recoverable = overrun || window_clip || fft_error || pipeline_error || stage_stalled ||
        (backend_done && backend_fault != 0);
    wire restart_exhausted = restart_count >= MAX_RETRIES;
    genvar i;
    generate
        for (i = 0;i < 6;i = i + 1)
        begin
            assign active_faults[i] = have_sample && constant_count[i] >= STUCK_SAMPLES;
            assign active_faults[6 + i] = clip_count[i] >= CLIP_SAMPLES;
        end
        for (i = 0;i < 5;i = i + 1)
        begin
            assign active_faults[12 + i] = have_sample && duplicate_count[i] >= STUCK_SAMPLES;
        end
    endgenerate
    assign active_faults[17] = sample_missing;
    assign active_faults[18] = !orientation_valid;
    assign active_faults[19] = !temperature_valid;
    // Preserve a compact summary here; the AXI mailbox exposes all eight
    // individual sensor fault bits in sensor_fault_details.
    assign active_faults[20] = sensor_faults[0] | sensor_faults[4] | sensor_faults[5];
    assign active_faults[21] = sensor_faults[1];
    assign active_faults[22] = sensor_faults[2] | sensor_faults[6];
    assign active_faults[23] = sensor_faults[3] | sensor_faults[7];
    assign active_faults[24] = overrun;
    assign active_faults[25] = window_clip;
    assign active_faults[26] = fft_error;
    assign active_faults[27] = pipeline_error;
    assign active_faults[28] = backend_fault != 0;
    assign active_faults[29] = stage_stalled;
    assign active_faults[30] = backend_fault == 9;
    assign active_faults[31] = restart_exhausted;
    // Temperature/IMU faults use documented local-frame/default-temperature fallback.
    // Duplicate-channel evidence is diagnostic only, since acoustics can produce it.
    assign coordinates_permitted = have_sample && !( | active_faults[11:0]) && !sample_missing &&
        !overrun && !window_clip && !fft_error && !pipeline_error &&
        !stage_stalled && backend_fault == 0 && !restart_exhausted;

    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            have_sample <= 0;
            sample_age <= 0;
            stage_age <= 0;
            cooldown_count <= 0;
            restart_count <= 0;
            recovery_request <= 0;
            recovery_latched <= 0;
            latched_faults <= 0;
            for (integer c = 0;c < 6;c = c + 1)
            begin
                previous[c] <= 0;
                constant_count[c] <= 0;
                clip_count[c] <= 0;
            end
            for (integer c = 0;c < 5;c = c + 1)duplicate_count[c] <= 0;
        end

        else
        begin
            recovery_request <= 0;
            latched_faults <= (clear_latched?32'd0:latched_faults) | active_faults;
            if (sample_valid)
            begin
                have_sample <= 1;
                sample_age <= 0;
                for (integer c = 0;c < 6;c = c + 1)
                begin
                    previous[c] <= pcm[c * 24 +: 24];
                    if (have_sample && pcm[c * 24 +: 24] == previous[c])
                    begin
                        if (constant_count[c] < STUCK_SAMPLES)constant_count[c] <= constant_count[c] + 1;
                    end

                    else constant_count[c] <= 0;
                    if (pcm[c * 24 +: 24] == 24'h7fffff || pcm[c * 24 +: 24] == 24'h800000)
                    begin
                        if (clip_count[c] < CLIP_SAMPLES)clip_count[c] <= clip_count[c] + 1;
                    end

                    else clip_count[c] <= 0;
                end
                for (integer c = 0;c < 5;c = c + 1)
                begin
                    if (pcm[(c + 1) * 24 +: 24] == pcm[23:0])
                    begin
                        if (duplicate_count[c] < STUCK_SAMPLES)duplicate_count[c] <= duplicate_count[c] + 1;
                    end

                    else duplicate_count[c] <= 0;
                end
            end

            else if (sample_age < SAMPLE_TIMEOUT)sample_age <= sample_age + 1;
            if (!backend_busy || backend_done)stage_age <= 0;
            else if (stage_age < STAGE_TIMEOUT)stage_age <= stage_age + 1;
            if (cooldown_count != 0)cooldown_count <= cooldown_count - 1;
            if (!recoverable)recovery_latched <= 0;
            if (result_frame_committed && coordinates_permitted)
            begin
                restart_count <= 0;
            end

            else if (recoverable && !recovery_latched && cooldown_count == 0 && !restart_exhausted)
            begin
                recovery_request <= 1;
                recovery_latched <= 1;
                restart_count <= restart_count + 1;
                cooldown_count <= COOLDOWN;
            end
        end
    end
endmodule
