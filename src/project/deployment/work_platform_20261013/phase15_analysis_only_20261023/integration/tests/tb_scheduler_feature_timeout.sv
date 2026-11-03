`timescale 1ns/1ps
module tb_scheduler_feature_timeout;
 reg feature_complete=0;wire feature_request;
 reg clk=0;always #10 clk=~clk;
 reg rst_n=0,cfg_valid=0;wire cfg_ready,cfg_applied,cfg_rejected;
 reg [31:0] cfg_version=7,cfg_session=3;reg cfg_pause=0;
 wire [31:0] active_session,active_config;wire slot_valid;wire [1:0] slot_id;wire [31:0] slot_address;
 reg slot_take=0,fill_done=0;reg [1:0] fill_slot=0;
 reg [31:0] frame=0,fill_frame=0,fill_config=0,fill_session=0,fill_error=0;
 reg [63:0] first=0;
 wire command_valid;reg command_ready=1;
 wire [31:0] command_token,command_base;wire [4:0] command_count;wire [127:0] offsets;wire [511:0] values;
 reg completion_valid=0;reg [31:0] completion_token=0,completion_error=0,completion_status=0;
 wire completion_ready,result_update;wire [1:0] result_slot;
 wire [31:0] result_frame,result_config,result_session,result_cycles,result_base;
 wire [63:0] result_first;wire [3:0] snapshot_valid;
 wire [31:0] overwritten,stale,failed,background,canceled;
 wire fault;reg reset_ack=0;
 analysis_scheduler #(.FEATURES_ENABLED(1),.WINDOW_CYCLES(10000),.SCALAR_BUDGET(200),.JOB_TIMEOUT(1000),.PERIOD1(3000),.PERIOD2(5000),.PUBLISH_WINDOWS(2)) dut(
 .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid),.cfg_ready(cfg_ready),.cfg_session(cfg_session),.cfg_version(cfg_version),.cfg_arena_base(32'h10000000),.cfg_arena_words(32'h400000),.cfg_reserved_low(32'h10000000),.cfg_reserved_high(32'h11000000),
 .cfg_p2_oneshot(1'b0),.cfg_p1_last_index(4'd0),.cfg_p1_stride(32'd0),.cfg_p1_descriptor(32'h80000),.cfg_p2_descriptor(32'h80100),.cfg_p1_enable(1'b1),.cfg_p2_enable(1'b1),.cfg_pause_p1_when_p2(cfg_pause),.cfg_applied(cfg_applied),.cfg_rejected(cfg_rejected),.active_session(active_session),.active_config(active_config),
 .slot_valid(slot_valid),.slot_id(slot_id),.slot_address(slot_address),.slot_take(slot_take),.taking_frame(frame),.taking_config(active_config),.taking_session(active_session),.taking_first(first),
 .fill_done(fill_done),.fill_slot(fill_slot),.fill_frame(fill_frame),.fill_config(fill_config),.fill_session(fill_session),.fill_error(fill_error),.fill_ready(),
 .command_valid(command_valid),.command_ready(command_ready),.command_token(command_token),.command_base(command_base),.command_count(command_count),.command_offsets(offsets),.command_values(values),
 .completion_valid(completion_valid),.completion_token(completion_token),.completion_error(completion_error),.completion_status(completion_status),.completion_ready(completion_ready),
 .result_update(result_update),.result_slot(result_slot),.result_frame(result_frame),.result_config(result_config),.result_session(result_session),.result_cycles(result_cycles),.result_first(result_first),.result_base(result_base),
 .result_ack(1'b0),.ack_slot(2'b0),.ack_frame(32'b0),.ack_session(32'b0),.snapshot_valid(snapshot_valid),.overwritten_results(overwritten),.stale_completions(stale),.failed_frames(failed),.background_completions(background),.canceled_contexts(canceled),.fault_latched(fault),.feature_request(feature_request),.feature_complete(feature_complete),.common_reset_ack(reset_ack));
 integer ticks=0,delay=0,p1chunks=0,p2chunks=0,fftjobs=0,pubs=0,checks=0;
 reg [31:0] pending_token,pending_base;reg [31:0] pending_descriptor;reg stall=0;
 always @(posedge clk)begin
  ticks<=ticks+1;completion_valid<=0;
  if(command_valid&&command_ready)begin
   if(delay!=0)$fatal(1,"scheduler re-entered busy engine");
   pending_token<=command_token;pending_base<=command_base;pending_descriptor<=values[32+:32];
   for(integer k=0;k<command_count;k=k+1)if(offsets[k*8+:8]!=(8'h10+k*8))$fatal(1,"register ABI mismatch");
   if(command_base==32'h44a40000)begin
    if(command_count!=7||values[4*32+:32]!=1||values[5*32+:32]!=3)$fatal(1,"bad real FFT command");
    fftjobs<=fftjobs+1;delay<=70;
   end else begin if(command_base!=32'h44a50000||command_count!=9)$fatal(1,"old backend requested");
    if(values[6*32+:32]!=dut.frames[values[3*32+:32]]||values[7*32+:32]!=dut.firsts[values[3*32+:32]][31:0]||values[8*32+:32]!=dut.firsts[values[3*32+:32]][63:32])$fatal(1,"source metadata mismatch");delay<=100;end
  end
  if(delay>0&&!stall)begin
   delay<=delay-1;
   if(delay==1)begin
    completion_valid<=1;completion_token<=pending_token;completion_status<=0;completion_error<=0;
    if(pending_base==32'h44a50000)begin
     if(pending_descriptor>=32'h80000&&pending_descriptor<32'h80040)begin p1chunks<=p1chunks+1;completion_status<=(p1chunks%3==2)?32'h80000000:32'h1200;end
     else begin p2chunks<=p2chunks+1;completion_status<=(p2chunks%3==2)?32'h80000000:32'h1300;end
    end
   end
  end
  if(result_update)begin
   if(result_config!=active_config||result_session!=active_session||result_cycles>=1000||result_base<32'h10100000)$fatal(1,"bad publication metadata/deadline");
   pubs<=pubs+1;checks<=checks+1;
  end
  if(ticks>150000)$fatal(1,"test timeout");
 end
 task configure;
 begin
  @(negedge clk);cfg_valid=1;
  while(!cfg_ready)@(negedge clk);
  @(negedge clk);cfg_valid=0;if(!cfg_applied||cfg_rejected)$fatal(1,"config not atomically applied");
 end endtask
 task window_frame(input integer n);
 begin
  while(!slot_valid)@(negedge clk);
  frame=n;first=n*512;fill_slot=slot_id;fill_frame=n;fill_config=active_config;fill_session=active_session;
  if(slot_address<32'h10000000||slot_address>=32'h10040000)$fatal(1,"slot outside input region");
  if((dut.p1_running&&dut.p1_source==slot_id)||(dut.p2_running&&dut.p2_source==slot_id))$fatal(1,"pinned source overwritten");
  slot_take=1;@(negedge clk);slot_take=0;
  repeat(15)@(negedge clk);fill_error=n==13?2:0;fill_done=1;@(negedge clk);fill_done=0;
 end endtask
 initial begin
  repeat(4)@(negedge clk);rst_n=1;configure();window_frame(1);
  while(!feature_request)@(negedge clk);
  while(dut.age<999)@(negedge clk);
  feature_complete=1;@(negedge clk);feature_complete=0;
  if(!fault||result_update||feature_request)$fatal(1,"timeout leaked late publication/request");
  repeat(30)begin @(negedge clk);if(feature_request||result_update)$fatal(1,"faulted feature relaunched");end
  $display("SCHEDULER_FEATURE_TIMEOUT_PASS boundary completion rejected no repeated request");$finish;
 end
 initial begin #1000000;$fatal(1,"timeout");end
endmodule
