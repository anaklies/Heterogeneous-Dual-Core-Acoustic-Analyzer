`timescale 1ns/1ps
// One complete CNN window -> 20-frame mean -> 85 long-FFT weights.
// 512/2048 FFT ratio: long bins 5+4*k map to short bins k+1.25.
// This is a single-window reducer, not the MATLAB stride-8 ensemble.

module cnn_mask_reduce
(
    input  wire clk,
    input  wire rst_n,
    input  wire mask_valid,
    output wire mask_ready,
    input  wire [12:0] mask_address,
    input  wire [15:0] mask_data,
    output wire weight_valid,
    input  wire weight_ready,
    output wire [6:0] weight_address,
    output wire [31:0] weight_float,
    output reg done,
    output reg error
);

    localparam COLLECT = 0, READ = 1, WAIT_READ = 2, EMIT = 3;
    reg [1:0] state;
    reg [10:0] expected;
    reg [6:0] bin;
    reg [4:0] frame;
    reg [20:0] accumulator;
    (* ram_style="block" *) reg [20:0] sum[0:127];
    reg [20:0] first_q, second_q;
    reg [6:0] index;
    wire accepted = mask_valid && mask_ready && mask_address == expected;
    wire write_sum = accepted && frame == 19;
    wire [6:0] address_a = write_sum?bin:index + 1;

    always @(posedge clk)if (write_sum || state == READ)
    begin
        if (write_sum)sum[address_a] <= accumulator + mask_data;
        first_q <= sum[address_a];
    end

    always @(posedge clk)if (state == READ)second_q <= sum[index + 2];
    wire [20:0] first = (index + 1 >= 4 && index + 1 <= 85)?first_q:21'd0;
    wire [20:0] second = (index + 2 >= 4 && index + 2 <= 85)?second_q:21'd0;
    wire [22:0] numerator = {2'b0, first} * 3 + {2'b0, second};
    // Exact for the complete reachable numerator range 0..5,242,800.
    // The reciprocal multiply maps to spare DSPs instead of a wide LUT divider.
    wire [54:0] quotient_product = numerator * 32'hcccccccd;
    wire [15:0] q16 = quotient_product[53:38];
    function automatic[31:0] q16_float(input [15:0] v);
    integer p;
    reg [7:0] e;
    reg [31:0] mantissa;
    begin
        p = 0;
        for (integer k = 0;k < 16;k = k + 1)if (v[k])p = k;
        e = 111 + p;
        mantissa = {16'b0, v} << (23 - p);
        q16_float = v == 0?0:{1'b0, e, mantissa[22:0]};
    end
    endfunction
    assign mask_ready = state == COLLECT && !error;
    assign weight_valid = state == EMIT && !error;
    assign weight_address = index;
    assign weight_float = q16_float(q16);

    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            state <= COLLECT;
            expected <= 0;
            bin <= 0;
            frame <= 0;
            index <= 0;
            accumulator <= 0;
            done <= 0;
            error <= 0;
        end

        else
        begin
            done <= 0;
            if (mask_valid && mask_ready)
            begin
                if (mask_address != expected)error <= 1;
                else
                begin
                    accumulator <= frame == 19?0:accumulator + mask_data;
                    expected <= expected + 1;
                    if (frame == 19)
                    begin
                        frame <= 0;
                        bin <= bin + 1;
                    end

                    else frame <= frame + 1;
                    if (expected == 1739)
                    begin
                        state <= READ;
                        index <= 0;
                    end
                end
            end
            if (state == READ)state <= WAIT_READ;
            if (state == WAIT_READ)state <= EMIT;
            if (weight_valid && weight_ready)
            begin
                if (index == 84)
                begin
                    state <= COLLECT;
                    expected <= 0;
                    bin <= 0;
                    frame <= 0;
                    accumulator <= 0;
                    done <= 1;
                end

                else
                begin
                    index <= index + 1;
                    state <= READ;
                end
            end
        end
    end
endmodule
