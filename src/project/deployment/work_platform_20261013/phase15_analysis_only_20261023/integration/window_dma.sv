`timescale 1ns/1ps
// Export one leased immutable bank as6 planar signed32 channel arrays.
module window_dma #(parameter integer N=2048,TIMEOUT=500000)(
 input wire clk,rst_n,recover_ack,
 input wire window_valid,window_bank,
 output wire window_ready,
 input wire [31:0] window_frame,window_config,window_session,
 input wire [63:0] window_first,
 input wire slot_valid,
 input wire [1:0] slot_id,
 input wire [31:0] slot_address,
 output wire slot_take,
 output wire read_bank,
 output wire [$clog2(N)-1:0] read_index,
 input wire [143:0] read_data,
 output wire release_valid,release_bank,
 output wire [31:0] release_frame,
 output wire done_valid,input wire done_ready,
 output reg [1:0] done_slot,
 output reg [31:0] done_frame,done_config,done_session,done_error,
 output reg [63:0] done_first,
 output reg fault_latched,
 output wire [31:0] awaddr,output wire [7:0] awlen,
 output wire [2:0] awsize,output wire [1:0] awburst,
 output wire awvalid,input wire awready,
 output wire [31:0] wdata,output wire [3:0] wstrb,
 output wire wlast,wvalid,input wire wready,
 input wire [1:0] bresp,input wire bvalid,output wire bready
);
 localparam A=$clog2(N);
 localparam IDLE=0,FILL_ADDR=1,FILL_DATA=2,AW=3,W=4,B=5,DONE=6;
 reg [2:0] state;
 reg bank;
 reg [31:0] base,position,age;
 reg [4:0] fill;
 reg [3:0] beat;
 reg [31:0] line[0:15];
 wire [31:0] at=position+fill;
 wire [2:0] channel=at>>A;
 wire progress=(awvalid&&awready)||(wvalid&&wready)||(bvalid&&bready);
 wire timeout_now=state!=IDLE&&state!=DONE&&age>=TIMEOUT-1&&!progress;
 assign window_ready=state==IDLE&&slot_valid&&!fault_latched;
 assign slot_take=window_valid&&window_ready;
 assign read_bank=bank;assign read_index=at[A-1:0];
 assign awaddr=base+position*4;assign awlen=15;assign awsize=2;assign awburst=1;
 assign awvalid=state==AW;assign wvalid=state==W;assign wdata=line[beat];
 assign wstrb=15;assign wlast=beat==15;assign bready=state==B;
 assign done_valid=state==DONE;assign release_valid=done_valid&&done_ready;
 assign release_bank=bank;assign release_frame=done_frame;
 initial if(N<16||(N&(N-1))||TIMEOUT<1)$fatal(1,"invalid window DMA parameters");
 always @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;bank<=0;base<=0;position<=0;fill<=0;beat<=0;age<=0;fault_latched<=0;
   done_slot<=0;done_frame<=0;done_config<=0;done_session<=0;done_first<=0;done_error<=0;
  end else begin
   if(state==IDLE||state==DONE||progress)age<=0;else if(age!=32'hffffffff)age<=age+1;
   if(timeout_now)begin fault_latched<=1;done_error<=done_error|4;end
   case(state)
    IDLE:if(slot_take)begin
     bank<=window_bank;base<=slot_address;position<=0;fill<=0;done_slot<=slot_id;
     done_frame<=window_frame;done_config<=window_config;done_session<=window_session;done_first<=window_first;done_error<=0;
     if(slot_address[11:0]!=0||{1'b0,slot_address}+6*N*4>33'h100000000)begin done_error<=1;state<=DONE;end
     else state<=FILL_ADDR;
    end
    FILL_ADDR:if(done_error!=0||timeout_now)state<=DONE;else state<=FILL_DATA;
    FILL_DATA:begin
     line[fill]<= {{8{read_data[channel*24+23]}},read_data[channel*24+:24]};
     if(fill==15)begin fill<=0;state<=AW;end else begin fill<=fill+1;state<=FILL_ADDR;end
    end
    AW:if(awready)begin beat<=0;state<=W;end
    W:if(wready)begin if(beat==15)state<=B;else beat<=beat+1;end
    B:if(bvalid)begin
     if(bresp!=0)begin fault_latched<=1;done_error<=done_error|2;state<=DONE;end
     else if(done_error!=0||timeout_now||position+16>=6*N)state<=DONE;
     else begin position<=position+16;state<=FILL_ADDR;end
    end
    DONE:if(done_ready)state<=IDLE;
    default:begin fault_latched<=1;state<=DONE;done_error<=8;end
   endcase
   if(recover_ack&&state==IDLE)begin fault_latched<=0;done_error<=0;end
   else if(recover_ack&&(state==FILL_ADDR||state==FILL_DATA))begin fault_latched<=0;done_error<=done_error|8;state<=DONE;end
   else if(recover_ack&&state==DONE)fault_latched<=0;
  end
 end
endmodule
