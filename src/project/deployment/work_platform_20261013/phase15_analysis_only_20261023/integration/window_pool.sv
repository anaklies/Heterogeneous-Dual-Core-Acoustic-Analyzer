`timescale 1ns/1ps
// Copy tagged capture RAM into one of two immutable banks. No AXI stalls affect
// the copy. Data overwritten before a read is rejected, never published.
module window_pool #(
 parameter integer N=2048,HOP=512
)(
 input wire clk,rst_n,pcm_valid,
 input wire [143:0] pcm,
 input wire [63:0] sample_id,
 input wire [31:0] config_version,session_id,
 output wire window_valid,input wire window_ready,
 output wire window_bank,
 output wire [31:0] window_frame,window_config,window_session,
 output wire [63:0] window_first,
 input wire release_valid,release_bank,
 input wire [31:0] release_frame,
 input wire read_bank,
 input wire [$clog2(N)-1:0] read_index,
 output wire [143:0] read_data,
 output reg [31:0] missed_windows,gaps,bad_release,
 output wire [1:0] occupied
);
 localparam A=$clog2(N);
 (* ram_style="block" *) reg [207:0] capture[0:N-1];
 (* ram_style="block" *) reg [143:0] bank0[0:N-1],bank1[0:N-1];
 reg [1:0] busy,ready,leased;
 reg [31:0] frames[0:1],configs[0:1],sessions[0:1];
 reg [63:0] starts[0:1];
 reg [63:0] last_id,copy_first;
 reg have_id;
 reg [A:0] warm,hop_count;
 reg copying,phase,target_bank;
 reg [A-1:0] index;
 reg [31:0] frame_counter;
 reg [207:0] capture_read,bypass_data;
 reg bypass_valid,read_bank_d;
 reg [143:0] bank0_read,bank1_read;
 wire [207:0] copy_data=bypass_valid?bypass_data:capture_read;
 wire take=window_valid&&window_ready;
 wire select_bank=ready[0]&&ready[1] ? frames[1]<frames[0] : !ready[0];
 wire [A-1:0] copy_address=copy_first[A-1:0]+index;
 wire contiguous=!have_id||sample_id==last_id+1'b1;
 assign window_valid=|ready;assign window_bank=select_bank;
 assign window_frame=frames[select_bank];assign window_config=configs[select_bank];
 assign window_session=sessions[select_bank];assign window_first=starts[select_bank];assign occupied=busy;
 initial if(N<4||(N&(N-1))||HOP<1||HOP>N)$fatal(1,"invalid window geometry");
 // Keep memory read registers separate from bypass/bank selection muxes.
 // This is a true synchronous RAM template; no reset applies to RAM contents.
 assign read_data=read_bank_d?bank1_read:bank0_read;
 always @(posedge clk)begin
  if(pcm_valid)capture[sample_id[A-1:0]]<={sample_id,pcm};
  capture_read<=capture[copy_address];
  bypass_valid<=pcm_valid&&sample_id[A-1:0]==copy_address;
  bypass_data<={sample_id,pcm};
  bank0_read<=bank0[read_index];bank1_read<=bank1[read_index];read_bank_d<=read_bank;
  if(rst_n&&copying&&phase&&copy_data[207:144]==copy_first+index)begin
   if(target_bank)bank1[index]<=copy_data[143:0];else bank0[index]<=copy_data[143:0];
  end
 end
 always @(posedge clk)begin
  if(!rst_n)begin
   busy<=0;ready<=0;leased<=0;last_id<=0;have_id<=0;warm<=0;hop_count<=0;
   copying<=0;phase<=0;target_bank<=0;index<=0;copy_first<=0;frame_counter<=0;
   missed_windows<=0;gaps<=0;bad_release<=0;
   frames[0]<=0;frames[1]<=0;starts[0]<=0;starts[1]<=0;
   configs[0]<=0;configs[1]<=0;sessions[0]<=0;sessions[1]<=0;
  end else begin
   if(take)begin ready[select_bank]<=0;leased[select_bank]<=1;end
   if(release_valid)begin
    if(leased[release_bank]&&frames[release_bank]==release_frame)begin busy[release_bank]<=0;leased[release_bank]<=0;end
    else if(bad_release!=32'hffffffff)bad_release<=bad_release+1;
   end
   if(pcm_valid)begin
    last_id<=sample_id;have_id<=1;
    if(!contiguous)begin warm<=1;hop_count<=1;if(gaps!=32'hffffffff)gaps<=gaps+1;end
    else begin
     if(warm<N)warm<=warm+1'b1;
     if(hop_count==HOP-1)begin
      hop_count<=0;
      if(warm>=N-1)begin
       if(copying||(&busy)||frame_counter==32'hffffffff)begin if(missed_windows!=32'hffffffff)missed_windows<=missed_windows+1;end
       else begin
        copying<=1;phase<=0;index<=0;target_bank<=busy[0];busy[busy[0]]<=1;
        frames[busy[0]]<=frame_counter;frame_counter<=frame_counter+1;
        starts[busy[0]]<=sample_id+1-N;copy_first<=sample_id+1-N;
        configs[busy[0]]<=config_version;sessions[busy[0]]<=session_id;
       end
      end
     end else hop_count<=hop_count+1'b1;
    end
   end
   if(copying)begin
    if(!phase)phase<=1;
    else if(copy_data[207:144]!=copy_first+index)begin
     copying<=0;busy[target_bank]<=0;if(missed_windows!=32'hffffffff)missed_windows<=missed_windows+1;
    end else begin
     if(index==N-1)begin copying<=0;ready[target_bank]<=1;end
     else begin index<=index+1'b1;phase<=0;end
    end
   end
  end
 end
endmodule
