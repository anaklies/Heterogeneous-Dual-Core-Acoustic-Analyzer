`timescale 1ns/1ps
// Bounded AXI harness, using the unmodified production HLS RTL.
module tb_stream_rtl;
 reg clk=0;always #10 clk=~clk;reg rst_n=0;
 wire av,wv,wl,bready,arv,rr;wire [31:0] aa,wd,ara;wire [7:0] al,arl;wire [3:0] ws;
 wire arready,awready,wready;reg bv=0,rv=0,rl=0;reg [31:0] rd=0;
 reg [31:0] mem[0:32767];reg wa=0,ra=0;reg [31:0] wp=0,rp=0;reg [8:0] left=0;
 reg cav=0,cwv=0,cbready=0,carv=0,crready=0;reg [6:0] ca=0,cara=0;reg [31:0] cd=0;
 wire cawr,cwr,cbv,carr,crv;wire [31:0] crd;wire [1:0] cbr,crresp;
 integer cycles=0,reads=0,writes=0,start_cycle=0,finish_cycle=0,f;
 assign awready=!wa&&!bv;assign wready=wa&&!bv&&(cycles%4!=0);assign arready=!ra&&!rv;
 stream_fft2048 dut(.ap_clk(clk),.ap_rst_n(rst_n),
 .m_axi_memory_AWVALID(av),.m_axi_memory_AWREADY(awready),.m_axi_memory_AWADDR(aa),.m_axi_memory_AWLEN(al),
 .m_axi_memory_WVALID(wv),.m_axi_memory_WREADY(wready),.m_axi_memory_WDATA(wd),.m_axi_memory_WSTRB(ws),.m_axi_memory_WLAST(wl),
 .m_axi_memory_BVALID(bv),.m_axi_memory_BREADY(bready),.m_axi_memory_BRESP(2'b0),.m_axi_memory_BID(1'b0),.m_axi_memory_BUSER(1'b0),
 .m_axi_memory_ARVALID(arv),.m_axi_memory_ARREADY(arready),.m_axi_memory_ARADDR(ara),.m_axi_memory_ARLEN(arl),
 .m_axi_memory_RVALID(rv),.m_axi_memory_RREADY(rr),.m_axi_memory_RDATA(rd),.m_axi_memory_RLAST(rl),.m_axi_memory_RRESP(2'b0),.m_axi_memory_RID(1'b0),.m_axi_memory_RUSER(1'b0),
 .s_axi_control_AWVALID(cav),.s_axi_control_AWREADY(cawr),.s_axi_control_AWADDR(ca),
 .s_axi_control_WVALID(cwv),.s_axi_control_WREADY(cwr),.s_axi_control_WDATA(cd),.s_axi_control_WSTRB(4'hf),
 .s_axi_control_BVALID(cbv),.s_axi_control_BREADY(cbready),.s_axi_control_BRESP(cbr),
 .s_axi_control_ARVALID(carv),.s_axi_control_ARREADY(carr),.s_axi_control_ARADDR(cara),
 .s_axi_control_RVALID(crv),.s_axi_control_RREADY(crready),.s_axi_control_RDATA(crd),.s_axi_control_RRESP(crresp));
 always @(posedge clk)begin
  cycles<=cycles+1;
  if(rst_n)begin
   if(av&&awready)begin if(aa[1:0]||aa>=131072)$fatal(1,"write range");wa<=1;wp<=aa>>2;end
   if(wv&&wready)begin
    for(integer j=0;j<4;j=j+1)if(ws[j])mem[wp][j*8+:8]<=wd[j*8+:8];
    wp<=wp+1;writes<=writes+1;if(wl)begin wa<=0;bv<=1;end
   end
   if(bv&&bready)bv<=0;
   if(arv&&arready)begin if(ara[1:0]||ara>=131072)$fatal(1,"read range");ra<=1;rp<=ara>>2;left<=arl+1;end
   if(ra&&!rv)begin rv<=1;rd<=mem[rp];rl<=left==1;end
   if(rv&&rr)begin rv<=0;reads<=reads+1;if(left==1)ra<=0;else begin rp<=rp+1;left<=left-1;end end
  end
  if(cycles>500000)$fatal(1,"bounded FFT timeout state=%h reads=%d writes=%d",dut.ap_CS_fsm,reads,writes);
 end
 task write_ctl(input [6:0] a,input [31:0] d);
  reg x,y;
  begin @(negedge clk);ca=a;cd=d;cav=1;cwv=1;
   while(cav||cwv)begin @(posedge clk);x=cawr;y=cwr;@(negedge clk);if(x)cav=0;if(y)cwv=0;end
   cbready=1;while(!cbv)@(negedge clk);if(cbr)$fatal(1,"control BRESP");@(negedge clk);cbready=0;
  end
 endtask
 task read_ctl(input [6:0] a,output [31:0] value);
  begin @(negedge clk);cara=a;carv=1;@(posedge clk);while(!carr)@(posedge clk);
   @(negedge clk);carv=0;crready=1;while(!crv)@(negedge clk);value=crd;if(crresp)$fatal(1,"control RRESP");@(negedge clk);crready=0;
  end
 endtask
 reg [31:0] status;integer polls;
 initial begin
  for(integer i=0;i<32768;i=i+1)mem[i]=0;
  repeat(5)@(negedge clk);rst_n=1;
  mem[42]=32'h7fc00000;
  write_ctl('h10,0);write_ctl('h18,32768);write_ctl('h20,32);write_ctl('h28,20000);write_ctl('h30,2);write_ctl('h38,1);write_ctl('h40,32'h473b8000);
  write_ctl(0,1);status=0;
  while(!status[1])begin repeat(40)@(negedge clk);read_ctl(0,status);end
  read_ctl('h48,status);if(status!=3||writes!=0)$fatal(1,"invalid complex frame not safely rejected");
  $display("INVALID_COMPLEX_REJECTED_WITHOUT_RESET");
  $readmemh("C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/tests/pcm_window.hex",mem,32,12319);
  write_ctl('h10,0);write_ctl('h18,32768);write_ctl('h20,32);write_ctl('h28,20000);write_ctl('h30,1);write_ctl('h38,3);write_ctl('h40,32'h473b8000);
  start_cycle=cycles;write_ctl(0,1);status=0;polls=0;
  while(!status[1])begin repeat(40)@(negedge clk);read_ctl(0,status);polls=polls+1;end
  finish_cycle=cycles;read_ctl('h48,status);if(status)$fatal(1,"FFT status=%h",status);
  if(wa||ra||rv||bv)$fatal(1,"completion before DMA drained");
  f=$fopen("C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/tests/actual_fft.hex","w");
  for(integer i=0;i<7179;i=i+1)$fdisplay(f,"%08h",mem[20000+i]);$fclose(f);
  $display("ACTUAL_FFT_RTL_DONE cycles=%0d reads=%0d writes=%0d polls=%0d",finish_cycle-start_cycle,reads,writes,polls);$finish;
 end
endmodule
