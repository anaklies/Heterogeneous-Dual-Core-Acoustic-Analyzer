`timescale 1ns/1ps
module tb_window_recovery;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,recover=0,valid=0,allow_aw=1,inject_error=0;
 wire ready,done,fault,awvalid,wvalid,wlast,bready,release_valid;
 reg bvalid=0;reg [1:0] bresp=0;
 wire [31:0] err;integer released=0,cycles=0;
 window_dma #(.N(16),.TIMEOUT(80)) dut(.clk(clk),.rst_n(rst_n),.recover_ack(recover),
 .window_valid(valid),.window_ready(ready),.window_bank(1'b0),.window_frame(32'd9),.window_config(32'd1),.window_session(32'd1),.window_first(64'd0),
 .slot_valid(1'b1),.slot_id(2'd0),.slot_address(32'h1000),.read_data(144'b0),.release_valid(release_valid),
 .done_valid(done),.done_ready(1'b1),.done_error(err),.fault_latched(fault),
 .awvalid(awvalid),.awready(allow_aw),.wvalid(wvalid),.wlast(wlast),.wready(1'b1),.bresp(bresp),.bvalid(bvalid),.bready(bready));
 always @(posedge clk)begin
  cycles<=cycles+1;
  if(wvalid&&wlast)begin bvalid<=1;bresp<=inject_error?2:0;end
  if(bvalid&&bready)bvalid<=0;
  if(release_valid)begin released<=released+1;if(err==0)$fatal(1,"failed transfer published valid");end
  if(cycles>2000)$fatal(1,"recovery timeout");
 end
 task submit;begin while(!ready)@(negedge clk);valid=1;@(negedge clk);valid=0;end endtask
 initial begin
  repeat(4)@(negedge clk);rst_n=1;inject_error=1;submit();
  while(released!=1)@(negedge clk);if(!fault)$fatal(1,"BRESP not latched");
  recover=1;@(negedge clk);recover=0;@(negedge clk);if(fault)$fatal(1,"drained fault not cleared");
  inject_error=0;allow_aw=0;submit();while(!fault)@(negedge clk);
  recover=1;repeat(3)@(negedge clk);
  if(!awvalid||!fault||released!=1)$fatal(1,"in-flight VALID withdrawn on recovery");
  recover=0;allow_aw=1;while(released!=2)@(negedge clk);
  recover=1;@(negedge clk);recover=0;@(negedge clk);if(fault)$fatal(1,"second recovery failed");
  $display("WINDOW_DMA_RECOVERY_PASS released=%0d",released);$finish;
 end
endmodule
