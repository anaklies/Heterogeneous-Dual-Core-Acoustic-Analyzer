`timescale 1ns / 1ps
// One bounded batch dispatcher. Algorithm cores supply progress and matching
// completion metadata. This module never generates an algorithm result.
module profile_scheduler #(
    parameter [63:0] MANDATORY_MASK = 64'h0000_0000_0000_03ff,
    parameter [63:0] PERIODIC_MASK = 64'h0000_0000_00ff_fc00,
    parameter [63:0] OPTIONAL_MASK = 64'h0000_1fff_ff00_0000,
    parameter integer P1_PERIOD_FRAMES = 2,
    parameter integer P2_PERIOD_FRAMES = 11,
    parameter integer JOB_TIMEOUT_CYCLES = 4718592,
    parameter integer STALL_TIMEOUT_CYCLES = 491620,
    parameter integer RESET_CYCLES = 16,
    parameter integer MAX_CONSECUTIVE_TIMEOUTS = 3
)(
    input wire clk, rst_n,
    input wire frame_start,
    input wire [31:0] frame_id,
    // This mask is supplied by the integrated design, not by a PS request.
    // Unimplemented functions must remain zero, including missing P0 cores.
    input wire [63:0] implemented_mask,
    input wire cfg_valid,
    output wire cfg_ready,
    input wire [31:0] cfg_request_id,
    input wire [63:0] ps_periodic_mask, pc_periodic_mask,
    input wire [63:0] ps_optional_mask, pc_optional_mask,
    input wire pause_unrelated_periodic,
    output reg cfg_applied, cfg_rejected,
    output reg [31:0] cfg_response_request_id,
    output reg [63:0] cfg_unsupported_mask,
    output reg [31:0] active_config_version,
    output wire [63:0] capabilities,
    output wire mandatory_ready,
    output wire [63:0] mandatory_missing_mask,
    output wire [63:0] active_periodic_mask, active_optional_mask,
    input wire engine_busy, engine_done, engine_progress,
    input wire [31:0] engine_transaction_id, engine_config_version,
    output reg job_start, job_cancel,
    output wire engine_reset,
    output reg [63:0] job_mask,
    output reg [31:0] job_frame_id, job_transaction_id, job_config_version,
    output reg result_publish, stale_done,
    output reg [31:0] completed_transaction_id, completed_config_version,
    input wire clear_fault,
    input wire clear_counters,
    output reg fault_latched,
    output reg [3:0] last_error_code,
    output reg [7:0] consecutive_timeouts,
    output reg [31:0] missed_frames, canceled_jobs, timeout_count, stale_done_count,
    output wire running
);
    localparam integer P1_W = (P1_PERIOD_FRAMES <= 1) ? 1 : $clog2(P1_PERIOD_FRAMES);
    localparam integer P2_W = (P2_PERIOD_FRAMES <= 1) ? 1 : $clog2(P2_PERIOD_FRAMES);
    localparam integer RESET_W = (RESET_CYCLES < 1) ? 1 : $clog2(RESET_CYCLES + 1);
    localparam [3:0] ERR_REQUEST = 1, ERR_P0_MISSING = 2,
                     ERR_JOB_TIMEOUT = 3, ERR_NO_PROGRESS = 4, ERR_ORPHAN_BUSY = 5;
    reg pending;
    reg [31:0] pending_request;
    reg [63:0] pending_periodic, pending_optional;
    reg pending_pause;
    reg [63:0] current_periodic, current_optional;
    reg current_pause;
    reg [P1_W-1:0] p1_phase;
    reg [P2_W-1:0] p2_phase;
    reg in_flight;
    reg [31:0] total_age, stall_age, orphan_age;
    reg [RESET_W-1:0] reset_remaining;
    reg [31:0] transaction_counter;
    wire apply_pending = frame_start && pending;
    wire [63:0] incoming_periodic = ps_periodic_mask | pc_periodic_mask;
    wire [63:0] incoming_optional = ps_optional_mask | pc_optional_mask;
    wire [63:0] illegal_request =
        ((incoming_periodic | incoming_optional) & ~implemented_mask) |
        (incoming_periodic & ~PERIODIC_MASK) | (incoming_optional & ~OPTIONAL_MASK);
    wire [63:0] frame_periodic = apply_pending ? pending_periodic : current_periodic;
    wire [63:0] frame_optional = apply_pending ? pending_optional : current_optional;
    wire frame_pause = apply_pending ? pending_pause : current_pause;
    wire [31:0] frame_version = active_config_version + (apply_pending ? 1 : 0);
    wire matching_done = in_flight && engine_done &&
        engine_transaction_id == job_transaction_id && engine_config_version == job_config_version;
    wire matching_progress = in_flight && engine_progress &&
        engine_transaction_id == job_transaction_id && engine_config_version == job_config_version;
    wire total_timeout = in_flight && total_age >= JOB_TIMEOUT_CYCLES-1;
    wire stall_timeout = in_flight && !matching_progress && stall_age >= STALL_TIMEOUT_CYCLES-1;
    wire orphan_timeout = !in_flight && engine_busy && !engine_reset && orphan_age >= STALL_TIMEOUT_CYCLES-1;
    wire timeout_event = !matching_done && !apply_pending && !fault_latched &&
                         (total_timeout || stall_timeout || orphan_timeout);
    wire p1_due = p1_phase == 0;
    wire p2_due = p2_phase == 0 || apply_pending;
    wire [63:0] requested_frame_mask = MANDATORY_MASK |
        ((p1_due && !(frame_pause && |frame_optional)) ? frame_periodic : 64'd0) |
        (p2_due ? frame_optional : 64'd0);
    assign cfg_ready = !pending;
    assign capabilities = implemented_mask;
    assign mandatory_missing_mask = MANDATORY_MASK & ~implemented_mask;
    assign mandatory_ready = mandatory_missing_mask == 0;
    assign active_periodic_mask = current_periodic;
    assign active_optional_mask = current_optional;
    assign engine_reset = reset_remaining != 0;
    assign running = in_flight;

    function automatic [31:0] increment_saturated(input [31:0] value);
        increment_saturated = (&value) ? value : value + 1;
    endfunction

    initial begin
        if (P1_PERIOD_FRAMES < 1 || P2_PERIOD_FRAMES < 1 || JOB_TIMEOUT_CYCLES < 1 ||
            STALL_TIMEOUT_CYCLES < 1 || RESET_CYCLES < 1 ||
            MAX_CONSECUTIVE_TIMEOUTS < 1 || MAX_CONSECUTIVE_TIMEOUTS > 255)
            $fatal(1, "Invalid scheduler cycle/frame limits");
        if ((MANDATORY_MASK & PERIODIC_MASK) != 0 || (MANDATORY_MASK & OPTIONAL_MASK) != 0 ||
            (PERIODIC_MASK & OPTIONAL_MASK) != 0)
            $fatal(1, "Priority masks must be disjoint");
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            pending <= 0; pending_request <= 0; pending_periodic <= 0; pending_optional <= 0; pending_pause <= 0;
            current_periodic <= 0; current_optional <= 0; current_pause <= 0;
            cfg_applied <= 0; cfg_rejected <= 0; cfg_response_request_id <= 0; cfg_unsupported_mask <= 0;
            active_config_version <= 0; p1_phase <= 0; p2_phase <= 0;
            in_flight <= 0; total_age <= 0; stall_age <= 0; orphan_age <= 0;
            reset_remaining <= RESET_CYCLES; transaction_counter <= 0;
            job_start <= 0; job_cancel <= 0; job_mask <= 0;
            job_frame_id <= 0; job_transaction_id <= 0; job_config_version <= 0;
            result_publish <= 0; stale_done <= 0; completed_transaction_id <= 0; completed_config_version <= 0;
            fault_latched <= 0; last_error_code <= 0; consecutive_timeouts <= 0;
            missed_frames <= 0; canceled_jobs <= 0; timeout_count <= 0; stale_done_count <= 0;
        end else begin
            job_start <= 0; job_cancel <= 0; result_publish <= 0; stale_done <= 0;
            cfg_applied <= 0; cfg_rejected <= 0;
            if (reset_remaining != 0) reset_remaining <= reset_remaining - 1;
            if (in_flight) begin
                total_age <= increment_saturated(total_age);
                stall_age <= matching_progress ? 0 : increment_saturated(stall_age);
            end else begin
                total_age <= 0; stall_age <= 0;
            end
            orphan_age <= (!in_flight && engine_busy && !engine_reset) ? increment_saturated(orphan_age) : 0;
            if (cfg_valid && cfg_ready) begin
                if (|illegal_request) begin
                    cfg_rejected <= 1; cfg_response_request_id <= cfg_request_id;
                    cfg_unsupported_mask <= illegal_request; last_error_code <= ERR_REQUEST;
                end else begin
                    pending <= 1; pending_request <= cfg_request_id;
                    pending_periodic <= incoming_periodic; pending_optional <= incoming_optional;
                    pending_pause <= pause_unrelated_periodic;
                end
            end
            if (apply_pending) begin
                pending <= 0; current_periodic <= pending_periodic; current_optional <= pending_optional;
                current_pause <= pending_pause; active_config_version <= frame_version;
                cfg_applied <= 1; cfg_response_request_id <= pending_request; cfg_unsupported_mask <= 0;
            end
            if (frame_start) begin
                p1_phase <= (p1_phase == P1_PERIOD_FRAMES-1) ? 0 : p1_phase + 1;
                if (apply_pending) p2_phase <= (P2_PERIOD_FRAMES == 1) ? 0 : 1;
                else p2_phase <= (p2_phase == P2_PERIOD_FRAMES-1) ? 0 : p2_phase + 1;
            end
            if (engine_done && !matching_done) begin
                stale_done <= 1; stale_done_count <= increment_saturated(stale_done_count);
            end
            if (matching_done) begin
                in_flight <= 0; total_age <= 0; stall_age <= 0;
                consecutive_timeouts <= 0;
                if (!apply_pending && !fault_latched && !clear_fault) begin
                    result_publish <= 1;
                    completed_transaction_id <= job_transaction_id;
                    completed_config_version <= job_config_version;
                end else begin
                    stale_done <= 1; stale_done_count <= increment_saturated(stale_done_count);
                end
            end
            if (clear_fault) begin
                fault_latched <= 0; last_error_code <= 0; consecutive_timeouts <= 0;
                total_age <= 0; stall_age <= 0; orphan_age <= 0;
                if (in_flight) begin
                    job_cancel <= 1; canceled_jobs <= increment_saturated(canceled_jobs);
                end
                in_flight <= 0; reset_remaining <= RESET_CYCLES;
            end else if (timeout_event) begin
                in_flight <= 0; job_cancel <= 1; reset_remaining <= RESET_CYCLES;
                total_age <= 0; stall_age <= 0; orphan_age <= 0;
                canceled_jobs <= increment_saturated(canceled_jobs);
                timeout_count <= increment_saturated(timeout_count);
                consecutive_timeouts <= consecutive_timeouts + 1;
                if (consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS-1) fault_latched <= 1;
                last_error_code <= orphan_timeout ? ERR_ORPHAN_BUSY :
                                   (total_timeout ? ERR_JOB_TIMEOUT : ERR_NO_PROGRESS);
            end else if (frame_start) begin
                if (!mandatory_ready) begin
                    missed_frames <= increment_saturated(missed_frames); last_error_code <= ERR_P0_MISSING;
                end else if (fault_latched || engine_reset) begin
                    missed_frames <= increment_saturated(missed_frames);
                end else if (in_flight && !matching_done) begin
                    missed_frames <= increment_saturated(missed_frames);
                    if (apply_pending) begin
                        in_flight <= 0; job_cancel <= 1; reset_remaining <= RESET_CYCLES;
                        canceled_jobs <= increment_saturated(canceled_jobs);
                    end
                end else if (engine_busy && !matching_done) begin
                    missed_frames <= increment_saturated(missed_frames);
                end else begin
                    job_start <= 1; in_flight <= 1;
                    job_mask <= requested_frame_mask & implemented_mask;
                    job_frame_id <= frame_id;
                    transaction_counter <= transaction_counter + 1;
                    job_transaction_id <= transaction_counter + 1;
                    job_config_version <= frame_version;
                    total_age <= 0; stall_age <= 0; orphan_age <= 0;
                end
            end
            // Clearing diagnostic counters does not rearm a latched fault.
            if (clear_counters) begin
                missed_frames <= 0; canceled_jobs <= 0; timeout_count <= 0; stale_done_count <= 0;
            end
        end
    end
endmodule
