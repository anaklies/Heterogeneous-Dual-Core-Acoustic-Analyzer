`timescale 1ns/1ps
module sample_cdc #(parameter integer DEPTH=16)(
 input wire wr_clk,wr_rst_n,wr_valid,
 input wire [207:0] wr_data,
 output reg overflow_sticky,
 input wire rd_clk,rd_rst_n,
 output reg rd_valid,
 input wire rd_ready,
 output reg [207:0] rd_data
);
 localparam A=$clog2(DEPTH);
 (* ram_style="distributed" *) reg [207:0] memory[0:DEPTH-1];
 reg [A:0] wp,wg,rp,rg;
 (* ASYNC_REG="TRUE" *) reg [A:0] rg1,rg2,wg1,wg2;
 reg full,empty;
 wire push=wr_valid&&!full;
 wire pop=(!rd_valid||rd_ready)&&!empty;
 wire [A:0] wn=wp+push,rn=rp+pop;
 wire [A:0] wgn=(wn>>1)^wn,rgn=(rn>>1)^rn;
 initial if(DEPTH<4||(DEPTH&(DEPTH-1)))$fatal(1,"CDC depth must be power-of-two >=4");
 always @(posedge wr_clk)if(wr_rst_n&&push)memory[wp[A-1:0]]<=wr_data;
 always @(posedge wr_clk or negedge wr_rst_n)begin
  if(!wr_rst_n)begin wp<=0;wg<=0;rg1<=0;rg2<=0;full<=0;overflow_sticky<=0;end
  else begin
   rg1<=rg;rg2<=rg1;
   if(wr_valid&&full)overflow_sticky<=1;
   wp<=wn;wg<=wgn;full<=wgn=={~rg2[A:A-1],rg2[A-2:0]};
  end
 end
 always @(posedge rd_clk or negedge rd_rst_n)begin
  if(!rd_rst_n)begin rp<=0;rg<=0;wg1<=0;wg2<=0;empty<=1;rd_valid<=0;rd_data<=0;end
  else begin
   wg1<=wg;wg2<=wg1;
   if(pop)begin rd_data<=memory[rp[A-1:0]];rd_valid<=1;end
   else if(rd_ready)rd_valid<=0;
   rp<=rn;rg<=rgn;empty<=rgn==wg2;
  end
 end
endmodule
