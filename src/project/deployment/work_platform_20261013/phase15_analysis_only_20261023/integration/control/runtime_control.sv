`timescale 1ns/1ps
// Runtime control boundary. One controller, independent AW/W and epoch snapshots.
module runtime_control #(parameter [63:0] CAPABILITIES=0,parameter CFG_WORDS=16,parameter PROTOCOL=2)(
 input wire clk,rst_n,
 input wire [11:0] awaddr,input wire awvalid,output wire awready,
 input wire [31:0] wdata,input wire [3:0] wstrb,input wire wvalid,output wire wready,
 output reg [1:0] bresp,output reg bvalid,input wire bready,
 input wire [11:0] araddr,input wire arvalid,output wire arready,
 output reg [31:0] rdata,output reg [1:0] rresp,output reg rvalid,input wire rready,
 output reg cfg_valid,input wire cfg_ready,cfg_applied,cfg_rejected,
 output reg [CFG_WORDS*32-1:0] cfg_payload,
 input wire result_valid,input wire [1023:0] result_words,
 input wire [511:0] raw_cursor_words,input wire [1023:0] fft_slot_words,
 input wire [31:0] live_faults,active_config,
 input wire clip_valid,clip_bank_in,input wire [511:0] clip_words,
 output wire clip_ready,output reg clip_release,clip_bank,output reg [31:0] clip_id,
 output wire irq
);
 reg ap,wp;reg [11:0] a;reg [31:0] d;reg [3:0] st;
 reg [31:0] shadow[0:CFG_WORDS-1],snapshot[0:31],epoch,faults;
 reg [511:0] clips[0:1];reg [1:0] clip_mask;
 reg pending,result_irq,cfg_irq;integer i,j;reg [31:0] merged;
 assign awready=!ap&&!bvalid;assign wready=!wp&&!bvalid;
 assign clip_ready=!clip_mask[clip_bank_in];
 assign arready=!rvalid||rready;assign irq=result_irq||cfg_irq||(|faults)||(|clip_mask);
 always @(posedge clk)begin
  if(!rst_n)begin
   ap<=0;wp<=0;a<=0;d<=0;st<=0;bresp<=0;bvalid<=0;rdata<=0;rresp<=0;rvalid<=0;
   clips[0]<=0;clips[1]<=0;clip_mask<=0;clip_release<=0;clip_bank<=0;clip_id<=0;
   cfg_valid<=0;cfg_payload<=0;pending<=0;result_irq<=0;cfg_irq<=0;epoch<=0;faults<=0;
   for(i=0;i<CFG_WORDS;i=i+1)shadow[i]<=0;
   for(i=0;i<32;i=i+1)snapshot[i]<=0;
  end else begin
   clip_release<=0;

   if(bvalid&&bready)bvalid<=0;if(rvalid&&rready)rvalid<=0;
   if(awvalid&&awready)begin ap<=1;a<=awaddr;end
   if(wvalid&&wready)begin wp<=1;d<=wdata;st<=wstrb;end
   if(cfg_valid&&cfg_ready)cfg_valid<=0;
   if(pending&&(cfg_applied||cfg_rejected))begin pending<=0;cfg_irq<=1;end
   if(ap&&wp&&!bvalid)begin
    ap<=0;wp<=0;bvalid<=1;bresp<=0;
    if(a[1:0]!=0)bresp<=2;
    else if(a>=12'h040&&a<12'h040+4*CFG_WORDS)begin
     merged=shadow[(a-12'h040)>>2];for(j=0;j<4;j=j+1)if(st[j])merged[j*8+:8]=d[j*8+:8];shadow[(a-12'h040)>>2]<=merged;
    end else if(a==12'h020&&st==15&&d==1)begin
     if(pending)bresp<=2;
     else begin
      for(i=0;i<CFG_WORDS;i=i+1)cfg_payload[i*32+:32]<=shadow[i];
      cfg_valid<=1;pending<=1;cfg_irq<=0;
     end
    end else if(a==12'h02c)begin
     merged=clip_id;for(j=0;j<4;j=j+1)if(st[j])merged[8*j+:8]=d[8*j+:8];clip_id<=merged;
    end else if(a==12'h028&&st==15&&d[31:2]==0&&d[0])begin
     if(clip_mask[d[1]]&&clips[d[1]][31:0]==clip_id)begin clip_release<=1;clip_bank<=d[1];clip_mask[d[1]]<=0;end
     else bresp<=2;
    end else if(a==12'h024)begin
     if(st[0]&&d[0])result_irq<=0;if(st[0]&&d[1])cfg_irq<=0;

    end else bresp<=2;
   end
   if(arvalid&&arready)begin
    rvalid<=1;rresp<=0;rdata<=0;
    if(araddr[1:0]!=0)rresp<=2;
    else if(araddr>=12'h200&&araddr<12'h280)rdata<=clips[araddr[6]][araddr[5:2]*32+:32];
    else if(araddr>=12'h400&&araddr<12'h480)rdata<=fft_slot_words[((araddr-12'h400)>>2)*32+:32];
    else if(araddr>=12'h300&&araddr<12'h340)rdata<=raw_cursor_words[((araddr-12'h300)>>2)*32+:32];
    else if(araddr>=12'h100&&araddr<12'h180)rdata<=snapshot[(araddr-12'h100)>>2];
    else if(araddr>=12'h040&&araddr<12'h040+4*CFG_WORDS)rdata<=shadow[(araddr-12'h040)>>2];
    else case(araddr)
     'h000:rdata<=32'h534d4132;
     'h004:rdata<=PROTOCOL;
     'h008:rdata<=32'h82000001;
     'h00c:rdata<=CAPABILITIES[31:0];'h010:rdata<=CAPABILITIES[63:32];
     'h014:rdata<=faults;'h018:rdata<=epoch;'h01c:rdata<=active_config;
     'h030:rdata<={30'b0,clip_mask};
     'h020:rdata<={29'b0,cfg_irq,result_irq,pending};
     default:rresp<=2;
    endcase
   end
   if(pending&&(cfg_applied||cfg_rejected))cfg_irq<=1; // completion wins W1C
   faults<=((ap&&wp&&!bvalid&&a==12'h024&&st[0]&&d[2])?32'b0:faults)|live_faults|
    ((pending&&cfg_rejected)?32'h40000000:32'b0)|((result_valid&&epoch==32'hffffffff)?32'h80000000:32'b0);
   if(clip_valid&&clip_ready)begin clips[clip_bank_in]<=clip_words;clip_mask[clip_bank_in]<=1;end
   if(result_valid)begin
    if(epoch==32'hffffffff)begin end
    else begin for(i=0;i<32;i=i+1)snapshot[i]<=result_words[i*32+:32];epoch<=epoch+1;result_irq<=1;end
   end
  end
 end
endmodule
