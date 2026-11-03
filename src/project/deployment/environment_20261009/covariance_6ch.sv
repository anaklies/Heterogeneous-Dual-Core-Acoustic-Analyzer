`timescale 1ns/1ps
// Upper Hermitian triangle R_ij = sum X_i*conj(X_j), 85 MUSIC bins.
// Input FFT normalized by N, then drops 8 PCM LSBs. Output not divided by T.
// Read snapshots only when the upstream observation window is paused.

module covariance_6ch
(
    input  wire clk,
    input  wire rst_n,
    input  wire clear,
    input  wire spectrum_valid,
    output wire spectrum_ready,
    input  wire spectrum_short,
    input  wire [2:0] spectrum_channel,
    input  wire [10:0] spectrum_bin,
    input  wire signed [31:0] spectrum_real,
    input  wire signed [31:0] spectrum_imag,
    input  wire read_enable,
    input  wire [10:0] read_address,
    input  wire read_imag_enable,
    input  wire [10:0] read_imag_address,
    output reg signed [47:0] read_real,
    output reg signed [47:0] read_imag,
    output reg [31:0] observation_count,
    output wire busy
);

    localparam COLLECT = 0, READ = 1, MULTIPLY = 2, WRITE = 3, NEXT = 4, CLEAR = 5, LOAD = 6;
    reg [2:0] state;
    reg [10:0] clear_address, current_address;
    reg [6:0] current_bin;
    reg [2:0] i, j;
    reg [4:0] pair_index;
    reg signed [15:0] buffered_real[0:4], buffered_imag[0:4];
    wire [6:0] bin_index = (spectrum_bin - 5) >> 2;
    genvar channel_index;
    generate
        for (channel_index = 0;channel_index < 5;channel_index = channel_index + 1)
        begin
            : channel_buffer
            (* ram_style="block" *)reg signed [15:0] real_ram[0:84], imag_ram[0:84];

            always @(posedge clk)
            begin
                if (state == COLLECT && spectrum_valid && !spectrum_short && spectrum_bin >= 5 && spectrum_bin <= 341 &&
                    spectrum_bin[1:0] == 1 && spectrum_channel == channel_index)
                begin
                    real_ram[bin_index] <= $signed(spectrum_real) >>> 8;
                    imag_ram[bin_index] <= $signed(spectrum_imag) >>> 8;
                end
                if (state == COLLECT && spectrum_valid && spectrum_channel == 5)
                begin
                    buffered_real[channel_index] <= real_ram[bin_index];
                    buffered_imag[channel_index] <= imag_ram[bin_index];
                end
            end
        end
    endgenerate
    reg signed [15:0] xr[0:5], xi[0:5];
    (* ram_style="block" *) reg signed [47:0] sum_real[0:1784], sum_imag[0:1784];
    reg signed [47:0] previous_real, previous_imag;
    (* use_dsp="yes" *) reg signed [32:0] product_real, product_imag;
    (* use_dsp="yes" *) wire signed [47:0] accumulated_real = previous_real + product_real;
    (* use_dsp="yes" *) wire signed [47:0] accumulated_imag = previous_imag + product_imag;
    wire [10:0] external_imag_address = read_imag_enable?read_imag_address:read_address;
    wire external_imag_enable = (read_imag_enable || read_enable) && external_imag_address < 1785;
    wire [10:0] internal_address = (state == CLEAR)?clear_address:current_address;

    assign spectrum_ready = (state == COLLECT && !clear);
    assign busy = (state != COLLECT);

    always @(posedge clk)
    begin
        if (state == CLEAR)
        begin
            sum_real[internal_address] <= 0;
            sum_imag[internal_address] <= 0;
        end

        else if (state == WRITE)
        begin
            sum_real[internal_address] <= accumulated_real;
            sum_imag[internal_address] <= accumulated_imag;
        end
        if (state == READ)
        begin
            previous_real <= sum_real[internal_address];
            previous_imag <= sum_imag[internal_address];
        end
    end

    always @(posedge clk)
    begin
        if (read_enable && read_address < 1785) read_real <= sum_real[read_address];
        if (external_imag_enable)read_imag <= sum_imag[external_imag_address];
    end

    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            state <= CLEAR;
            clear_address <= 0;
            current_address <= 0;
            current_bin <= 0;
            i <= 0;
            j <= 0;
            pair_index <= 0;
            observation_count <= 0;
            product_real <= 0;
            product_imag <= 0;
        end

        else if (clear && state == COLLECT)
        begin
            state <= CLEAR;
            clear_address <= 0;
            observation_count <= 0;
        end

        else case
        (state)
        CLEAR:
        begin
            if (clear_address == 1784)
            begin
                state <= COLLECT;
                clear_address <= 0;
            end

            else clear_address <= clear_address + 1;
        end
        COLLECT: if (spectrum_valid && !spectrum_short && spectrum_bin >= 5 && spectrum_bin <= 341 &&
            spectrum_bin[1:0] == 1)
        begin
            if (spectrum_channel == 5)
            begin
                xr[5] <= $signed(spectrum_real) >>> 8;
                xi[5] <= $signed(spectrum_imag) >>> 8;
                current_bin <= bin_index;
                current_address <= bin_index * 21;
                i <= 0;
                j <= 0;
                pair_index <= 0;
                state <= LOAD;
            end
        end
        LOAD:
        begin
            for (integer c = 0;c < 5;c = c + 1)
            begin
                xr[c] <= buffered_real[c];
                xi[c] <= buffered_imag[c];
            end
            state <= READ;
        end
        READ: state <= MULTIPLY;
        MULTIPLY:
        begin
            product_real <= ($signed(xr[i]) * $signed(xr[j])) + ($signed(xi[i]) * $signed(xi[j]));
            product_imag <= ($signed(xi[i]) * $signed(xr[j])) - ($signed(xr[i]) * $signed(xi[j]));
            state <= WRITE;
        end
        WRITE: state <= NEXT;
        NEXT:
        begin
            if (pair_index == 20)
            begin
                state <= COLLECT;
                if (current_bin == 84) observation_count <= observation_count + 1;
            end

            else
            begin
                pair_index <= pair_index + 1;
                current_address <= current_address + 1;
                if (j == 5)
                begin
                    i <= i + 1;
                    j <= i + 1;
                end

                else j <= j + 1;
                state <= READ;
            end
        end
    endcase
    end
endmodule
