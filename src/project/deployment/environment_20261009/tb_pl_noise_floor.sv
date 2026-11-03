`timescale 1ns/1ps

module tb_pl_noise_floor;

    reg clk = 0;

    always #10 clk = ~clk;
    reg clear_reference = 0;
    reg rst_n = 0, arm = 0, retain_reference = 0, short_valid = 0, short_ready = 1;
    reg [2:0] short_channel = 0;
    reg [10:0] short_bin = 0;
    reg signed [31:0] short_real = 0, short_imag = 0;
    reg [8:0] read_address = 0;
    wire [31:0] read_float;
    wire ready, noisy;
    pl_noise_floor dut(.*);
    task tick;
    begin
        @(posedge clk);
        #1;
    end
    endtask
    task scenario(input integer base, input integer burst);
    begin
        @(negedge clk);
        rst_n = 0;
        tick;
        @(negedge clk);
        rst_n = 1;
        arm = 1;
        tick;
        @(negedge clk);
        arm = 0;
        for (integer f = 0;f < 20;f++)for (integer c = 0;c < 6;c++)for (integer b = 0;b < 257;b++)
        begin
            short_valid = 1;
            short_channel = c;
            short_bin = b;
            short_real = base + ((f == 5 && c == 2)?burst:0);
            short_imag = 0;
            tick;
            @(negedge clk);
        end
        short_valid = 0;
        repeat(270)tick;
        if (!ready)$fatal(1, "minimum estimator did not finish");
        read_address = 0;
        repeat(3)tick;
        if (base == 100 && (!noisy || read_float == 0))$fatal(1, "broadband reference missing");
        if (base == 1 && noisy)$fatal(1, "quiet room incorrectly marked noisy");
    end
    endtask
    initial
    begin
        scenario(100, 10000);
        // Once qualified, the same reference is retained even if another window starts.
        retain_reference = 1;
        @(negedge clk);
        arm = 1;
        tick;
        @(negedge clk);
        arm = 0;
        if (!ready || !noisy)$fatal(1, "qualified reference changed on rearm");
        // A rejected reference is replaced by the next complete window.
        retain_reference = 0;
        arm = 1;
        tick;
        @(negedge clk);
        arm = 0;
        if (ready)$fatal(1, "rejected reference was not invalidated");
        for (integer f = 0;f < 20;f++)for (integer c = 0;c < 6;c++)for (integer b = 0;b < 257;b++)
        begin
            short_valid = 1;
            short_channel = c;
            short_bin = b;
            short_real = 1;
            short_imag = 0;
            tick;
            @(negedge clk);
        end
        short_valid = 0;
        repeat(270)tick;
        if (!ready || noisy)$fatal(1, "replacement quiet reference failed");
        scenario(1, 0);
        $display("PASS noise floor: transient immunity, reference retention/refresh, quiet/noisy and bounded finish");
        $finish;
    end
    initial
    begin
        #3000000;
        $fatal(1, "test timeout");
    end
endmodule
