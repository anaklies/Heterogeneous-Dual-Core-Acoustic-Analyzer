`timescale 1ns/1ps
// Read real FFT bin powers while scheduler retains the source slot.
module fft_event_features_reference #(parameter TIMEOUT=500000)(
 input wire clk,rst_n,frame_valid,input wire [31:0] frame_base,
 input wire [63:0] frame_last,input wire [7:0] band_mask,input wire [255:0] band_edges,
 output wire done_valid,input wire done_ready,output reg feature_valid,
 output reg [191:0] channel_power,output reg [255:0] band_power,output reg [63:0] timestamp,
 output reg fault,output reg [31:0] araddr,output wire arvalid,input wire arready,
 input wire [31:0] rdata,input wire [1:0] rresp,input wire rvalid,rlast,output wire rready
);
 localparam IDLE=0,ADDRESS=1,RESPONSE=2,DONE=3,FOLD=4;
 reg [2:0] state;reg [31:0] base,age;reg [2:0] channel;reg [10:0] bin;
 reg [2:0] band_index;reg [7:0] mask;reg [255:0] edges;reg [63:0] total,bands[0:7];
 integer i;reg [32:0] converted;reg [63:0] final_power,final_band;
 function automatic [32:0] q30(input [31:0] fp);
  reg [31:0] v;reg [7:0] e;
  begin e=fp[30:23];v={1'b1,fp[22:0]};
   if(fp[31]||e==255)q30={1'b1,32'b0};
   else if(e<97)q30=0;
   else if(e>128)q30={1'b1,32'hffffffff};
   else begin if(e>=120)v=v<<(e[3:0]-4'd8);else v=v>>(5'd24-e[4:0]);
    q30={1'b0,v};end
  end
 endfunction
 assign arvalid=state==ADDRESS;assign rready=state==RESPONSE;assign done_valid=state==DONE;
 always @(posedge clk)begin
  if(!rst_n)begin state<=IDLE;band_index<=0;base<=0;age<=0;channel<=0;bin<=0;mask<=0;edges<=0;total<=0;araddr<=0;feature_valid<=0;channel_power<=0;band_power<=0;timestamp<=0;fault<=0;for(i=0;i<8;i=i+1)bands[i]<=0;end
  else begin
   if(state==ADDRESS||state==RESPONSE)begin if(age<TIMEOUT)age<=age+1;else begin fault<=1;feature_valid<=0;end end
   case(state)
    IDLE:if(frame_valid)begin
     state<=ADDRESS;base<=frame_base;araddr<=frame_base+4098*4;age<=0;channel<=0;bin<=0;mask<=band_mask;edges<=band_edges;total<=0;timestamp<=frame_last;feature_valid<=1;
     for(i=0;i<8;i=i+1)begin bands[i]<=0;if(band_mask[i]&&(band_edges[32*i+:16]>=band_edges[32*i+16+:16]||band_edges[32*i+16+:16]>1025))begin feature_valid<=0;fault<=1;end end
    end
    ADDRESS:if(arready)begin state<=RESPONSE;age<=0;end
    RESPONSE:if(rvalid)begin
     age<=0;
     if(rresp!=0||!rlast)begin fault<=1;feature_valid<=0;state<=DONE;end
     else begin
      converted=q30(rdata);if(converted[32])begin fault<=1;feature_valid<=0;end
      final_power=total+converted[31:0];
      for(i=0;i<8;i=i+1)begin
       final_band=bands[i]+((mask[i]&&bin>=edges[32*i+:16]&&bin<edges[32*i+16+:16])?{32'b0,converted[31:0]}:64'b0);
       bands[i]<=final_band;

      end
      if(bin==1024)begin
       channel_power[channel*32+:32]<=final_power>64'hffffffff ? 32'hffffffff : final_power[31:0];
       if(final_power>64'hffffffff)begin feature_valid<=0;fault<=1;end
       total<=0;bin<=0;
       if(channel==5)begin state<=FOLD;band_index<=0;end
       else begin channel<=channel+1;araddr<=base+(channel+1)*32768+4098*4;state<=ADDRESS;end
      end else begin total<=final_power;bin<=bin+1;araddr<=araddr+12;state<=ADDRESS;end
     end
    end
    FOLD:begin
     final_band=bands[band_index];
     if(final_band>64'h5fffffffa)begin band_power[32*band_index+:32]<=32'hffffffff;feature_valid<=0;fault<=1;end
     else band_power[32*band_index+:32]<=(final_band[34:0]+35'd3)/35'd6;
     if(band_index==7)state<=DONE;else band_index<=band_index+1;
    end
    DONE:if(done_ready)state<=IDLE;
   endcase
  end
 end
endmodule


