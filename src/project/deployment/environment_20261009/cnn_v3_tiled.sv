`timescale 1ns/1ps
// Exact frequency tiling of the 3x3/3x3/3x3/1x1 network, with 3-row halo.
// First/last tiles retain GLOBAL padding; internal halos are never emitted.
// Features are computed elsewhere in PL; this wrapper does not use the PS.

module cnn_v3_tiled #(
    parameter COEFF_DIR = "pl/coeff",
    parameter TILE_FREQ = 32,
    parameter TOTAL_FREQ = 90,
    parameter OUTPUT_FREQ = 87
)
(
    input  wire clk,
    input  wire rst_n,
    input  wire feature_valid,
    output wire feature_ready,
    input  wire [15:0] feature_index,
    input  wire signed [23:0] feature_data,
    input  wire start,
    output wire busy,
    output reg done,
    output reg load_error,
    output wire mask_valid,
    input  wire mask_ready,
    output wire [12:0] mask_address,
    output wire [15:0] mask_data
);

    localparam IDLE = 0, READ = 1, WAIT = 2, SEND = 3, LAUNCH = 4, RUN = 5;
    reg [2:0] state;
    reg [8:0] tile_start, tile_length;
    reg [15:0] local_index;
    reg [$clog2(TOTAL_FREQ * 160 + 2)-1:0] loaded;
    wire [15:0] read_index = tile_start * 160 + local_index;
    wire signed [15:0] read_feature;
    wire signed [15:0] incoming_feature = $signed(feature_data) >>> 6;
    wire [12:0] local_address = local_index[15:3];
    wire core_ready, core_busy, core_done, core_error, core_valid;
    wire [12:0] core_address;
    wire [15:0] core_data;
    // Compare addresses directly: a combinational divide-by-20 on the ready
    // path prevents a 125 MHz implementation despite correct simulation.
    // Three halo rows on each internal boundary preserve the full network.
    wire [12:0] halo_end = (tile_length - 3) * 20;
    wire eligible = (tile_start == 0 || core_address >= 60) &&
        (tile_start + tile_length == TOTAL_FREQ || core_address < halo_end) &&
        (tile_start * 20 + core_address < OUTPUT_FREQ * 20);
    assign feature_ready = state == IDLE;
    assign busy = state != IDLE;
    assign mask_valid = core_valid && eligible;
    assign mask_data = core_data;
    assign mask_address = tile_start * 20 + core_address;
    cnn_activation_ram #(.WIDTH(16), .DEPTH((TOTAL_FREQ * 160)), .ADDR_BITS(16)) features(
    .clk(clk), .we(feature_valid && feature_ready && feature_index < (TOTAL_FREQ * 160)),
        .waddr(feature_index),
        .wdata(incoming_feature), .re(state == READ), .raddr(read_index), .rdata(read_feature));
    cnn_v3_fixed #(.FREQ(TILE_FREQ), .TIME(20), .COEFF_DIR(COEFF_DIR)) engine(
    .clk(clk), .rst_n(rst_n), .feature_valid(state == SEND), .feature_ready(core_ready),
        .feature_address(local_address), .feature_channel(local_index[2:0]),
        .feature_data($signed(read_feature) * 24'sd64),
        .feature_frequency_count(tile_length), .start(state == LAUNCH), .busy(core_busy), .done(core_done),
        .load_error(core_error),
        .mask_valid(core_valid), .mask_ready(eligible?mask_ready:1'b1), .mask_address(core_address),
        .mask_data(core_data));

    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            state <= IDLE;
            tile_start <= 0;
            tile_length <= TILE_FREQ;
            local_index <= 0;
            loaded <= 0;
            done <= 0;
            load_error <= 0;
        end

        else
        begin
            done <= 0;
            if (feature_valid && feature_ready)
            begin
                if (feature_index < (TOTAL_FREQ * 160) && loaded < TOTAL_FREQ * 160) loaded <= loaded + 1;
                else load_error <= 1;
            end
            if (core_error) load_error <= 1;
            case
                (state)
                IDLE: if (start)
                begin
                    if (load_error || loaded != (TOTAL_FREQ * 160) || feature_valid) load_error <= 1;
                    else
                    begin
                        loaded <= 0;
                        tile_start <= 0;
                        tile_length <= TILE_FREQ;
                        local_index <= 0;
                        state <= READ;
                        load_error <= 0;
                    end
                end
                READ: state <= WAIT;
                WAIT: state <= SEND;
                SEND: if (core_ready)
                begin
                    if (local_index == tile_length * 160 - 1) state <= LAUNCH;
                    else
                    begin
                        local_index <= local_index + 1;
                        state <= READ;
                    end
                end
                LAUNCH: state <= RUN;
                RUN: if (core_done)
                begin
                    if (tile_start + tile_length == TOTAL_FREQ)
                    begin
                        done <= 1;
                        state <= IDLE;
                    end

                    else
                    begin
                        tile_start <= tile_start + (TILE_FREQ - 6);
                        if (tile_start + (TILE_FREQ - 6) + TILE_FREQ > TOTAL_FREQ) tile_length <=
                            TOTAL_FREQ - tile_start - (TILE_FREQ - 6);
                        else tile_length <= TILE_FREQ;
                        local_index <= 0;
                        state <= READ;
                    end
                end
            endcase
        end
    end
endmodule
