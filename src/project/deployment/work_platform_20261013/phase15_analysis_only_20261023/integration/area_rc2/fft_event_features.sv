`timescale 1ns / 1ps

// One shared band accumulator. Input and output contracts match RC1.
module fft_event_features #(
    parameter TIMEOUT = 500000
)(
    input wire clk, rst_n, frame_valid,
    input wire [31:0] frame_base,
    input wire [63:0] frame_last,
    input wire [7:0] band_mask,
    input wire [255:0] band_edges,
    output wire done_valid,
    input wire done_ready,
    output reg feature_valid,
    output reg [191:0] channel_power,
    output reg [255:0] band_power,
    output reg [63:0] timestamp,
    output reg fault,
    output reg [31:0] araddr,
    output wire arvalid,
    input wire arready,
    input wire [31:0] rdata,
    input wire [1:0] rresp,
    input wire rvalid, rlast,
    output wire rready
);
    localparam IDLE=0, INIT=1, ADDRESS=2, RESPONSE=3,
               ACCUMULATE=4, ADVANCE=5, FOLD=6, DONE=7;
    // At most 6*1025 unsigned 32-bit addends: sum < 2**45.
    // This includes invalid/saturated Q30 inputs; validity handling is unchanged.
    localparam ACC_W = 45;
    reg [2:0] state, channel, band_index;
    reg [10:0] bin;
    reg [31:0] base, age, pending_power;
    reg [7:0] mask;
    reg [255:0] edges;
    reg [ACC_W-1:0] total;
    (* ram_style = "distributed" *) reg [ACC_W-1:0] bands [0:7];
    reg [32:0] converted;
    reg [ACC_W-1:0] final_power;
    wire [ACC_W-1:0] selected_band = bands[band_index];
    wire band_hit = mask[band_index] &&
                    bin >= edges[32*band_index +: 16] &&
                    bin < edges[32*band_index+16 +: 16];

    function automatic [32:0] q30(input [31:0] fp);
        reg [31:0] v;
        reg [7:0] e;
        begin
            e=fp[30:23]; v={1'b1,fp[22:0]};
            if(fp[31] || e==255) q30={1'b1,32'b0};
            else if(e<97) q30=0;
            else if(e>128) q30={1'b1,32'hffffffff};
            else begin
                if(e>=120) v=v<<(e[3:0]-4'd8);
                else v=v>>(5'd24-e[4:0]);
                q30={1'b0,v};
            end
        end
    endfunction

    assign arvalid = state==ADDRESS;
    assign rready = state==RESPONSE;
    assign done_valid = state==DONE;

    always @(posedge clk) begin
        if(!rst_n) begin
            state<=IDLE; channel<=0; band_index<=0; bin<=0;
            base<=0; age<=0; pending_power<=0; mask<=0; edges<=0;
            total<=0; araddr<=0; feature_valid<=0; channel_power<=0;
            band_power<=0; timestamp<=0; fault<=0;
            // Per-frame initialization precedes every read of band storage.
        end else begin
            if(state==ADDRESS || state==RESPONSE) begin
                if(age<TIMEOUT) age<=age+1;
                else begin fault<=1; feature_valid<=0; end
            end
            case(state)
                IDLE: if(frame_valid) begin
                    state<=INIT; band_index<=0; base<=frame_base;
                    araddr<=frame_base+4098*4; age<=0; channel<=0; bin<=0;
                    mask<=band_mask; edges<=band_edges; total<=0;
                    timestamp<=frame_last; feature_valid<=1;
                end
                INIT: begin
                    bands[band_index]<=0;
                    if(mask[band_index] &&
                       (edges[32*band_index +: 16]>=edges[32*band_index+16 +: 16] ||
                        edges[32*band_index+16 +: 16]>1025)) begin
                        feature_valid<=0; fault<=1;
                    end
                    if(band_index==7) begin state<=ADDRESS; band_index<=0; end
                    else band_index<=band_index+1;
                end
                ADDRESS: if(arready) begin state<=RESPONSE; age<=0; end
                RESPONSE: if(rvalid) begin
                    age<=0;
                    if(rresp!=0 || !rlast) begin
                        fault<=1; feature_valid<=0; state<=DONE;
                    end else begin
                        converted=q30(rdata);
                        if(converted[32]) begin fault<=1; feature_valid<=0; end
                        pending_power<=converted[31:0];
                        final_power=total+converted[31:0];
                        if(bin==1024) begin
                            channel_power[channel*32 +: 32] <=
                                final_power>45'hffffffff ? 32'hffffffff : final_power[31:0];
                            if(final_power>45'hffffffff) begin feature_valid<=0; fault<=1; end
                            total<=0;
                        end else total<=final_power;
                        band_index<=0; state<=ACCUMULATE;
                    end
                end
                ACCUMULATE: begin
                    if(band_hit) bands[band_index]<=selected_band+pending_power;
                    if(band_index==7) state<=ADVANCE;
                    else band_index<=band_index+1;
                end
                ADVANCE: begin
                    if(bin==1024) begin
                        bin<=0;
                        if(channel==5) begin state<=FOLD; band_index<=0; end
                        else begin
                            channel<=channel+1;
                            araddr<=base+(channel+1)*32768+4098*4;
                            state<=ADDRESS;
                        end
                    end else begin bin<=bin+1; araddr<=araddr+12; state<=ADDRESS; end
                end
                FOLD: begin
                    if(selected_band>45'h5fffffffa) begin
                        band_power[32*band_index +: 32]<=32'hffffffff;
                        feature_valid<=0; fault<=1;
                    end else band_power[32*band_index +: 32]<=(selected_band[34:0]+35'd3)/35'd6;
                    if(band_index==7) state<=DONE;
                    else band_index<=band_index+1;
                end
                DONE: if(done_ready) state<=IDLE;
            endcase
        end
    end
endmodule
