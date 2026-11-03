`timescale 1ns/1ps

module tb_cnn_band;

    reg clk = 0;

    always #4 clk = ~clk;
    reg rst_n = 0, feature_valid = 0, start = 0, mask_ready = 1;
    wire feature_ready, busy, done, load_error, mask_valid;
    reg [15:0] feature_index = 0;
    reg signed [23:0] feature_data = 0;
    wire [12:0] mask_address;
    wire [15:0] mask_data;
    reg [23:0] inputs[0:41119];
    reg [15:0] expected[0:5139];
    integer count = 0, cycles = 0;
    cnn_v3_tiled #(.COEFF_DIR("C:/Users/sunxi/Desktop/sixmic3D_fpga/pl/coeff"), .TOTAL_FREQ(90), .OUTPUT_FREQ(87)) dut(.*);
    initial
    begin
        $readmemh("C:/Users/sunxi/Desktop/sixmic3D_fpga/pl/coeff/full_features.mem", inputs);
        $readmemh("C:/Users/sunxi/Desktop/sixmic3D_fpga/pl/coeff/full_expected.mem", expected);
        repeat(4) @(negedge clk);
        rst_n = 1;
        // Seven feature channels, followed by the final legacy channel.
        for (integer i = 0;i < 14400;i = i + 1) if (i % 8 != 3)
        begin
            @(negedge clk);
            feature_valid = 1;
            feature_index = i;
            feature_data = inputs[i];
        end
        for (integer t = 0;t < 20;t = t + 1) for (integer f = 0;f < 90;f = f + 1)
        begin
            @(negedge clk);
            feature_valid = 1;
            feature_index = (f * 20 + t) * 8 + 3;
            feature_data = inputs[(f * 20 + t) * 8 + 3];
        end
        @(negedge clk);
        feature_valid = 0;
        @(negedge clk);
        start = 1;
        @(negedge clk);
        start = 0;
        wait(done);
        @(negedge clk);
        if (load_error || count != 1740) $fatal(1, "CNN tile load/output error %0d", count);
        $display("PASS full 257x20 tiled trained CNN, %0d masks, %0d cycles", count, cycles);
        $finish;
    end

    always @(negedge clk) if (rst_n) mask_ready = (cycles % 7 != 0);

    always @(posedge clk)
    begin
        cycles <= cycles + 1;
        if (cycles > 5000000) $fatal(1, "tiled CNN timeout");
        if (mask_valid && mask_ready)
        begin
            if (mask_address !== count || mask_data !== expected[mask_address]) $fatal(1,
                "full mask %0d got %0d expected %0d", mask_address, mask_data, expected[mask_address]);
            count <= count + 1;
        end
    end
endmodule
