`timescale 1ns/1ps
// Bounded AXI harness, using the unmodified production HLS RTL.
module tb_scalar_rtl;
 reg clk=0;always #10 clk=~clk;reg rst_n=0;
 wire av,wv,wl,bready,arv,rr;wire [31:0] aa,wd,ara;wire [7:0] al,arl;wire [3:0] ws;
 wire arready,awready,wready;reg bv=0,rv=0,rl=0;reg [31:0] rd=0;
 reg [31:0] mem[0:557055];reg wa=0,ra=0;reg [31:0] wp=0,rp=0;reg [8:0] left=0;
 reg cav=0,cwv=0,cbready=0,carv=0,crready=0;reg [6:0] ca=0,cara=0;reg [31:0] cd=0;
 wire cawr,cwr,cbv,carr,crv;wire [31:0] crd;wire [1:0] cbr,crresp;
 integer cycles=0,reads=0,writes=0,start_cycle=0,finish_cycle=0,f;
 assign awready=!wa&&!bv;assign wready=wa&&!bv&&(cycles%4!=0);assign arready=!ra&&!rv;
 scalar_engine dut(.ap_clk(clk),.ap_rst_n(rst_n),
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
   if(av&&awready)begin if(aa[1:0]||aa>=2228224)$fatal(1,"write range");wa<=1;wp<=aa>>2;end
   if(wv&&wready)begin
    for(integer j=0;j<4;j=j+1)if(ws[j])mem[wp][j*8+:8]<=wd[j*8+:8];
    wp<=wp+1;writes<=writes+1;if(wl)begin wa<=0;bv<=1;end
   end
   if(bv&&bready)bv<=0;
   if(arv&&arready)begin if(ara[1:0]||ara>=2228224)$fatal(1,"read range");ra<=1;rp<=ara>>2;left<=arl+1;end
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
 reg [31:0] status;integer jobs=0;integer B=524288,O=532480,C=524416;
 task instruction(input integer n,input[31:0]op,input[31:0]imm,input[31:0]target);
 begin mem[C+4*n]=op;mem[C+4*n+1]=imm;mem[C+4*n+2]=target;mem[C+4*n+3]=0;end endtask
 initial begin
 for(integer i=0;i<557056;i=i+1)mem[i]=0;
 mem[B]=32'h414c5531;mem[B+1]=1;mem[B+2]=C;mem[B+3]=21;mem[B+4]=B+2048;
 mem[B+5]=B+4096;mem[B+6]=16;mem[B+7]=O;mem[B+8]=32;mem[B+9]=5;mem[B+10]=2;mem[B+11]=3;mem[B+12]=7;mem[B+13]=1;mem[B+14]=44;
 mem[B+4096]=32'hff800000;
 instruction(0,14|(31<<8),0,0);
 instruction(1,20|(1<<8)|(31<<13),0,1);
 instruction(2,22|(1<<13),0,0);
 instruction(3,1|(1<<8),32'h34000000,0);
 instruction(4,6|(1<<18),0,0);
 instruction(5,3|(31<<13),0,1);
 instruction(6,1|(2<<8),32'h40800000,0);
 instruction(7,8|(3<<8)|(2<<13),0,0);
 instruction(8,9|(4<<8)|(3<<13),0,0);
 instruction(9,10|(5<<8)|(4<<13),0,0);
 instruction(10,7|(6<<8)|(5<<13)|(3<<18),0,0);
 instruction(11,3|(3<<8)|(31<<13),1,1);
 instruction(12,3|(4<<8)|(31<<13),2,1);
 instruction(13,3|(5<<8)|(31<<13),3,1);
 instruction(14,3|(6<<8)|(31<<13),4,1);
 instruction(15,26|(7<<8),0,0);
 instruction(16,21|(7<<8)|(31<<13),8,1);
 instruction(17,26|(7<<8),1,0);
 instruction(18,21|(7<<8)|(31<<13),9,1);
 instruction(19,26|(7<<8),2,0);
 // Last checkpoint then final STORE/END in separate chunk.
 instruction(20,21|(7<<8)|(31<<13),10,1);
 instruction(21,0,0,0);mem[B+3]=22;
 repeat(5)@(negedge clk);rst_n=1;
 write_ctl('h10,0);write_ctl('h18,B);write_ctl('h20,557056);write_ctl('h28,0);write_ctl('h30,3);write_ctl('h38,7);
 write_ctl('h40,3219);write_ctl('h48,32'hffffff00);write_ctl('h50,18);
 start_cycle=cycles;
 status=0;
 while(!status[31])begin
 write_ctl(0,1);status=0;
 while(!status[1])begin repeat(30)@(negedge clk);read_ctl(0,status);end
 read_ctl('h58,status);if(status[7:0]!=0)$fatal(1,"scalar status=%h",status);
 jobs=jobs+1;if(jobs>8)$fatal(1,"context never completed");
 end
 if(wa||ra||rv||bv)$fatal(1,"completion before DMA fence");
 if(mem[O-16]!=32'h52534c54||mem[O-15]!=22||mem[O-14]!=3||mem[O-13]!=7||mem[O-10]!=3219||mem[O-9]!=32'hffffff00||mem[O-8]!=18||mem[O-2]!=1)$fatal(1,"publication metadata/fence mismatch");
 if(mem[O]!=32'hbf800000||mem[O+1]!=32'h40000000||mem[O+8]!=3219||mem[O+9]!=32'hffffff00||mem[O+10]!=18)$fatal(1,"math or metadata mismatch");
 f=$fopen("C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/tests/actual_scalar.hex","w");for(integer i=0;i<11;i=i+1)$fdisplay(f,"%08h",mem[O+i]);$fclose(f);
 $display("ACTUAL_SCALAR_RTL_DONE jobs=%0d cycles=%0d reads=%0d writes=%0d",jobs,cycles-start_cycle,reads,writes);$finish;
 end
endmodule
