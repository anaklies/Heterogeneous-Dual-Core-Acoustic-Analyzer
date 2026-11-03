`timescale 1ns/1ps
// Real serial INMP441 left-slot input. Common reset is required for both domains.
module pcm_capture(
 input wire clk_audio,clk_compute,rst_n,
 input wire [5:0] mic_sd,
 output wire mic_sck,mic_ws,
 output wire pcm_valid,
 output wire [143:0] pcm,
 output wire [63:0] sample_id,
 output wire overflow_audio
);
 wire rise,fall,frame_ce,valid;
 wire signed [23:0] m0,m1,m2,m3,m4,m5;
 reg [63:0] id;
 wire [207:0] packet;
 (* ASYNC_REG="TRUE" *) reg [1:0] audio_reset_sync;
 always @(posedge clk_audio or negedge rst_n)if(!rst_n)audio_reset_sync<=0;else audio_reset_sync<={audio_reset_sync[0],1'b1};
 wire audio_rst_n=audio_reset_sync[1];
 i2s_timing_gen clocking_unit(.clk_audio(clk_audio),.rst_n(audio_rst_n),.i2s_bclk(mic_sck),.i2s_ws(mic_ws),.bclk_rise_ce(rise),.bclk_fall_ce(fall),.frame_start_ce(frame_ce));
 i2s_rx_6ch receiver(.clk_audio(clk_audio),.rst_n(audio_rst_n),.i2s_ws(mic_ws),.bclk_rise_ce(rise),
  .mic1_sd(mic_sd[0]),.mic2_sd(mic_sd[1]),.mic3_sd(mic_sd[2]),.mic4_sd(mic_sd[3]),.mic5_sd(mic_sd[4]),.mic6_sd(mic_sd[5]),
  .mic1_data(m0),.mic2_data(m1),.mic3_data(m2),.mic4_data(m3),.mic5_data(m4),.mic6_data(m5),.sample_valid(valid));
 always @(posedge clk_audio or negedge audio_rst_n)if(!audio_rst_n)id<=0;else if(valid&&id!=64'hffffffffffffffff)id<=id+1'b1;
 sample_cdc crossing(.wr_clk(clk_audio),.wr_rst_n(audio_rst_n),.wr_valid(valid&&id!=64'hffffffffffffffff),
  .wr_data({id,m5,m4,m3,m2,m1,m0}),.overflow_sticky(overflow_audio),
  .rd_clk(clk_compute),.rd_rst_n(rst_n),.rd_valid(pcm_valid),.rd_ready(1'b1),.rd_data(packet));
 assign pcm=packet[143:0];assign sample_id=packet[207:144];
endmodule
