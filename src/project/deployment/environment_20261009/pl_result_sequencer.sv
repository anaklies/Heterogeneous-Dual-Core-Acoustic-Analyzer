`timescale 1ns/1ps
// Atomic localization -> tracking -> 52-word publication, all in PL.
// Compute IPs connect via synchronous ap_memory ports. No PS algorithm work.

module pl_result_sequencer #(
    parameter MUSIC_TIMEOUT = 500000000,
    TRACK_TIMEOUT = 5000000,
    OUTPUT_TIMEOUT = 5000000
)
(
    input  wire clk,
    input  wire rst_n,
    input  wire request,
    input  wire abort_window,
    input  wire [31:0] dt_float,
    output wire ready,
    output wire busy,
    output reg done,
    output reg [3:0] fault,
    output reg [31:0] music_cycles,
    output reg [31:0] track_cycles,
    output reg music_start,
    output reg track_start,
    output wire cores_reset,
    output reg track_reset,
    input  wire music_done,
    input  wire track_done,
    input  wire music_we0,
    input  wire music_we1,
    input  wire [5:0] music_address0,
    input  wire [5:0] music_address1,
    input  wire [31:0] music_data0,
    input  wire [31:0] music_data1,
    input  wire track_read0,
    input  wire track_read1,
    input  wire [5:0] track_read_address0,
    input  wire [5:0] track_read_address1,
    output reg [31:0] track_q0,
    output reg [31:0] track_q1,
    output reg [31:0] track_dt,
    input  wire track_we0,
    input  wire track_we1,
    input  wire [5:0] track_address0,
    input  wire [5:0] track_address1,
    input  wire [31:0] track_data0,
    input  wire [31:0] track_data1,
    output wire result_valid,
    input  wire result_ready,
    output wire [5:0] result_address,
    output wire [31:0] result_data
);

    localparam IDLE = 0, MUSIC = 1, TRACK = 2, CHECK = 3, PUBLISH = 4, RECOVER = 5, READ_RESULT = 6,
        WAIT_RESULT = 7;
    reg [($clog2(OUTPUT_TIMEOUT+2)>0?$clog2(OUTPUT_TIMEOUT+2):1)-1:0] output_cycles;
    reg [2:0] state;
    reg first;
    reg [2:0] reset_count;
    reg [5:0] cursor;
    reg [51:0] music_seen, track_seen;
    (* ram_style="block" *) reg [31:0] detections[0:63], results[0:63];
    reg [31:0] result_q, result_count;
    wire [51:0] music_added = (music_we0 && music_address0 < 52?(52'b1 << music_address0):52'b0) |
        (music_we1 && music_address1 < 52?(52'b1 << music_address1):52'b0);
    wire [51:0] track_added = (track_we0 && track_address0 < 52?(52'b1 << track_address0):52'b0) |
        (track_we1 && track_address1 < 52?(52'b1 << track_address1):52'b0);
    assign ready = state == IDLE;
    assign busy = state != IDLE;
    assign cores_reset = !rst_n || state == RECOVER;
    assign result_valid = state == PUBLISH;
    assign result_address = cursor;
    assign result_data = result_q;
    wire dw0 = state == MUSIC && music_we0 && music_address0 < 52;
    wire dw1 = state == MUSIC && music_we1 && music_address1 < 52 && !(music_we0 && music_address0 ==
        music_address1);
    wire [5:0] da0 = dw0?music_address0:track_read_address0;
    wire [5:0] da1 = dw1?music_address1:track_read_address1;
    wire rw0 = state == TRACK && track_we0 && track_address0 < 52;
    wire rw1 = state == TRACK && track_we1 && track_address1 < 52 && !(track_we0 && track_address0 ==
        track_address1);
    wire [5:0] ra0 = rw0?track_address0:cursor;

    always @(posedge clk)if (dw0 || track_read0)
    begin
        if (dw0)detections[da0] <= music_data0;
        track_q0 <= detections[da0];
    end

    always @(posedge clk)if (dw1 || track_read1)
    begin
        if (dw1)detections[da1] <= music_data1;
        track_q1 <= detections[da1];
    end

    always @(posedge clk)if (rw0 || state == READ_RESULT)
    begin
        if (rw0)results[ra0] <= track_data0;
        result_q <= results[ra0];
    end

    always @(posedge clk)if (rw1)results[track_address1] <= track_data1;

    always @(posedge clk)
    begin
        if (state == TRACK && track_we0 && track_address0 == 0)result_count <= track_data0;
        if (state == TRACK && track_we1 && track_address1 == 0)result_count <= track_data1;
    end

    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            output_cycles <= 0;
            state <= IDLE;
            first <= 1;
            reset_count <= 0;
            cursor <= 0;
            done <= 0;
            fault <= 0;
            music_start <= 0;
            track_start <= 0;
            track_reset <= 1;
            music_seen <= 0;
            track_seen <= 0;
            music_cycles <= 0;
            track_cycles <= 0;
            track_dt <= 32'h3e800000;
        end

        else
        begin
            done <= 0;
            music_start <= 0;
            track_start <= 0;
            if (state == READ_RESULT || state == WAIT_RESULT || state == PUBLISH)output_cycles <= output_cycles + 1;
            else output_cycles <= 0;
            if (abort_window && state != IDLE && state != RECOVER)
            begin
                fault <= 10;
                state <= RECOVER;
                reset_count <= 0;
            end

            else if ((state == READ_RESULT || state == WAIT_RESULT || state == PUBLISH) && output_cycles >=
                OUTPUT_TIMEOUT - 1)
            begin
                fault <= 9;
                state <= RECOVER;
                reset_count <= 0;
            end

            else case
            (state)
            IDLE:if (request)
            begin
                state <= MUSIC;
                music_start <= 1;
                music_seen <= 0;
                track_seen <= 0;
                music_cycles <= 0;
                track_cycles <= 0;
                track_dt <= dt_float;
                fault <= 0;
            end
            MUSIC:
            begin
                music_cycles <= music_cycles + 1;
                music_seen <= music_seen | music_added;
                if ((music_we0 && music_address0 >= 52) || (music_we1 && music_address1 >= 52) || (music_we0 &&
                    music_we1 &&
                    music_address0 == music_address1 && music_data0 != music_data1))
                begin
                    fault <= 1;
                    state <= RECOVER;
                    reset_count <= 0;
                end

                else if (music_done)
                begin
                    if ( & (music_seen | music_added))
                    begin
                        track_start <= 1;
                        track_reset <= first;
                        first <= 0;
                        state <= TRACK;
                    end

                    else
                    begin
                        fault <= 2;
                        state <= RECOVER;
                        reset_count <= 0;
                    end
                end

                else if (music_cycles >= MUSIC_TIMEOUT - 1)
                begin
                    fault <= 3;
                    state <= RECOVER;
                    reset_count <= 0;
                end
            end
            TRACK:
            begin
                track_cycles <= track_cycles + 1;
                track_seen <= track_seen | track_added;
                if ((track_we0 && track_address0 >= 52) || (track_we1 && track_address1 >= 52) || (track_we0 &&
                    track_we1 &&
                    track_address0 == track_address1 && track_data0 != track_data1))
                begin
                    fault <= 4;
                    state <= RECOVER;
                    reset_count <= 0;
                end

                else if (track_done)
                begin
                    if ( & (track_seen | track_added))state <= CHECK;
                    else
                    begin
                        fault <= 5;
                        state <= RECOVER;
                        reset_count <= 0;
                    end
                end

                else if (track_cycles >= TRACK_TIMEOUT - 1)
                begin
                    fault <= 6;
                    state <= RECOVER;
                    reset_count <= 0;
                end
            end
            CHECK:
            begin
                // Header count must be a signed nonnegative integer in 0..3.
                if (result_count > 3)
                begin
                    fault <= 7;
                    state <= RECOVER;
                    reset_count <= 0;
                end

                else
                begin
                    cursor <= 0;
                    state <= READ_RESULT;
                end
            end
            READ_RESULT:state <= WAIT_RESULT;
            WAIT_RESULT:state <= PUBLISH;
            PUBLISH:if (result_ready)
            begin
                if (cursor == 51)
                begin
                    done <= 1;
                    state <= IDLE;
                end

                else
                begin
                    cursor <= cursor + 1;
                    state <= READ_RESULT;
                end
            end
            RECOVER:
            begin
                first <= 1;
                if (reset_count == 3)
                begin
                    done <= 1;
                    state <= IDLE;
                end

                else reset_count <= reset_count + 1;
            end
            default:
            begin
                fault <= 8;
                state <= RECOVER;
                reset_count <= 0;
            end
        endcase
    end
    end
endmodule
