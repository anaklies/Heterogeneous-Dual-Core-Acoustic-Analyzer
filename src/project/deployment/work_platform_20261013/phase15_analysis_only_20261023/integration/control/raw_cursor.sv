`timescale 1ns/1ps
// Read-only current-ring telemetry. This grants no permanent buffer lease.
module raw_cursor(
 input wire clk,rst_n,configured,record_arm,writer_enable,
 input wire [31:0] generation,base,bytes,next_offset,dropped,faults,session,config_version,
 input wire [63:0] last_sample,
 input wire [1:0] leased,
 output reg [511:0] words
);
 reg [31:0] observed_generation,observed_offset;
 reg [63:0] records;
 wire changed=generation==observed_generation&&next_offset!=observed_offset;
 wire [63:0] visible_records=generation!=observed_generation?64'd0:
                  (changed&&records!=64'hffffffffffffffff ? records+1'b1:records);
 always @(posedge clk)begin
  if(!rst_n)begin observed_generation<=0;observed_offset<=0;records<=0;end
  else begin
   observed_generation<=generation;observed_offset<=next_offset;
   if(generation!=observed_generation)records<=0;
   else if(changed&&records!=64'hffffffffffffffff)records<=records+1'b1;
  end
 end
 always @*begin
  words=0;words[0+:32]=32'h43555231;words[32+:32]=generation;
  words[64+:32]=base;words[96+:32]=bytes;words[128+:32]=next_offset;
  words[160+:64]=visible_records;words[224+:64]=last_sample;
  words[288+:32]=dropped;words[320+:32]=faults;
  words[352+:32]=session;words[384+:32]=config_version;
  words[416+:32]=32'h473b89c6;words[448+:32]=1;
  words[480+:32]={26'b0,(records==64'hffffffffffffffff),leased,writer_enable,record_arm,configured};
 end
endmodule

