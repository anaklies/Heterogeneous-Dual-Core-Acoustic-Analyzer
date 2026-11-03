`timescale 1ns/1ps
module tb_fft_event_features;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,v=0,ready=0,rv=0,inject=0;
 wire done,good,fault,av,rr;wire [31:0] address;wire [191:0] channels;wire [255:0] bands;wire [63:0] ts;
 integer reads=0;reg [255:0] edges=0;
 fft_event_features dut(.clk(clk),.rst_n(rst_n),.frame_valid(v),.frame_base(32'h100000),.frame_last(64'd4095),.band_mask(8'd1),.band_edges(edges),.done_valid(done),.done_ready(ready),.feature_valid(good),.channel_power(channels),.band_power(bands),.timestamp(ts),.fault(fault),.araddr(address),.arvalid(av),.arready(1'b1),.rdata(32'h35800000),.rresp(inject?2'b10:2'b00),.rvalid(rv),.rlast(1'b1),.rready(rr));
 always @(posedge clk)begin
  if(av)begin
   if(address!=32'h100000+(reads/1025)*32768+(4098+3*(reads%1025))*4)$fatal(1,"source order mismatch");
   rv<=1;reads<=reads+1;
  end
  if(rv&&rr)rv<=0;
 end
 initial begin
  edges[15:0]=10;edges[31:16]=20;repeat(3)@(negedge clk);rst_n=1;v=1;
  while(!done)@(negedge clk);
  if(reads!=6150||!good||fault||ts!=4095)$fatal(1,"frame invalid");
  for(integer k=0;k<6;k++)if(channels[32*k+:32]!=1049600)$fatal(1,"channel sum incorrect");
  if(bands[31:0]!=10240)$fatal(1,"band integration incorrect");
  repeat(4)@(negedge clk);if(!done)$fatal(1,"result not held under backpressure");
  ready=1;v=0;@(negedge clk);ready=0;reads=0;v=1;inject=1;
  while(!done)@(negedge clk);if(good||!fault)$fatal(1,"DDR error produced valid features");
  $display("FFT_EVENT_FEATURES_PASS 6150_reads exact_Q30 band_edges retained_response invalid_DDR");$finish;
 end
 initial begin #1000000;$fatal(1,"timeout");end
endmodule
