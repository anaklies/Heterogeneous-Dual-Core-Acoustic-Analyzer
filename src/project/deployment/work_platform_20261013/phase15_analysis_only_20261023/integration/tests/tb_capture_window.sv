`timescale 1ns/1ps
module tb_capture_window;
 reg audio=0,clk=0,rst_n=0;
 always #10.170 audio=~audio;always #10 clk=~clk;
 reg [5:0] sd=0;wire sck,ws,valid,overflow;wire [143:0] pcm;wire [63:0] id;
 pcm_capture capture(.clk_audio(audio),.clk_compute(clk),.rst_n(rst_n),.mic_sd(sd),.mic_sck(sck),.mic_ws(ws),.pcm_valid(valid),.pcm(pcm),.sample_id(id),.overflow_audio(overflow));
 integer serial_frame=0,serial_bit=0;reg previous_ws=0;
 function automatic [23:0] pattern(input integer frame,input integer ch);
  integer value;begin value=frame*123+ch*7777;pattern=ch%2?-value:value;end
 endfunction
 always @(negedge sck)begin
  if(ws!=previous_ws)begin serial_bit=0;if(!ws)serial_frame=serial_frame+1;end
  else serial_bit=serial_bit+1;
  previous_ws=ws;
  for(integer c=0;c<6;c=c+1)begin
   if(!ws&&serial_bit>=1&&serial_bit<=24)sd[c]=(pattern(serial_frame,c)>>(24-serial_bit))&1;
   else sd[c]=0;
  end
 end
 wire wvalid,wready,bank,release_valid,release_bank,read_bank,done;
 wire [31:0] frame,config_id,session,release_frame,missed,gaps,bad_release;
 wire [63:0] first;wire [10:0] read_index;wire [143:0] read_data;wire [1:0] occupied;
 window_pool pool(.clk(clk),.rst_n(rst_n),.pcm_valid(valid),.pcm(pcm),.sample_id(id),.config_version(32'd7),.session_id(32'd3),
  .window_valid(wvalid),.window_ready(wready),.window_bank(bank),.window_frame(frame),.window_config(config_id),.window_session(session),.window_first(first),
  .release_valid(release_valid),.release_bank(release_bank),.release_frame(release_frame),.read_bank(read_bank),.read_index(read_index),.read_data(read_data),
  .missed_windows(missed),.gaps(gaps),.bad_release(bad_release),.occupied(occupied));
 reg done_ready=0;wire take,fault;wire [1:0] done_slot;wire [31:0] done_frame,done_config,done_session,done_error;wire [63:0] done_first;
 wire [31:0] awaddr,wdata;wire [7:0] awlen;wire [2:0] awsize;wire [1:0] awburst;
 wire awvalid,wvalid_bus,wlast,bready;wire [3:0] wstrb;
 reg awready=0,wready_bus=0,bvalid=0;reg [1:0] bresp=0;
 window_dma dma(.clk(clk),.rst_n(rst_n),.recover_ack(1'b0),.window_valid(wvalid),.window_bank(bank),.window_ready(wready),.window_frame(frame),.window_config(config_id),.window_session(session),.window_first(first),
  .slot_valid(1'b1),.slot_id(2'd0),.slot_address(32'h1000),.slot_take(take),.read_bank(read_bank),.read_index(read_index),.read_data(read_data),
  .release_valid(release_valid),.release_bank(release_bank),.release_frame(release_frame),.done_valid(done),.done_ready(done_ready),.done_slot(done_slot),
  .done_frame(done_frame),.done_config(done_config),.done_session(done_session),.done_error(done_error),.done_first(done_first),.fault_latched(fault),
  .awaddr(awaddr),.awlen(awlen),.awsize(awsize),.awburst(awburst),.awvalid(awvalid),.awready(awready),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.wvalid(wvalid_bus),.wready(wready_bus),.bresp(bresp),.bvalid(bvalid),.bready(bready));
 reg [31:0] memory[0:16383];integer ticks=0,beats=0,bdelay=0,bursts=0,samples=0,checks=0;reg pending=0;reg [31:0] address;
 always @(posedge clk)begin
  ticks<=ticks+1;awready<=!pending&&!bvalid&&ticks%11<8;wready_bus<=pending&&ticks%7<5;
  if(valid)begin
   if(id!=samples)$fatal(1,"CDC sample order %0d !=%0d",id,samples);
   for(integer c=0;c<6;c=c+1)if(pcm[c*24+:24]!=pattern(samples+1,c))$fatal(1,"serial channel%0d sample%0d got%h expected%h",c,samples,pcm[c*24+:24],pattern(samples+1,c));
   samples<=samples+1;
  end
  if(awvalid&&awready)begin
   if(pending||awaddr[5:0]||awlen!=15||awsize!=2||awburst!=1)$fatal(1,"bad AXI address/burst");
   pending<=1;address<=awaddr;beats<=0;
  end
  if(wvalid_bus&&wready_bus)begin
   if(!pending||wstrb!=15||wlast!=(beats==15))$fatal(1,"bad write beat");
   memory[(address>>2)+beats]<=wdata;beats<=beats+1;
   if(wlast)begin pending<=0;bdelay<=4;bursts<=bursts+1;end
  end
  if(bdelay>0)begin bdelay<=bdelay-1;if(bdelay==1)bvalid<=1;end
  if(bvalid&&bready)bvalid<=0;
  if(ticks>2500000)$fatal(1,"capture/window timeout");
 end
 integer file_out;
 initial begin
  repeat(10)@(negedge clk);rst_n=1;
  wait(done);@(negedge clk);
  if(done_error||done_frame!=0||done_config!=7||done_session!=3||done_first!=0||bursts!=768)$fatal(1,"descriptor/commit mismatch");
  repeat(10)begin @(negedge clk);if(!done||!occupied[release_bank])$fatal(1,"lease changed under stall");end
  file_out=$fopen("pcm_window.hex","w");
  for(integer c=0;c<6;c=c+1)for(integer n=0;n<2048;n=n+1)begin
   if(memory[1024+c*2048+n]!={{8{pattern(n+1,c)[23]}},pattern(n+1,c)})$fatal(1,"planar PCM mismatch c%0d n%0d",c,n);
   $fdisplay(file_out,"%08x",memory[1024+c*2048+n]);checks=checks+1;
  end
  $fclose(file_out);
  if(missed||gaps||bad_release||overflow||fault)$fatal(1,"unexpected capture fault");
  done_ready=1;@(negedge clk);done_ready=0;repeat(2)@(negedge clk);
  if(occupied!=0)$fatal(1,"lease not released");
  $display("REAL_I2S_CDC_PLANAR_DMA_PASS checks=%0d bursts=%0d samples=%0d",checks,bursts,samples);$finish;
 end
endmodule
