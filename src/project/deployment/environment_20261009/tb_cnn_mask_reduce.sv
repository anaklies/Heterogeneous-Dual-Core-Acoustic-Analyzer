`timescale 1ns/1ps

module tb_cnn_mask_reduce;

    reg clk = 0;

    always #10 clk = ~clk;
    reg rst_n = 0, mv = 0, wr = 0;
    reg [12:0] ma = 0;
    reg [15:0] md = 0;
    wire mr, wv, done, error;
    wire [6:0] wa;
    wire [31:0] wf;
    cnn_mask_reduce dut(.clk(clk), .rst_n(rst_n), .mask_valid(mv), .mask_ready(mr), .mask_address(ma),
        .mask_data(md), .weight_valid(wv), .weight_ready(wr), .weight_address(wa), .weight_float(wf),
        .done(done),
        .error(error));
    integer n, j, cycles;
    integer a, b, value;
    reg [31:0] expected, held;
    reg [6:0] held_address;
    function automatic integer bin_value(input integer f);
    begin
        bin_value = f >= 4 && f <= 85?f * 500 + 190:0;
    end
    endfunction
    initial
    begin
        repeat(3)@(negedge clk);
        rst_n = 1;
        for (n = 0;n < 1740;n = n + 1)
        begin
            @(negedge clk);
            mv = 1;
            ma = n;
            md = (n / 20) * 500 + (n % 20) * 20;
        end
        @(negedge clk);
        mv = 0;
        for (j = 0;j < 85;j = j + 1)
        begin
            wait(wv);
            if (!wv || wa != j || error)$fatal(1, "output order");
            value = (3 * bin_value(j + 1) + bin_value(j + 2)) / 4;
            expected = $shortrealtobits(value / 65536.0);
            if (wf !== expected)$fatal(1, "weight %0d expected %h actual %h", j, expected, wf);
            held = wf;
            held_address = wa;
            wr = 0;
            repeat(3)
            begin
                @(negedge clk);
                if (!wv || wf !== held || wa != held_address)$fatal(1, "backpressure instability");
            end
            wr = 1;
            @(negedge clk);
            wr = 0;
        end
        if (!done || !mr)$fatal(1, "window completion");
        @(negedge clk);
        mv = 1;
        ma = 1;
        @(negedge clk);
        mv = 0;
        if (!error || mr || wv)$fatal(1, "gap not rejected");
        $display("PASS CNN mask reduction: 1740 inputs, 85 weights, mean/interpolation, band limits, backpressure, gap rejection");
        $finish;
    end
    initial
    begin
        #200000;
        $fatal(1, "timeout");
    end
endmodule
