`timescale 1ns/1ps
// One complete spectral window -> unchanged band features -> trained CNN.
// Background magnitudes are float32 bits. Input spectrum is packed signed int32 FFT, not float32.
// This block is a PL stage, not the final microphone-to-coordinate top.

module band_features_pipeline #(
    parameter COEFF_DIR = "pl/coeff",
    parameter STAGE_TIMEOUT = 250000000
)
(
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire spectrum_write_valid,
    output wire spectrum_write_ready,
    input  wire [13:0] spectrum_write_address,
    input  wire [63:0] spectrum_write_data,
    input  wire background_write_valid,
    output wire background_write_ready,
    input  wire [8:0] background_write_address,
    input  wire [31:0] background_write_data,
    output wire busy,
    output reg done,
    output reg pipeline_error,
    output wire mask_valid,
    input  wire mask_ready,
    output wire [12:0] mask_address,
    output wire [15:0] mask_data
);

    reg [($clog2(STAGE_TIMEOUT+1)>0?$clog2(STAGE_TIMEOUT+1):1)-1:0] running_cycles;
    reg running, hls_start;
    reg [6:0] write_bin;
    reg [2:0] write_channel;
    reg [4:0] write_frame;
    wire [13:0] expected_spectrum_address = write_bin * 120 + write_frame * 6 + write_channel;
    reg [13:0] loaded;
    reg [8:0] background_loaded;
    wire hls_done, hls_idle, hls_ready, cnn_busy, cnn_done, cnn_error, bridge_error, cnn_start;
    wire [13:0] spectrum_address;
    wire spectrum_ce;
    wire [63:0] spectrum_q;
    wire [45:0] spectrum_compact_q;
    assign spectrum_q = {spectrum_compact_q[45:23], 9'b0, spectrum_compact_q[22:0], 9'b0};
    wire [8:0] background_address;
    wire background_ce;
    reg [31:0] background_q;
    wire [13:0] feature_address;
    wire feature_ce, feature_we;
    wire [31:0] feature_value;
    wire delivered_valid, delivered_ready;
    wire [15:0] delivered_address;
    wire signed [23:0] delivered_value;
    wire raw_mask_valid;
    cnn_activation_ram #(.WIDTH(46), .DEPTH(10800), .ADDR_BITS(14)) spectrum_ram(
    .clk(clk), .we(spectrum_write_valid && spectrum_write_ready && spectrum_write_address ==
        expected_spectrum_address), .waddr(spectrum_write_address), .wdata({spectrum_write_data[63:41],
        spectrum_write_data[31:9]}),
        .re(spectrum_ce), .raddr(spectrum_address), .rdata(spectrum_compact_q));
    (* ram_style="block" *) reg [31:0] background_ram[0:256];
    // STFT order: frame 0..19, channel 0..5, bin 0..89.
    // Memory layout remains (bin*20+frame)*6+channel; no transpose RAM.
    assign spectrum_write_ready = !running && !start && !pipeline_error && loaded < 10800;
    assign background_write_ready = !running && !start && !pipeline_error;
    assign busy = running;
    assign mask_valid = raw_mask_valid && !pipeline_error && !bridge_error;

    always @(posedge clk)
    begin
        if (background_write_valid && background_write_ready && background_write_address ==
            (background_loaded ==
            257?0:background_loaded)) background_ram[background_write_address] <= background_write_data;
        if (background_ce) background_q <= background_address < 257?background_ram[background_address]:0;
    end
    cnn_features_band_0 features(.ap_clk(clk), .ap_rst(!rst_n), .ap_start(hls_start), .ap_done(hls_done),
        .ap_idle(hls_idle), .ap_ready(hls_ready),
        .spectrum_address0(spectrum_address), .spectrum_ce0(spectrum_ce), .spectrum_q0(spectrum_q),
        .background_address0(background_address), .background_ce0(background_ce), .background_q0(background_q),
        .feature_address0(feature_address), .feature_ce0(feature_ce), .feature_we0(feature_we),
        .feature_d0(feature_value));
    features_cnn_bridge #(.FEATURE_WORDS(14400)) bridge(.clk(clk), .rst_n(rst_n), .hls_ce(feature_ce),
        .hls_we(feature_we), .hls_address({2'b0, feature_address}), .hls_data(feature_value),
        .hls_done(hls_done),
        .feature_valid(delivered_valid), .feature_ready(delivered_ready), .feature_index(delivered_address),
        .feature_data(delivered_value), .cnn_busy(cnn_busy), .cnn_start(cnn_start),
        .bridge_error(bridge_error));
    cnn_v3_tiled #(.COEFF_DIR(COEFF_DIR), .TOTAL_FREQ(90), .OUTPUT_FREQ(87)) cnn(.clk(clk), .rst_n(rst_n),
        .feature_valid(delivered_valid), .feature_ready(delivered_ready), .feature_index(delivered_address),
        .feature_data(delivered_value),
        .start(cnn_start), .busy(cnn_busy), .done(cnn_done), .load_error(cnn_error),
        .mask_valid(raw_mask_valid),
        .mask_ready(mask_ready), .mask_address(mask_address), .mask_data(mask_data));

    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            running_cycles <= 0;
            running <= 0;
            hls_start <= 0;
            done <= 0;
            pipeline_error <= 0;
            loaded <= 0;
            background_loaded <= 0;
            write_bin <= 0;
            write_channel <= 0;
            write_frame <= 0;
        end

        else
        begin
            hls_start <= 0;
            done <= 0;
            if (running && running_cycles < STAGE_TIMEOUT)running_cycles <= running_cycles + 1;
            else if(running)running_cycles <= running_cycles;
            else running_cycles <= 0;
            if (spectrum_write_valid && spectrum_write_ready)
            begin
                if (spectrum_write_address != expected_spectrum_address || loaded >= 10800 ||
                    spectrum_write_data[40:32] !=
                    0 ||
                    spectrum_write_data[8:0] != 0) pipeline_error <= 1;
                else
                begin
                    loaded <= loaded + 1;
                    if (write_bin == 89)
                    begin
                        write_bin <= 0;
                        if (write_channel == 5)
                        begin
                            write_channel <= 0;
                            write_frame <= write_frame == 19?0:write_frame + 1;
                        end

                        else write_channel <= write_channel + 1;
                    end

                    else write_bin <= write_bin + 1;
                end
            end
            if (background_write_valid && background_write_ready)
            begin
                if (background_write_address != (background_loaded == 257?0:background_loaded)) pipeline_error <= 1;
                else background_loaded <= background_loaded == 257?1:background_loaded + 1;
            end
            if (start)
            begin
                if (running || loaded != 10800 || background_loaded != 257 || pipeline_error) pipeline_error <= 1;
                else
                begin
                    running <= 1;
                    hls_start <= 1;
                    loaded <= 0;
                end
            end
            if (bridge_error || cnn_error) pipeline_error <= 1;
            if (running && cnn_done)
            begin
                running <= 0;
                done <= 1;
            end
            if (running && running_cycles >= STAGE_TIMEOUT - 1)
            begin
                running <= 0;
                pipeline_error <= 1;
                done <= 1;
            end
        end
    end
endmodule
