`timescale 1ns/1ps

module tb_pl_background_covariance;

    reg clk = 0;

    always #10 clk = ~clk;
    reg clear_reference = 0;
    reg rst_n = 0, start = 0, noise_present = 0;
    wire busy, done, valid, covariance_read_enable;
    wire [10:0] covariance_read_address;
    reg signed [47:0] covariance_real = 0, covariance_imag = 0;
    reg bg_r_ce = 0, bg_i_ce = 0;
    reg [10:0] bg_r_address = 0, bg_i_address = 0;
    wire [63:0] bg_r_data, bg_i_data;
    reg coherent = 0;
    integer cycles;
    pl_background_covariance dut(.*);

    always @(posedge clk)if (covariance_read_enable)
    begin
        covariance_real <= ((covariance_read_address % 21 == 0) || (covariance_read_address % 21 == 6) ||
            (covariance_read_address % 21 == 11) || (covariance_read_address % 21 == 15) ||
            (covariance_read_address % 21 ==
            18) || (covariance_read_address % 21 == 20))?48'sd100:(coherent?-48'sd100:48'sd0);
        covariance_imag <= 0;
    end
    task tick;
    begin
        @(posedge clk);
        #1;
    end
    endtask
    task run_case(input bit loud, input bit correlated, input bit expected);
    begin
        @(negedge clk);
        rst_n = 0;
        tick;
        @(negedge clk);
        rst_n = 1;
        noise_present = loud;
        coherent = correlated;
        start = 1;
        tick;
        @(negedge clk);
        start = 0;
        cycles = 0;
        while (!done && cycles < 4000)
        begin
            tick;
            cycles = cycles + 1;
        end
        if (!done || busy || valid != expected)$fatal(1,
            "reference qualification failed loud=%0d coherent=%0d valid=%0d cycles=%0d", loud, correlated,
            valid, cycles);
        if (expected)
        begin
            bg_r_ce = 1;
            bg_i_ce = 1;
            bg_r_address = 0;
            bg_i_address = 0;
            tick;
            if (bg_r_data != 100 || bg_i_data != 0)$fatal(1, "background memory mismatch");
            bg_r_address = 1;
            tick;
            if (bg_r_data != 0)$fatal(1, "off diagonal mismatch");
            bg_r_ce = 0;
            bg_i_ce = 0;
        end
    end
    endtask
    initial
    begin
        run_case(1, 0, 1);
        run_case(1, 1, 0);
        run_case(0, 0, 0);
        $display("PASS spatial background: 1785-pair capture, diffuse qualification, coherent-target veto, signed covariance, bounded completion");
        $finish;
    end
    initial
    begin
        #300000;
        $fatal(1, "timeout");
    end
endmodule
