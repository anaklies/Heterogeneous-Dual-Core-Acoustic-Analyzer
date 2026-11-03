`timescale 1ns/1ps

module tb_covariance_6ch;

    reg read_imag_enable = 0;
    reg [10:0] read_imag_address = 0;
    reg clk = 0;

    always #5 clk = ~clk;
    reg rst_n = 0, clear = 0, spectrum_valid = 0, spectrum_short = 0, read_enable = 0;
    wire spectrum_ready, busy;
    reg [2:0] spectrum_channel = 0;
    reg [10:0] spectrum_bin = 5, read_address = 0;
    reg signed [31:0] spectrum_real = 0, spectrum_imag = 0;
    wire signed [47:0] read_real, read_imag;
    wire [31:0] observation_count;
    covariance_6ch dut(.*);
    integer index = 0;
    initial
    begin
        repeat(3) @(negedge clk);
        rst_n = 1;
        wait(spectrum_ready);
        for (integer c = 0;c < 6;c = c + 1)
        begin
            @(negedge clk);
            spectrum_valid = 1;
            spectrum_channel = c;
            spectrum_real = (c + 1) * 256;
            spectrum_imag = (6 - c) * 256;
        end
        @(negedge clk);
        spectrum_valid = 0;
        wait(spectrum_ready);
        for (integer a = 0;a < 6;a = a + 1) for (integer b = a;b < 6;b = b + 1)
        begin
            @(negedge clk);
            read_enable = 1;
            read_address = index;
            @(negedge clk);
            if (read_real !== ((a + 1) * (b + 1) + (6 - a) * (6 - b))) $fatal(1, "real pair %0d", index);
            if (read_imag !== ((6 - a) * (b + 1) - (a + 1) * (6 - b))) $fatal(1, "imag pair %0d got %0d", index,
                read_imag);
            index = index + 1;
        end
        read_imag_enable = 1;
        read_imag_address = 1;
        read_address = 0;
        @(negedge clk);
        @(negedge clk);
        if (read_real != 37 || read_imag != 7)$fatal(1, "independent real/imag read addresses");
        read_enable = 0;
        read_imag_address = 2;
        @(negedge clk);
        @(negedge clk);
        if (read_real != 37 || read_imag != 14)$fatal(1, "imag-only read");
        $display("PASS six-channel complex covariance: 21 Hermitian entries, independent real/imag and imag-only reads");
        $finish;
    end
    initial
    begin
        #1000000;
        $fatal(1, "covariance timeout");
    end
endmodule
