`timescale 1ns/1ps
// Spectral minimum from 20 short FFT frames, without a manual mode switch.

module pl_noise_floor
(
    input  wire clk,
    input  wire rst_n,
    input wire clear_reference,
    input  wire arm,
    input  wire retain_reference,
    input  wire short_valid,
    input  wire short_ready,
    input  wire [2:0] short_channel,
    input  wire [10:0] short_bin,
    input  wire signed [31:0] short_real,
    input  wire signed [31:0] short_imag,
    input  wire [8:0] read_address,
    output reg [31:0] read_float,
    output reg ready,
    output wire noisy
);

    (* ram_style="block" *)reg [23:0] floor_q16[0:256];
    reg [23:0] read_q, magnitude_q16;
    reg [8:0] write_address;
    reg write_pending, write_first;
    reg [4:0] frames;
    reg capturing, scanning, scan_valid;
    reg [8:0] scan_address;
    reg [8:0] loud_bins;
    function automatic[23:0] magnitude(input signed [31:0] re, im);
    reg [31:0] ar, ai;
    reg [32:0] sum;
    begin
        ar = re[31]?-re:re;
        ai = im[31]?-im:im;
        sum = {1'b0, ar} + {1'b0, ai};
        magnitude = sum > 33'd4194303 ? 24'hffffff : (sum[21:0] << 2) + 1;
    end
    endfunction
    function automatic[31:0] q16_float(input [23:0] value);
    integer p;
    reg [31:0] normalized;
    begin
        p = 0;
        for (integer k = 0;k < 24;k = k + 1)if (value[k])p = k;
        normalized = {8'b0, value} << (23 - p);
        q16_float = value == 0?0:{1'b0, 8'(111 + p), normalized[22:0]};
    end
    endfunction
    wire [8:0] floor_read_address = (capturing && short_valid && short_ready &&
        short_bin < 257)?short_bin[8:0]:(scanning?scan_address:read_address);
    assign noisy = ready && loud_bins >= 129;
    // majority of bins above Q16=12

    always @(posedge clk)
    begin
        read_q <= floor_q16[floor_read_address];
        read_float <= q16_float(read_q);
        if (write_pending)floor_q16[write_address] <=
            write_first?magnitude_q16:(magnitude_q16 < read_q?magnitude_q16:read_q);
    end

    always @(posedge clk)
    begin
        if (!rst_n || clear_reference)
        begin
            frames <= 0;
            capturing <= 0;
            ready <= 0;
            write_pending <= 0;
            write_first <= 0;
            write_address <= 0;
            magnitude_q16 <= 0;
            loud_bins <= 0;
            scanning <= 0;
            scan_address <= 0;
            scan_valid <= 0;
        end

        else
        begin
            write_pending <= 0;
            // A rejected reference is sampled again on the next window. A qualified
            // reference remains frozen so a tracked source cannot become background.
            if (arm && !capturing && !scanning && (!ready || !retain_reference))
            begin
                capturing <= 1;
                ready <= 0;
                frames <= 0;
                loud_bins <= 0;
            end
            if (capturing && short_valid && short_ready && short_bin < 257)
            begin
                write_address <= short_bin[8:0];
                magnitude_q16 <= magnitude(short_real, short_imag);
                write_pending <= 1;
                write_first <= frames == 0 && short_channel == 0;
                if (short_bin == 256 && short_channel == 5)
                begin
                    if (frames == 19)
                    begin
                        capturing <= 0;
                        scanning <= 1;
                        scan_address <= 0;
                        scan_valid <= 0;
                    end

                    else frames <= frames + 1;
                end
            end
            if (scanning)
            begin
                scan_valid <= 1;
                if (scan_valid && read_q > 12 && loud_bins < 257)loud_bins <= loud_bins + 1;
                if (scan_address == 256)
                begin
                    scanning <= 0;
                end

                else scan_address <= scan_address + 1;
            end

            else if (scan_valid)
            begin
                scan_valid <= 0;
                if (read_q > 12 && loud_bins < 257)loud_bins <= loud_bins + 1;
                ready <= 1;
            end
        end
    end
endmodule
