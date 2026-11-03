`timescale 1ns / 1ps
// One frontend command and its two DDR STFT banks. This is not the NN/DOA
// scheduler and does not claim ownership of the capture or feature slot pool.
module frontend_lease #(
    parameter integer COLD_TIMEOUT = 37500000,
    parameter integer WARM_TIMEOUT = 7200000,
    parameter [31:0] INITIAL_TOKEN = 1
)(
    input wire clk, rst_n,
    input wire [31:0] arena_base,
    input wire [31:0] active_config, active_session,
    input wire request_valid,
    output wire request_ready,
    input wire [1:0] request_slot,
    input wire [31:0] request_frame, request_config, request_session,
    input wire [63:0] request_sample,
    output wire command_valid,
    input wire command_ready,
    output reg [31:0] command_token,
    output reg [31:0] command_frame, command_config, command_session,
    output reg [1:0] command_slot,
    output reg [63:0] command_sample,
    output reg command_reuse,
    output reg [31:0] pcm_address, feature_address, scratch_address,
    output reg [31:0] qlogs_address, previous_address, current_address,
    output reg [31:0] previous_meta_address, current_meta_address,
    input wire done_valid,
    output wire done_ready,
    input wire [31:0] done_token,
    // Transport must combine HLS metadata error, RRESP/BRESP and ap_done.
    input wire [31:0] done_error,
    input wire memory_fault,
    output wire completion_valid,
    input wire completion_ready,
    output reg [31:0] completion_error,
    output wire cache_available,
    output reg fault_latched,
    output reg [31:0] timeout_count, stale_done_count, accepted_count,
    // Only assert after all relevant AXI masters are idle or safely reset.
    // A local watchdog must never withdraw an active AXI transaction.
    input wire recover_request, bus_quiescent_ack
);
    localparam [1:0] IDLE=0, ISSUE=1, WAIT_DONE=2, RESULT=3;
    localparam [31:0] BAD_ARGS=1, STALE_CONFIG=2, TIMEOUT=4,
        MEMORY_ERROR=8, ENGINE_ERROR=16, RECOVERED_ABORT=32;
    reg [1:0] state;
    reg cache_valid, cache_bank, pending_bank;
    reg [31:0] cache_config, cache_session, token_counter, age;
    reg [31:0] cache_arena, command_arena;
    reg [63:0] cache_sample;
    reg discard_result;
    wire context_matches = command_config==active_config && command_session==active_session;
    wire matching_done = state==WAIT_DONE && done_valid && done_token==command_token;
    wire [31:0] timeout_limit=command_reuse ? WARM_TIMEOUT : COLD_TIMEOUT;
    wire expired = (state==ISSUE || state==WAIT_DONE) && age>=timeout_limit-1;
    wire arena_ok=arena_base[11:0]==0 && arena_base<=32'h3f800000;
    wire request_context=request_config==active_config && request_session==active_session;
    assign request_ready=state==IDLE && !fault_latched && !memory_fault;
    assign command_valid=state==ISSUE;
    assign completion_valid=state==RESULT;
    assign done_ready=1'b1;
    assign cache_available=cache_valid;

    function automatic [31:0] increment_sat(input [31:0] x);
        increment_sat=(&x)?x:x+1;
    endfunction
    initial begin
        if(COLD_TIMEOUT<1 || WARM_TIMEOUT<1)
            $fatal(1,"Frontend timeout must be positive");
    end

    always @(posedge clk) begin
        if(!rst_n) begin
            state<=IDLE;cache_valid<=0;cache_bank<=0;pending_bank<=0;
            cache_config<=0;cache_session<=0;cache_sample<=0;
            cache_arena<=0;command_arena<=0;
            token_counter<=INITIAL_TOKEN;age<=0;discard_result<=0;
            command_token<=0;command_frame<=0;command_config<=0;
            command_session<=0;command_slot<=0;command_sample<=0;command_reuse<=0;
            pcm_address<=0;feature_address<=0;scratch_address<=0;qlogs_address<=0;
            previous_address<=0;current_address<=0;
            previous_meta_address<=0;current_meta_address<=0;
            completion_error<=0;fault_latched<=0;timeout_count<=0;
            stale_done_count<=0;accepted_count<=0;
        end
        else begin
            if(memory_fault)begin fault_latched<=1;cache_valid<=0;end
            if(done_valid && !matching_done)
                stale_done_count<=increment_sat(stale_done_count);
            if(state==IDLE && request_valid && request_ready) begin
                command_token<=token_counter;token_counter<=token_counter+1;
                accepted_count<=increment_sat(accepted_count);
                command_frame<=request_frame;command_config<=request_config;
                command_session<=request_session;command_sample<=request_sample;
                command_slot<=request_slot;age<=0;discard_result<=0;
                command_arena<=arena_base;
                completion_error<=0;
                pending_bank<=cache_valid ? ~cache_bank : 1'b0;
                command_reuse<=cache_valid && arena_base==cache_arena && request_context &&
                    request_config==cache_config && request_session==cache_session &&
                    cache_sample<=64'hffff_ffff_ffff_edff &&
                    cache_sample+64'd4608==request_sample;
                // Fixed non-overlapping layout within one8MiB reserved arena.
                // Three PCM/feature slots are leased by the upstream pool.
                pcm_address<=arena_base+request_slot*32'h00050000;
                feature_address<=arena_base+32'h00100000+request_slot*32'h00050000;
                scratch_address<=arena_base+32'h00329000;
                qlogs_address<=arena_base+32'h00334000;
                previous_address<=arena_base+32'h00300000+(cache_bank?32'h00014000:0);
                previous_meta_address<=arena_base+32'h00328000+(cache_bank?64:0);
                current_address<=arena_base+32'h00300000+
                    ((cache_valid ? ~cache_bank : 1'b0)?32'h00014000:0);
                current_meta_address<=arena_base+32'h00328000+
                    ((cache_valid ? ~cache_bank : 1'b0)?64:0);
                // On cold start the unused previous pointer must still name a
                // distinct valid allocation. allow_reuse remains false.
                if(!cache_valid) begin
                    previous_address<=arena_base+32'h00314000;
                    previous_meta_address<=arena_base+32'h00328040;
                end
                if(!arena_ok || request_slot>2 ||
                    request_sample>64'hffff_ffff_ffff_d1ff) begin
                    completion_error<=BAD_ARGS;state<=RESULT;
                end
                else if(!request_context) begin
                    completion_error<=STALE_CONFIG;state<=RESULT;
                end
                else state<=ISSUE;
            end
            if(state==ISSUE && command_ready)state<=WAIT_DONE;
            if(state==ISSUE || state==WAIT_DONE)age<=increment_sat(age);

            if((state==ISSUE || state==WAIT_DONE) && memory_fault) begin
                discard_result<=1;fault_latched<=1;cache_valid<=0;
                completion_error<=completion_error|MEMORY_ERROR;
            end
            if(expired && !matching_done && !discard_result) begin
                discard_result<=1;fault_latched<=1;cache_valid<=0;
                timeout_count<=increment_sat(timeout_count);
                completion_error<=completion_error|TIMEOUT|
                    (memory_fault?MEMORY_ERROR:0);
            end
            if(matching_done) begin
                state<=RESULT;
                if(discard_result || memory_fault || done_error!=0 || !context_matches) begin
                    cache_valid<=0;
                    completion_error<=completion_error|
                        (memory_fault?MEMORY_ERROR:0)|
                        (done_error!=0?ENGINE_ERROR:0)|(!context_matches?STALE_CONFIG:0);
                end
                else begin
                    cache_valid<=1;cache_bank<=pending_bank;
                    cache_config<=command_config;cache_session<=command_session;
                    cache_sample<=command_sample;
                    cache_arena<=command_arena;
                end
            end
            if(state==RESULT && completion_ready)state<=IDLE;
            if(recover_request && bus_quiescent_ack) begin
                cache_valid<=0;fault_latched<=0;discard_result<=0;age<=0;
                if(state==ISSUE || state==WAIT_DONE) begin
                    completion_error<=completion_error|RECOVERED_ABORT;
                    state<=RESULT;
                end
            end
        end
    end
endmodule
