`timescale 1ns/1ps
// Window lifecycle only. Reference magnitudes/covariance must be supplied by
// a separate, explicitly validated calibration block; never learn a target as noise.

module pl_window_scheduler #(
    parameter ACQUIRE_TIMEOUT = 49162010,
    COMPUTE_TIMEOUT = 600000000
)
(
    input  wire clk,
    input  wire rst_n,
    input  wire enable,
    input  wire acquisition_valid,
    input  wire covariance_busy,
    input  wire [31:0] observation_count,
    input  wire short_complete,
    input  wire short_error,
    input  wire config_done,
    input  wire features_done,
    input  wire features_error,
    input  wire weights_done,
    input  wire cnn_required,
    input  wire flat_weights_done,
    input  wire flat_weights_error,
    output reg flat_weights_start,
    input  wire backend_ready,
    input  wire backend_done,
    input  wire [3:0] backend_fault,
    output reg covariance_clear,
    output reg short_arm,
    output reg config_capture,
    output reg features_start,
    output reg backend_request,
    output wire covariance_pause,
    output reg window_committed,
    output reg recovery_request,
    output reg [3:0] fault,
    output wire busy
);

    localparam OFF = 0, CLEAR = 1, WAIT_CLEAR = 2, ACQUIRE = 3, SNAPSHOT = 4, CONFIG = 5, FEATURES = 6,
        REQUEST = 7,
        RESULT = 8, FAULT = 9, BYPASS = 10;
    reg [3:0]state;
    reg [$clog2((ACQUIRE_TIMEOUT>COMPUTE_TIMEOUT?ACQUIRE_TIMEOUT:COMPUTE_TIMEOUT)+2)-1:0] age;
    reg [31:0] last_observations;
    reg short_captured, config_captured, weights_captured, features_captured, use_cnn;
    assign busy = state != OFF;
    assign covariance_pause = state >= SNAPSHOT;

    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            state <= OFF;
            age <= 0;
            last_observations <= 0;
            short_captured <= 0;
            config_captured <= 0;
            weights_captured <= 0;
            features_captured <= 0;
            use_cnn <= 1;
            flat_weights_start <= 0;
            covariance_clear <= 0;
            short_arm <= 0;
            config_capture <= 0;
            features_start <= 0;
            backend_request <= 0;
            window_committed <= 0;
            recovery_request <= 0;
            fault <= 0;
        end

        else
        begin
            covariance_clear <= 0;
            short_arm <= 0;
            config_capture <= 0;
            features_start <= 0;
            flat_weights_start <= 0;
            backend_request <= 0;
            window_committed <= 0;
            recovery_request <= 0;
            if (state == OFF || state == FAULT)age <= 0;
            else age <= age + 1;
            if (state != OFF && state != FAULT && (!acquisition_valid || short_error || (features_error &&
                use_cnn &&
                state >= FEATURES && state <= RESULT) || (flat_weights_error && !use_cnn && (state == BYPASS ||
                state ==
                REQUEST || state == RESULT))))
            begin
                state <= FAULT;
                fault <= 1;
                recovery_request <= 1;
            end

            else if (state >= CLEAR && state <= SNAPSHOT && age >= ACQUIRE_TIMEOUT - 1)
            begin
                state <= FAULT;
                fault <= 2;
                recovery_request <= 1;
            end

            else if ((state >= CONFIG && state <= RESULT || state == BYPASS) && age >= COMPUTE_TIMEOUT - 1)
            begin
                state <= FAULT;
                fault <= 3;
                recovery_request <= 1;
            end

            else case
            (state)
            OFF:if (enable && acquisition_valid)
            begin
                state <= CLEAR;
                fault <= 0;
                short_captured <= 0;
                config_captured <= 0;
                weights_captured <= 0;
                features_captured <= 0;
            end
            CLEAR:if (!covariance_busy)
            begin
                covariance_clear <= 1;
                state <= WAIT_CLEAR;
            end
            WAIT_CLEAR:if (covariance_busy)
            begin
                state <= ACQUIRE;
                short_arm <= 1;
                last_observations <= 0;
            end
            ACQUIRE:
            begin
                if (short_complete)short_captured <= 1;
                last_observations <= observation_count;
                // Observation counter advances only after the last selected bin's update.
                // Wait for that boundary AFTER short-window completion to avoid a partial covariance.
                if (short_captured && observation_count >= 20 && observation_count != last_observations &&
                    !covariance_busy)
                begin
                    state <= SNAPSHOT;
                    age <= 0;
                end
            end
            SNAPSHOT:if (!covariance_busy)
            begin
                state <= CONFIG;
                config_capture <= 1;
            end
            CONFIG:if (config_done)
            begin
                config_captured <= 1;
                use_cnn <= cnn_required;
                if (cnn_required)
                begin
                    state <= FEATURES;
                    features_start <= 1;
                end

                else
                begin
                    state <= BYPASS;
                    flat_weights_start <= 1;
                end
            end
            BYPASS:if (flat_weights_done)
            begin
                weights_captured <= 1;
                state <= REQUEST;
            end
            FEATURES:
            begin
                if (weights_done)weights_captured <= 1;
                if (features_done)features_captured <= 1;
                if ((features_captured || features_done) && (weights_captured || weights_done))state <= REQUEST;
            end
            REQUEST:if (backend_ready && config_captured && weights_captured)
            begin
                backend_request <= 1;
                state <= RESULT;
            end
            RESULT:if (backend_done)
            begin
                if (backend_fault == 0)
                begin
                    window_committed <= 1;
                    state <= OFF;
                end

                else
                begin
                    fault <= 4;
                    recovery_request <= 1;
                    state <= FAULT;
                end
            end
            // Sticky fault deliberately requires supervised reset, never endless restart.
            FAULT:state <= FAULT;
            default:
            begin
                state <= FAULT;
                fault <= 5;
                recovery_request <= 1;
            end
        endcase
    end
    end
endmodule
