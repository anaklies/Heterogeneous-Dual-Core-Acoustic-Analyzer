`timescale 1ns/1ps
module tb_stream_job_bridge;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,job_valid=0,completion_ready=0,kernel_dma_idle=1;
 reg [31:0] job_token=0,job_kernel_base=0,status_value=0;
 reg [4:0] job_arg_count=0;
 reg [127:0] job_offsets=0;reg [511:0] job_values=0;
 wire job_ready,completion_valid,fault_latched;
 wire [31:0] completion_token,completion_error,result0,result1;
 wire [1:0] active_kernel;
 wire [31:0] m_awaddr,m_wdata,m_araddr;
 wire m_awvalid,m_wvalid,m_bready,m_arvalid,m_rready;wire [3:0] m_wstrb;
 reg m_awready=0,m_wready=0,m_bvalid=0,m_arready=0,m_rvalid=0;
 reg [1:0] m_bresp=0,m_rresp=0;reg [31:0] m_rdata=0;
 reg aw_seen=0,w_seen=0;reg [31:0] write_address,write_value;
 integer ticks=0,running=0,starts=0,checks=0,reads=0;
 stream_job_bridge #(.TIMEOUT_CYCLES(2000),.POLL_CYCLES(2)) dut(
 .clk(clk),.rst_n(rst_n),.job_valid(job_valid),.job_ready(job_ready),
 .job_token(job_token),.job_kernel_base(job_kernel_base),.job_arg_count(job_arg_count),
 .job_offsets(job_offsets),.job_values(job_values),.memory_fault(1'b0),
 .kernel_dma_idle(kernel_dma_idle),.active_kernel(active_kernel),
 .completion_valid(completion_valid),.completion_ready(completion_ready),
 .completion_token(completion_token),.completion_error(completion_error),.result0(result0),.result1(result1),
 .fault_latched(fault_latched),.recover_request(1'b0),.common_bus_reset_ack(1'b0),
 .m_awaddr(m_awaddr),.m_wdata(m_wdata),.m_araddr(m_araddr),
 .m_awvalid(m_awvalid),.m_wvalid(m_wvalid),.m_bready(m_bready),
 .m_arvalid(m_arvalid),.m_rready(m_rready),.m_wstrb(m_wstrb),
 .m_awready(m_awready),.m_wready(m_wready),.m_bvalid(m_bvalid),
 .m_arready(m_arready),.m_rvalid(m_rvalid),.m_bresp(m_bresp),.m_rresp(m_rresp),.m_rdata(m_rdata));
 always @(posedge clk)begin
  ticks<=ticks+1;
  m_awready<=ticks%3==0;m_wready<=ticks%4==0;m_arready<=!m_rvalid;
  if(running>0)running<=running-1;
  if(m_awvalid&&m_awready)begin aw_seen<=1;write_address<=m_awaddr;end
  if(m_wvalid&&m_wready)begin w_seen<=1;write_value<=m_wdata;end
  if(aw_seen&&w_seen&&!m_bvalid)begin
   m_bvalid<=1;aw_seen<=0;w_seen<=0;
   if(write_address[15:0]==0&&write_value==1)begin running<=15;starts<=starts+1;end
  end
  if(m_bvalid&&m_bready)m_bvalid<=0;
  if(m_rvalid&&m_rready)m_rvalid<=0;
  if(m_arvalid&&m_arready)begin
   m_rvalid<=1;reads<=reads+1;
   if(m_araddr==32'h44a50000||m_araddr==32'h44a40000)m_rdata<=running?0:6;
   else if(m_araddr==32'h44a50058||m_araddr==32'h44a40048)m_rdata<=status_value;
   else $fatal(1,"unexpected/DDR metadata address %h",m_araddr);
  end
  if(ticks>5000)$fatal(1,"test timeout");
 end
 task check(input bit ok);begin checks=checks+1;if(!ok)$fatal(1,"check %0d failed",checks);end endtask
 task submit(input [31:0] base,input integer count,input bit invalid_offset);
 begin
  while(!job_ready)@(negedge clk);
  @(negedge clk);job_kernel_base=base;job_arg_count=count;job_token=job_token+1;
  for(integer i=0;i<16;i=i+1)begin job_offsets[i*8+:8]=8'h10+i*8;job_values[i*32+:32]=32'h100+i;end
  if(invalid_offset)job_offsets[7:0]=8'h18;
  job_valid=1;@(negedge clk);job_valid=0;
 end endtask
 task finish(input [31:0] expected);
 begin
  while(!completion_valid)@(negedge clk);
  check(completion_error==expected);check(completion_token==job_token);
  repeat(3)begin @(negedge clk);check(completion_valid&&completion_error==expected);end
  completion_ready=1;@(negedge clk);completion_ready=0;
 end endtask
 initial begin
  repeat(3)@(negedge clk);rst_n=1;
  submit(32'h44a40000,7,0);finish(0);check(active_kernel==0);
  status_value=3;submit(32'h44a50000,9,0);finish(32);check(active_kernel==1);
  status_value=32'h80000000;submit(32'h44a50000,9,0);finish(0);check(result1[31]);
  status_value=0;submit(32'h44a10000,6,0);finish(1);
  submit(32'h44a50000,9,1);finish(1);
  kernel_dma_idle=0;submit(32'h44a40000,7,0);
  repeat(220)begin @(negedge clk);check(!completion_valid);end
  kernel_dma_idle=1;finish(0);check(starts==4);check(!fault_latched);
  $display("STREAM_JOB_BRIDGE_PASS checks=%0d starts=%0d",checks,starts);$finish;
 end
endmodule
