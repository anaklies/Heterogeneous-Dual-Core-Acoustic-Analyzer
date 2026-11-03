`timescale 1ns/1ps
// P0 has priority. P1/P2 execute bounded backend chunks at job boundaries.
// Completed DDR output uses generation-checked snapshots, not unlimited leases.
module analysis_scheduler #(
 parameter integer WINDOW_CYCLES=533225,SCALAR_BUDGET=40000,
 parameter integer JOB_TIMEOUT=500000,PERIOD1=9600000,PERIOD2=52800000,PUBLISH_WINDOWS=9,FEATURES_ENABLED=0
)(
 input wire clk,rst_n,
 input wire cfg_valid,output wire cfg_ready,
 input wire [31:0] cfg_session,cfg_version,cfg_arena_base,cfg_arena_words,cfg_reserved_low,cfg_reserved_high,
 input wire [31:0] cfg_p1_descriptor,cfg_p2_descriptor,
 input wire [3:0] cfg_p1_last_index,input wire [31:0] cfg_p1_stride,input wire cfg_p2_oneshot,
 input wire cfg_p1_enable,cfg_p2_enable,cfg_pause_p1_when_p2,
 output reg cfg_applied,cfg_rejected,
 output reg [31:0] active_session,active_config,
 output wire slot_valid,output wire [1:0] slot_id,output wire [31:0] slot_address,
 input wire slot_take,
 input wire [31:0] taking_frame,taking_config,taking_session,
 input wire [63:0] taking_first,
 input wire fill_done,input wire [1:0] fill_slot,
 input wire [31:0] fill_frame,fill_config,fill_session,fill_error,
 output wire fill_ready,
 output wire command_valid,input wire command_ready,
 output reg [31:0] command_token,command_base,
 output reg [4:0] command_count,
 output reg [127:0] command_offsets,output reg [511:0] command_values,
 input wire completion_valid,input wire [31:0] completion_token,completion_error,completion_status,
 output wire completion_ready,
 output reg result_update,
 output reg [1:0] result_slot,
 output reg [31:0] result_frame,result_config,result_session,result_cycles,
 output reg [63:0] result_first,
 output reg [31:0] result_base,
 input wire result_ack,input wire [1:0] ack_slot,input wire [31:0] ack_frame,ack_session,
 output wire [3:0] snapshot_valid,
 output wire [1023:0] fft_slot_headers,
 output reg [31:0] overwritten_results,stale_completions,failed_frames,background_completions,canceled_contexts,input_timeouts,
 output reg [31:0] background_failures,output reg fault_latched,
 output wire feature_request,input wire feature_complete,
 output wire [31:0] feature_base,output wire [63:0] feature_last,
 input wire common_reset_ack
);
 localparam FREE=0,FILL=1,READY=2,RUN=3;
 localparam IDLE=0,ISSUE=1,WAIT=2,FEATURE=3;
 reg [1:0] slots[0:3],state,selected,kind;
 reg [31:0] frames[0:3],configs[0:3],sessions[0:3],ready_at[0:3];
 reg [63:0] firsts[0:3];
 reg [3:0] snapshots,unconsumed;
 reg [31:0] arena_base,arena_words,p1_desc,p2_desc,token_counter,clock_count,age,until_window,due1,due2,input_age;
 reg p2_once;reg configured,p1_enable,p2_enable,p1_running,p2_running,pause_p1,background_turn;
 reg [1:0] p1_source,p2_source,source_slot;
 reg have_source;
 reg p1_seen,p2_seen;reg [31:0] p1_last_frame,p2_last_frame;
 wire p1_source_fresh=have_source&&(!p1_seen||frames[source_slot]!=p1_last_frame);
 wire p2_source_fresh=have_source&&(!p2_seen||frames[source_slot]!=p2_last_frame);
 wire p1_eligible=p1_running||(due1==0&&p1_source_fresh);
 wire p2_eligible=p2_running||(due2==0&&p2_source_fresh);
 reg bg_transform,p1_fft,p2_fft;reg [31:0] p1_fft_spec,p2_fft_spec;
 reg [3:0] p1_index,p1_last;reg [31:0] p1_stride;
 wire [31:0] requested_stride=cfg_p1_stride==0?32'd24576:cfg_p1_stride;
 wire [63:0] p1_end={32'b0,cfg_p1_descriptor}+{32'b0,requested_stride}*cfg_p1_last_index+64;
 reg [2:0] channel;
 reg [3:0] publish_div;
 reg have_free,have_ready,have_fill;reg [1:0] free_slot,ready_slot;
 integer i;
 initial if(PUBLISH_WINDOWS<1||PUBLISH_WINDOWS>16)$fatal(1,"invalid publication divider");
 always @*begin
  have_free=0;have_ready=0;have_fill=0;free_slot=0;ready_slot=0;
  for(integer n=0;n<4;n=n+1)begin
   if(slots[n]==FREE&&!(p1_running&&p1_source==n)&&!(p2_running&&p2_source==n)&&!have_free)begin have_free=1;free_slot=n;end
   if(slots[n]==FILL)have_fill=1;
   if(slots[n]==READY&&(!have_ready||frames[n]<frames[ready_slot]))begin have_ready=1;ready_slot=n;end
  end
 end
 always @*begin
  have_source=0;source_slot=0;
  for(integer n=0;n<4;n=n+1)
   if(slots[n]==FREE&&snapshots[n]&&!(slot_take&&slot_valid&&free_slot==n)&&
      (!have_source||frames[n]>frames[source_slot]))begin have_source=1;source_slot=n;end
 end
 assign cfg_ready=state==IDLE&&!fault_latched&&!have_fill&&!common_reset_ack;
 assign slot_valid=configured&&have_free&&!fault_latched&&!cfg_valid&&!common_reset_ack;
 assign slot_id=free_slot;assign slot_address=arena_base+{free_slot,16'b0};
 assign fill_ready=1;
 assign completion_ready=1;
 assign command_valid=state==ISSUE&&!fault_latched&&age<JOB_TIMEOUT-1&&!common_reset_ack;
 assign snapshot_valid=snapshots;
 generate for(genvar h=0;h<4;h=h+1)begin:host_slot_headers
  assign fft_slot_headers[h*256+:32]={31'b0,snapshots[h]};
  assign fft_slot_headers[h*256+32+:32]=frames[h];
  assign fft_slot_headers[h*256+64+:32]=configs[h];
  assign fft_slot_headers[h*256+96+:32]=sessions[h];
  assign fft_slot_headers[h*256+128+:64]=firsts[h];
  assign fft_slot_headers[h*256+192+:32]=32'h100000+h*32'h40000;
  assign fft_slot_headers[h*256+224+:32]=1;
 end endgenerate
 assign feature_request=state==FEATURE&&!fault_latched&&age<JOB_TIMEOUT-1&&!common_reset_ack;
 assign feature_base=arena_base+32'h100000+{selected,18'b0};
 assign feature_last=firsts[selected]+2047;
 task argument(input integer n,input [31:0] value);
  begin command_offsets[n*8+:8]<=8'h10+n*8;command_values[n*32+:32]<=value;end
 endtask
 task fft_job(input [1:0] slot,input [2:0] ch);
  begin
   bg_transform<=0;command_base<=32'h44a40000;command_count<=7;
   argument(0,arena_base);argument(1,arena_words);
   argument(2,{slot,14'b0}+ch*2048);
   argument(3,32'h40000+{slot,16'b0}+ch*8192);
   argument(4,1);argument(5,3);argument(6,32'h473b89c6); // actual sample clock/1024, approx48009.78
   command_token<=token_counter;token_counter<=token_counter+1;age<=0;state<=ISSUE;
  end
 endtask
 task scalar_job(input [1:0] which,input [31:0] descriptor,input [1:0] source);
  begin
   bg_transform<=0;kind<=which;command_base<=32'h44a50000;command_count<=9;
   argument(0,arena_base);argument(1,descriptor+source*16);argument(2,arena_words);argument(3,{30'b0,source});argument(4,active_session);argument(5,active_config);argument(6,frames[source]);argument(7,firsts[source][31:0]);argument(8,firsts[source][63:32]);
   command_token<=token_counter;token_counter<=token_counter+1;age<=0;state<=ISSUE;
  end
 endtask
 task transform_job(input [1:0] which,input [31:0] spec);
  reg [31:0] base;
  begin
   base={10'b0,spec[27:18],12'b0};
   if(base<32'h80000||arena_words<16384||base>arena_words-16384)begin fault_latched<=1;state<=IDLE;end
   else begin
    kind<=which;bg_transform<=1;command_base<=32'h44a40000;command_count<=7;
    argument(0,arena_base);argument(1,arena_words);argument(2,base+4096);argument(3,base+8192);
    argument(4,2);argument(5,{30'b0,spec[29:28]});argument(6,32'h473b89c6);
    command_token<=token_counter;token_counter<=token_counter+1;age<=0;state<=ISSUE;
   end
  end
 endtask
 task publish_frame;
 begin
       slots[selected]<=FREE;snapshots[selected]<=1;unconsumed[selected]<=1;state<=IDLE;
       if(publish_div==PUBLISH_WINDOWS-1)begin
        publish_div<=0;result_update<=1;result_slot<=selected;result_frame<=frames[selected];result_config<=configs[selected];result_session<=sessions[selected];
        result_first<=firsts[selected];result_cycles<=clock_count-ready_at[selected];result_base<=arena_base+32'h100000+{selected,18'b0};
       end else publish_div<=publish_div+1;
 end
 endtask
 always @(posedge clk)begin
  if(!rst_n)begin
   bg_transform<=0;p1_fft<=0;p2_fft<=0;p1_fft_spec<=0;p2_fft_spec<=0;
   state<=IDLE;selected<=0;kind<=0;channel<=0;configured<=0;active_session<=0;active_config<=0;
   arena_base<=0;arena_words<=0;p1_desc<=0;p2_desc<=0;p1_enable<=0;p2_enable<=0;p1_running<=0;p2_running<=0;pause_p1<=0;background_turn<=0;
   p2_once<=0;p1_index<=0;p1_last<=0;p1_stride<=24576;p1_source<=0;p2_source<=0;p1_seen<=0;p2_seen<=0;p1_last_frame<=0;p2_last_frame<=0;
   token_counter<=1;clock_count<=0;age<=0;until_window<=WINDOW_CYCLES;due1<=0;due2<=0;input_age<=0;input_timeouts<=0;
   command_token<=0;command_base<=0;command_count<=0;command_offsets<=0;command_values<=0;
   result_update<=0;result_slot<=0;result_frame<=0;result_config<=0;result_session<=0;result_cycles<=0;result_first<=0;result_base<=0;
   snapshots<=0;unconsumed<=0;publish_div<=0;overwritten_results<=0;stale_completions<=0;failed_frames<=0;background_completions<=0;canceled_contexts<=0;
   background_failures<=0;fault_latched<=0;cfg_applied<=0;cfg_rejected<=0;
   for(i=0;i<4;i=i+1)begin slots[i]<=FREE;frames[i]<=0;configs[i]<=0;sessions[i]<=0;firsts[i]<=0;ready_at[i]<=0;end
  end else begin
   clock_count<=clock_count+1;result_update<=0;cfg_applied<=0;cfg_rejected<=0;
   if(until_window!=0)until_window<=until_window-1;
   if(due1!=0)due1<=due1-1;if(due2!=0)due2<=due2-1;
   if(configured&&input_age!=32'hffffffff)input_age<=input_age+1;
   if(configured&&!cfg_valid&&!fault_latched&&input_age>=WINDOW_CYCLES*8)begin fault_latched<=1;input_timeouts<=input_timeouts+1;end
   if(state!=IDLE&&age!=32'hffffffff)age<=age+1;
   if(state!=IDLE&&age>=JOB_TIMEOUT-1)begin
    fault_latched<=1;
    // An unaccepted command has no bus transaction to drain. Never start it late.
    if(state==ISSUE)begin state<=IDLE;if(kind==0)begin slots[selected]<=FREE;failed_frames<=failed_frames+1;end end
   end
   if(token_counter==32'hffffffff)fault_latched<=1;
   if(slot_take&&slot_valid)begin
    slots[free_slot]<=FILL;frames[free_slot]<=taking_frame;configs[free_slot]<=taking_config;sessions[free_slot]<=taking_session;firsts[free_slot]<=taking_first;
    snapshots[free_slot]<=0;
    if(unconsumed[free_slot])begin overwritten_results<=overwritten_results+1;unconsumed[free_slot]<=0;end
   end
   if(fill_done)begin
    input_age<=0;
    if(slots[fill_slot]!=FILL||frames[fill_slot]!=fill_frame||configs[fill_slot]!=fill_config||sessions[fill_slot]!=fill_session)stale_completions<=stale_completions+1;
    else if(fill_error!=0||fill_config!=active_config||fill_session!=active_session)begin slots[fill_slot]<=FREE;failed_frames<=failed_frames+1;end
    else begin slots[fill_slot]<=READY;ready_at[fill_slot]<=clock_count;until_window<=WINDOW_CYCLES;end
   end
   if(result_ack&&snapshots[ack_slot]&&frames[ack_slot]==ack_frame&&sessions[ack_slot]==ack_session)unconsumed[ack_slot]<=0;
   if(cfg_valid&&cfg_ready)begin
    if(cfg_arena_base[11:0]!=0||cfg_arena_words<32'h80000||cfg_arena_words>32'h400000||cfg_arena_base<cfg_reserved_low||
       cfg_reserved_high<=cfg_reserved_low||cfg_reserved_high>32'h40000000||
       {1'b0,cfg_arena_base}+{1'b0,cfg_arena_words,2'b0}>{3'b0,cfg_reserved_high}||
       {1'b0,cfg_arena_base}+{1'b0,cfg_arena_words,2'b0}>35'h040000000||
       (cfg_p1_enable&&(cfg_p1_descriptor<32'h80000||cfg_p1_descriptor>cfg_arena_words-64||requested_stride<64||requested_stride[3:0]!=0||p1_end>cfg_arena_words))||
       (cfg_p2_enable&&(cfg_p2_descriptor<32'h80000||cfg_p2_descriptor>cfg_arena_words-64)))cfg_rejected<=1;
    else begin
     // Apply only between commands. READY snapshots from old config are discarded.
     active_session<=cfg_session;active_config<=cfg_version;arena_base<=cfg_arena_base;arena_words<=cfg_arena_words;
     p2_once<=cfg_p2_oneshot;p1_index<=0;p1_last<=cfg_p1_last_index;p1_stride<=requested_stride;p1_desc<=cfg_p1_descriptor;p2_desc<=cfg_p2_descriptor;p1_enable<=cfg_p1_enable;p2_enable<=cfg_p2_enable;pause_p1<=cfg_pause_p1_when_p2;configured<=1;cfg_applied<=1;
     if(p1_running||p2_running)canceled_contexts<=canceled_contexts+1;
     p1_running<=0;p2_running<=0;p1_seen<=0;p2_seen<=0;p1_fft<=0;p2_fft<=0;due1<=0;due2<=0;publish_div<=0;snapshots<=0;unconsumed<=0;input_age<=0;
     for(i=0;i<4;i=i+1)if(slots[i]==READY)begin slots[i]<=FREE;snapshots[i]<=0;end
    end
   end else if(!fault_latched&&!(state!=IDLE&&age>=JOB_TIMEOUT-1))case(state)
    IDLE:if(configured)begin
     if(have_ready)begin selected<=ready_slot;slots[ready_slot]<=RUN;kind<=0;channel<=0;fft_job(ready_slot,0);end
     else if(until_window>SCALAR_BUDGET+32)begin
      if(p1_enable&&!(p2_enable&&pause_p1)&&p1_eligible&&
          !(background_turn&&p2_enable&&p2_eligible)&&(p1_running||have_source))begin
       p1_running<=1; background_turn<=1;
       if(!p1_running)begin p1_source<=source_slot;p1_seen<=1;p1_last_frame<=frames[source_slot];end
       if(p1_fft)begin transform_job(1,p1_fft_spec);p1_fft<=0;end
       else scalar_job(1,p1_desc+p1_index*p1_stride,p1_running?p1_source:source_slot);
      end
      else if(p2_enable&&p2_eligible&&(p2_running||have_source))begin
       p2_running<=1;background_turn<=0;
       if(!p2_running)begin p2_source<=source_slot;p2_seen<=1;p2_last_frame<=frames[source_slot];end
       if(p2_fft)begin transform_job(2,p2_fft_spec);p2_fft<=0;end
       else scalar_job(2,p2_desc,p2_running?p2_source:source_slot);
      end
     end
    end
    FEATURE:if(feature_complete)publish_frame;
    ISSUE:if(command_valid&&command_ready)state<=WAIT;
    WAIT:if(completion_valid&&completion_token==command_token)begin
     if(completion_error!=0||(kind!=0&&completion_status[7:0]!=0))begin
      if(kind==0)begin slots[selected]<=FREE;failed_frames<=failed_frames+1;end
      else begin
       // A completed scalar numerical/descriptor failure is not a dead bus.
       // Isolate that optional service; transport, timeout and guard faults remain fatal.
       background_failures<=background_failures+1;
       if(kind==1)begin p1_running<=0;p1_fft<=0;p1_enable<=0;end
       else begin p2_running<=0;p2_fft<=0;p2_enable<=0;end
      end
      if(kind==0||(completion_error&~32'h20)!=0)fault_latched<=1;
      state<=IDLE;
     end else if(kind==0)begin
      if(channel<5)begin channel<=channel+1;fft_job(selected,channel+1'b1);end
      else begin
       if(FEATURES_ENABLED)begin state<=FEATURE;age<=0;end else publish_frame;
      end
     end else begin
      state<=IDLE;
      if(bg_transform)begin bg_transform<=0;end
      else if(completion_status[30]&&!completion_status[31])begin
       if(kind==1)begin p1_fft<=1;p1_fft_spec<=completion_status;end
       else begin p2_fft<=1;p2_fft_spec<=completion_status;end
      end else if(completion_status[31])begin
       background_completions<=background_completions+1;
       if(kind==1)begin p1_running<=0;due1<=PERIOD1;p1_index<=p1_index==p1_last?0:p1_index+1'b1;end else begin p2_running<=0;due2<=PERIOD2;if(p2_once)p2_enable<=0;end
      end
     end
    end
   endcase
   if(completion_valid&&(state!=WAIT||completion_token!=command_token))stale_completions<=stale_completions+1;
   // Ack must mean common bus+masters have been reset/drained, never local timeout.
   if(common_reset_ack)begin
    state<=IDLE;fault_latched<=0;configured<=0;snapshots<=0;unconsumed<=0;p1_seen<=0;p2_seen<=0;p1_running<=0;p2_running<=0;p1_fft<=0;p2_fft<=0;bg_transform<=0;
    for(i=0;i<4;i=i+1)slots[i]<=FREE;
   end
  end
 end
endmodule
