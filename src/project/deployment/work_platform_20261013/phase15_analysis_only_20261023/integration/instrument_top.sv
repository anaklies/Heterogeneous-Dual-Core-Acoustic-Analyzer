`timescale 1ns/1ps
// Integrated development subsystem: no UI or physical pin assignment here.
module instrument_top(
 input wire  clk_compute,
 input wire  clk_audio,
 input wire  rst_n,
 input wire [5:0] mic_sd,
 output wire  mic_sck,
 output wire  mic_ws,
 input wire  common_bus_reset_ack,
 output wire [31:0] raw_awaddr,
 output wire [7:0] raw_awlen,
 output wire [2:0] raw_awsize,
 output wire [1:0] raw_awburst,
 output wire  raw_awvalid,
 input wire  raw_awready,
 output wire [31:0] raw_wdata,
 output wire [3:0] raw_wstrb,
 output wire  raw_wlast,
 output wire  raw_wvalid,
 input wire  raw_wready,
 input wire [1:0] raw_bresp,
 input wire  raw_bvalid,
 output wire  raw_bready,
 output wire [31:0] win_awaddr,
 output wire [7:0] win_awlen,
 output wire [2:0] win_awsize,
 output wire [1:0] win_awburst,
 output wire  win_awvalid,
 input wire  win_awready,
 output wire [31:0] win_wdata,
 output wire [3:0] win_wstrb,
 output wire  win_wlast,
 output wire  win_wvalid,
 input wire  win_wready,
 input wire [1:0] win_bresp,
 input wire  win_bvalid,
 output wire  win_bready,
 output wire [31:0] fft_awaddr,
 output wire [7:0] fft_awlen,
 output wire [2:0] fft_awsize,
 output wire [1:0] fft_awburst,
 output wire  fft_awvalid,
 input wire  fft_awready,
 output wire [31:0] fft_wdata,
 output wire [3:0] fft_wstrb,
 output wire  fft_wlast,
 output wire  fft_wvalid,
 input wire  fft_wready,
 input wire [1:0] fft_bresp,
 input wire  fft_bvalid,
 output wire  fft_bready,
 output wire [31:0] fft_araddr,
 output wire [7:0] fft_arlen,
 output wire [2:0] fft_arsize,
 output wire [1:0] fft_arburst,
 output wire  fft_arvalid,
 input wire  fft_arready,
 input wire [31:0] fft_rdata,
 input wire [1:0] fft_rresp,
 input wire  fft_rlast,
 input wire  fft_rvalid,
 output wire  fft_rready,
 output wire [31:0] scalar_awaddr,
 output wire [7:0] scalar_awlen,
 output wire [2:0] scalar_awsize,
 output wire [1:0] scalar_awburst,
 output wire  scalar_awvalid,
 input wire  scalar_awready,
 output wire [31:0] scalar_wdata,
 output wire [3:0] scalar_wstrb,
 output wire  scalar_wlast,
 output wire  scalar_wvalid,
 input wire  scalar_wready,
 input wire [1:0] scalar_bresp,
 input wire  scalar_bvalid,
 output wire  scalar_bready,
 output wire [31:0] scalar_araddr,
 output wire [7:0] scalar_arlen,
 output wire [2:0] scalar_arsize,
 output wire [1:0] scalar_arburst,
 output wire  scalar_arvalid,
 input wire  scalar_arready,
 input wire [31:0] scalar_rdata,
 input wire [1:0] scalar_rresp,
 input wire  scalar_rlast,
 input wire  scalar_rvalid,
 output wire  scalar_rready,
 output wire [31:0] feature_araddr,
 output wire  feature_arvalid,
 output wire  feature_rready,
 input wire  feature_arready,
 input wire  feature_rvalid,
 input wire  feature_rlast,
 input wire [31:0] feature_rdata,
 input wire [1:0] feature_rresp,
 inout wire sensor_scl,sensor_sda,
 input wire [11:0] host_awaddr,host_araddr,
 input wire host_awvalid,host_wvalid,host_bready,host_arvalid,host_rready,
 input wire [31:0] host_wdata,input wire [3:0] host_wstrb,
 output wire host_awready,host_wready,host_bvalid,host_arready,host_rvalid,
 output wire [1:0] host_bresp,host_rresp,output wire [31:0] host_rdata,output wire irq
);
 reg [1023:0] pending_cfg,active_cfg;reg [1:0] apply_state;
 wire [63:0] clip_first,clip_last;wire [1:0] leases;
 wire  cfg_valid;
 wire  cfg_ready;
 wire  cfg_applied;
 wire  cfg_rejected;
 wire [31:0] cfg_session;
 wire [31:0] cfg_version;
 wire [31:0] cfg_arena_base;
 wire [31:0] cfg_arena_words;
 wire [31:0] cfg_reserved_low;
 wire [31:0] cfg_reserved_high;
 wire [31:0] cfg_p1_descriptor;
 wire [31:0] cfg_p2_descriptor;
 wire  cfg_p1_enable;
 wire  cfg_p2_enable;
 wire  cfg_pause_p1_when_p2;
 wire  raw_enable;
 wire  raw_cfg_valid;
 wire [31:0] raw_base;
 wire [31:0] raw_bytes;
 wire [31:0] raw_reserved_low;
 wire [31:0] raw_reserved_high;
 wire  raw_cfg_ready;
 wire  raw_configured;
 wire  result_update;
 wire [1:0] result_slot;
 wire [31:0] result_frame;
 wire [31:0] result_config;
 wire [31:0] result_session;
 wire [31:0] result_cycles;
 wire [31:0] result_base;
 wire [63:0] result_first;
 wire  result_ack;
 wire [1:0] ack_slot;
 wire [31:0] ack_frame;
 wire [31:0] ack_session;
 wire [3:0] snapshot_valid;
 wire [1023:0] fft_slot_headers;
 wire [31:0] missed_windows;
 wire [31:0] dropped_samples;
 wire [31:0] overwritten_results;
 wire [31:0] failed_frames;
 wire [31:0] background_completions;
 wire [31:0] error_flags;
 wire  event_cfg_commit;
 wire [191:0] event_cfg_data;
 wire [255:0] event_band_edges;
 wire  event_started;
 wire [63:0] event_timestamp;
 wire [31:0] raw_committed;
 wire [31:0] raw_next_offset;
 wire [31:0] raw_generation_id;
 wire [63:0] raw_last_sample;
 wire  raw_cfg_accepted;
 wire  pcm_tick;
 wire [31:0] microphone_status;
 wire [34:0] event_power_before,event_power_now;wire [15:0] event_reason_flags;wire event_measurement_valid;
 wire capturing;reg [34:0] clip_background;reg [15:0] clip_reason;reg [63:0] clip_origin;
 wire [63:0] summary_age=clip_last>=event_timestamp?clip_last-event_timestamp:event_timestamp-clip_last;
 wire [31:0] before_q22=clip_background>>8,after_q22=event_power_now>>8;
 always @(posedge clk_compute)begin
  if(!rst_n)begin clip_background<=0;clip_reason<=0;clip_origin<=0;end
  else if(event_started&&!capturing)begin clip_background<=event_power_before;clip_reason<=event_reason_flags;clip_origin<=active_cfg[63:0];end
 end
 analysis_runtime runtime(
 .clk_compute(clk_compute),
 .clk_audio(clk_audio),
 .rst_n(rst_n),
 .mic_sd(mic_sd),
 .mic_sck(mic_sck),
 .mic_ws(mic_ws),
 .cfg_valid(cfg_valid),
 .cfg_ready(cfg_ready),
 .cfg_applied(cfg_applied),
 .cfg_rejected(cfg_rejected),
 .cfg_session(cfg_session),
 .cfg_version(cfg_version),
 .cfg_arena_base(cfg_arena_base),
 .cfg_arena_words(cfg_arena_words),
 .cfg_reserved_low(cfg_reserved_low),
 .cfg_reserved_high(cfg_reserved_high),
 .cfg_p1_descriptor(cfg_p1_descriptor),
 .cfg_p1_last_index(pending_cfg[480+:4]),.cfg_p1_stride(pending_cfg[960+:32]),.cfg_p2_oneshot(pending_cfg[992]),
 .cfg_p2_descriptor(cfg_p2_descriptor),
 .cfg_p1_enable(cfg_p1_enable),
 .cfg_p2_enable(cfg_p2_enable),
 .cfg_pause_p1_when_p2(cfg_pause_p1_when_p2),
 .raw_enable(raw_enable),
 .raw_cfg_valid(raw_cfg_valid),
 .raw_base(raw_base),
 .raw_bytes(raw_bytes),
 .raw_reserved_low(raw_reserved_low),
 .raw_reserved_high(raw_reserved_high),
 .raw_cfg_ready(raw_cfg_ready),
 .raw_configured(raw_configured),
 .common_bus_reset_ack(common_bus_reset_ack),
 .result_update(result_update),
 .result_slot(result_slot),
 .result_frame(result_frame),
 .result_config(result_config),
 .result_session(result_session),
 .result_cycles(result_cycles),
 .result_base(result_base),
 .result_first(result_first),
 .result_ack(result_ack),
 .ack_slot(ack_slot),
 .ack_frame(ack_frame),
 .ack_session(ack_session),
 .snapshot_valid(snapshot_valid),.fft_slot_headers(fft_slot_headers),
 .missed_windows(missed_windows),
 .dropped_samples(dropped_samples),
 .overwritten_results(overwritten_results),
 .failed_frames(failed_frames),
 .background_completions(background_completions),
 .error_flags(error_flags),
 .raw_awaddr(raw_awaddr),
 .raw_awlen(raw_awlen),
 .raw_awsize(raw_awsize),
 .raw_awburst(raw_awburst),
 .raw_awvalid(raw_awvalid),
 .raw_awready(raw_awready),
 .raw_wdata(raw_wdata),
 .raw_wstrb(raw_wstrb),
 .raw_wlast(raw_wlast),
 .raw_wvalid(raw_wvalid),
 .raw_wready(raw_wready),
 .raw_bresp(raw_bresp),
 .raw_bvalid(raw_bvalid),
 .raw_bready(raw_bready),
 .win_awaddr(win_awaddr),
 .win_awlen(win_awlen),
 .win_awsize(win_awsize),
 .win_awburst(win_awburst),
 .win_awvalid(win_awvalid),
 .win_awready(win_awready),
 .win_wdata(win_wdata),
 .win_wstrb(win_wstrb),
 .win_wlast(win_wlast),
 .win_wvalid(win_wvalid),
 .win_wready(win_wready),
 .win_bresp(win_bresp),
 .win_bvalid(win_bvalid),
 .win_bready(win_bready),
 .fft_awaddr(fft_awaddr),
 .fft_awlen(fft_awlen),
 .fft_awsize(fft_awsize),
 .fft_awburst(fft_awburst),
 .fft_awvalid(fft_awvalid),
 .fft_awready(fft_awready),
 .fft_wdata(fft_wdata),
 .fft_wstrb(fft_wstrb),
 .fft_wlast(fft_wlast),
 .fft_wvalid(fft_wvalid),
 .fft_wready(fft_wready),
 .fft_bresp(fft_bresp),
 .fft_bvalid(fft_bvalid),
 .fft_bready(fft_bready),
 .fft_araddr(fft_araddr),
 .fft_arlen(fft_arlen),
 .fft_arsize(fft_arsize),
 .fft_arburst(fft_arburst),
 .fft_arvalid(fft_arvalid),
 .fft_arready(fft_arready),
 .fft_rdata(fft_rdata),
 .fft_rresp(fft_rresp),
 .fft_rlast(fft_rlast),
 .fft_rvalid(fft_rvalid),
 .fft_rready(fft_rready),
 .scalar_awaddr(scalar_awaddr),
 .scalar_awlen(scalar_awlen),
 .scalar_awsize(scalar_awsize),
 .scalar_awburst(scalar_awburst),
 .scalar_awvalid(scalar_awvalid),
 .scalar_awready(scalar_awready),
 .scalar_wdata(scalar_wdata),
 .scalar_wstrb(scalar_wstrb),
 .scalar_wlast(scalar_wlast),
 .scalar_wvalid(scalar_wvalid),
 .scalar_wready(scalar_wready),
 .scalar_bresp(scalar_bresp),
 .scalar_bvalid(scalar_bvalid),
 .scalar_bready(scalar_bready),
 .scalar_araddr(scalar_araddr),
 .scalar_arlen(scalar_arlen),
 .scalar_arsize(scalar_arsize),
 .scalar_arburst(scalar_arburst),
 .scalar_arvalid(scalar_arvalid),
 .scalar_arready(scalar_arready),
 .scalar_rdata(scalar_rdata),
 .scalar_rresp(scalar_rresp),
 .scalar_rlast(scalar_rlast),
 .scalar_rvalid(scalar_rvalid),
 .scalar_rready(scalar_rready),
 .event_cfg_commit(event_cfg_commit),
 .event_cfg_data(event_cfg_data),
 .event_band_edges(event_band_edges),
 .event_started(event_started),
 .event_timestamp(event_timestamp),
 .raw_committed(raw_committed),
 .raw_next_offset(raw_next_offset),
 .raw_generation_id(raw_generation_id),
 .raw_last_sample(raw_last_sample),
 .raw_cfg_accepted(raw_cfg_accepted),
 .pcm_tick(pcm_tick),
 .microphone_status(microphone_status),
 .feature_araddr(feature_araddr),
 .feature_arvalid(feature_arvalid),
 .feature_rready(feature_rready),
 .feature_arready(feature_arready),
 .feature_rvalid(feature_rvalid),
 .feature_rlast(feature_rlast),
 .feature_rdata(feature_rdata),
 .feature_rresp(feature_rresp),
 .event_power_before(event_power_before),.event_power_now(event_power_now),.event_reason_flags(event_reason_flags),.event_measurement_valid(event_measurement_valid)
);
 wire record_arm=active_cfg[259];
 wire [511:0] raw_cursor_words;
 raw_cursor cursor(.clk(clk_compute),.rst_n(rst_n),.configured(raw_configured),.record_arm(record_arm),.writer_enable(raw_enable),
 .generation(raw_generation_id),.base(raw_awaddr-raw_next_offset),.bytes(raw_bytes),.next_offset(raw_next_offset),.dropped(dropped_samples),.faults(error_flags),.session(active_cfg[0+:32]),.config_version(active_cfg[32+:32]),.last_sample(raw_last_sample),.leased(leases),.words(raw_cursor_words));
 wire host_cfg_valid;wire [1023:0] host_cfg;
 reg applied,rejected,event_commit_r,event_initialized;
 wire clip_valid,clip_ready,clip_bank_out,clip_release,release_bank,clip_incomplete,recorder_fault;
 wire [31:0] clip_id_out,release_id,clip_offset,clip_frames,lost_events,handoff_drops;
 wire [511:0] clip_words;
 wire signed [15:0] temp,roll,pitch,yaw,qw,qx,qy,qz;
 wire [15:0] humidity,sensor_errors;wire [31:0] pressure,speed_float,env_seq,pose_seq;
 wire signed [31:0] speed_q16;wire temp_valid,pressure_valid,pose_valid,env_valid;
 wire [1:0] env_mode;wire [7:0] sensor_faults;
 reg [1023:0] result_words;

 wire [31:0] all_faults=error_flags|{8'b0,(|sensor_faults),(handoff_drops!=0),(lost_events!=0),recorder_fault,20'b0};
 wire [34:0] req0_end={3'b0,host_cfg[9*32+:32]}+{3'b0,host_cfg[10*32+:32]};
 wire [34:0] req1_end={3'b0,host_cfg[13*32+:32]}+{3'b0,host_cfg[10*32+:32]};
 wire [34:0] req_analysis_end={3'b0,host_cfg[2*32+:32]}+{1'b0,host_cfg[3*32+:32],2'b0};
 wire raw_legal=!(host_cfg[259]||record_arm||(|leases))||(
 host_cfg[10*32+:32]>=16777216&&(host_cfg[10*32+:32]&(host_cfg[10*32+:32]-1))==0&&
 host_cfg[9*32+:12]==0&&host_cfg[13*32+:12]==0&&
 host_cfg[9*32+:32]>=host_cfg[11*32+:32]&&host_cfg[13*32+:32]>=host_cfg[11*32+:32]&&
 req0_end<={3'b0,host_cfg[12*32+:32]}&&req1_end<={3'b0,host_cfg[12*32+:32]}&&
 (req0_end<={3'b0,host_cfg[13*32+:32]}||req1_end<={3'b0,host_cfg[9*32+:32]})&&
 (req0_end<={3'b0,host_cfg[2*32+:32]}||req_analysis_end<={3'b0,host_cfg[9*32+:32]})&&
 (req1_end<={3'b0,host_cfg[2*32+:32]}||req_analysis_end<={3'b0,host_cfg[13*32+:32]}));
 wire geometry_locked=(record_arm||(|leases))&&
 (host_cfg[9*32+:128]!=active_cfg[9*32+:128]||host_cfg[13*32+:32]!=active_cfg[13*32+:32]);
 assign cfg_valid=apply_state==1;
 assign cfg_session=pending_cfg[0+:32];assign cfg_version=pending_cfg[32+:32];
 assign cfg_arena_base=pending_cfg[64+:32];assign cfg_arena_words=pending_cfg[96+:32];
 assign cfg_reserved_low=pending_cfg[128+:32];assign cfg_reserved_high=pending_cfg[160+:32];
 assign cfg_p1_descriptor=pending_cfg[192+:32];assign cfg_p2_descriptor=pending_cfg[224+:32];
 assign cfg_p1_enable=pending_cfg[256];assign cfg_p2_enable=pending_cfg[257];assign cfg_pause_p1_when_p2=pending_cfg[258];
 assign raw_reserved_low=active_cfg[352+:32];assign raw_reserved_high=active_cfg[384+:32];
 assign result_ack=1'b0;assign ack_slot=0;assign ack_frame=0;assign ack_session=0;
 assign event_band_edges=active_cfg[704+:256];
 localparam [191:0] DEFAULT_EVENT=192'h0800000400000400000c00c0000400180080020002000000;
 wire [191:0] configured_event=active_cfg[512+:192]==0?DEFAULT_EVENT:active_cfg[512+:192];
 assign event_cfg_data={configured_event[191:1],(active_cfg[448]&&record_arm)};
 assign event_cfg_commit=event_commit_r;
 always @(posedge clk_compute)begin
  if(!rst_n)begin apply_state<=0;pending_cfg<=0;active_cfg<=0;applied<=0;rejected<=0;event_commit_r<=0;event_initialized<=0;end
  else begin
   applied<=0;rejected<=0;event_commit_r<=0;
   case(apply_state)
    0:if(host_cfg_valid)begin
     if(!raw_legal||geometry_locked)rejected<=1;
     else begin pending_cfg<=host_cfg;apply_state<=1;end
    end
    1:if(cfg_ready)apply_state<=2;
    2:if(cfg_rejected)begin rejected<=1;apply_state<=0;end
      else if(cfg_applied)begin
       active_cfg<=pending_cfg;event_initialized<=1;event_commit_r<=!event_initialized||pending_cfg[512+:448]!=active_cfg[512+:448]||pending_cfg[448]!=active_cfg[448]||pending_cfg[259]!=active_cfg[259];
       if(pending_cfg[259]&&!record_arm)apply_state<=3;
       else begin applied<=1;apply_state<=0;end
      end
    3:if(raw_cfg_accepted)begin applied<=1;apply_state<=0;end
      else if(recorder_fault)begin rejected<=1;apply_state<=0;end
   endcase
  end
 end
 event_recorder recorder(.clk(clk_compute),.rst_n(rst_n),.enable(record_arm),.sample_valid(pcm_tick),.event_start(event_started),.event_sample(event_timestamp),
 .last_committed(raw_last_sample),.committed(raw_committed),.next_offset(raw_next_offset),.writer_drops(dropped_samples),
 .bank0_base(active_cfg[288+:32]),.bank1_base(active_cfg[416+:32]),.bank_bytes(active_cfg[320+:32]),.reserved_low(raw_reserved_low),.reserved_high(raw_reserved_high),
 .capturing(capturing),.writer_enable(raw_enable),.writer_cfg_valid(raw_cfg_valid),.writer_cfg_ready(raw_cfg_ready),.writer_cfg_accepted(raw_cfg_accepted),.writer_cfg_base(raw_base),.writer_cfg_bytes(raw_bytes),
 .release_valid(clip_release),.release_bank(release_bank),.release_id(release_id),
 .descriptor_valid(clip_valid),.descriptor_ready(clip_ready),.descriptor_bank(clip_bank_out),.descriptor_id(clip_id_out),.descriptor_start_offset(clip_offset),.descriptor_frames(clip_frames),
 .descriptor_first(clip_first),.descriptor_last(clip_last),.descriptor_incomplete(clip_incomplete),.leased(leases),.lost_events(lost_events),.handoff_drops(handoff_drops),.fault(recorder_fault));
 assign clip_words={summary_age[30:0],event_measurement_valid,(after_q22-before_q22),after_q22,before_q22,16'b0,clip_reason,clip_origin,31'b0,clip_incomplete,clip_last,clip_first,clip_frames,clip_offset,(clip_bank_out?active_cfg[416+:32]:active_cfg[288+:32]),clip_id_out};
 instrument_sensors sensors(.clk(clk_compute),.rst_n(rst_n),.scl(sensor_scl),.sda(sensor_sda),.temperature_centi(temp),.roll(roll),.pitch(pitch),.yaw(yaw),.qw(qw),.qx(qx),.qy(qy),.qz(qz),
 .humidity_raw(humidity),.pressure_pa(pressure),.temperature_valid(temp_valid),.pressure_valid(pressure_valid),.orientation_valid(pose_valid),.speed_float(speed_float),.speed_q16(speed_q16),.environment_mode(env_mode),.environment_valid(env_valid),.environment_sequence(env_seq),.pose_sequence(pose_seq),.sensor_faults(sensor_faults),.sensor_error_count(sensor_errors));
 always @*begin
  result_words=0;
  result_words[0+:32]=3;result_words[32+:32]=32'h82000002;
  result_words[64+:32]=result_frame;result_words[96+:32]=result_config;result_words[128+:32]=result_session;
  result_words[160+:32]={30'b0,result_slot};result_words[192+:32]=result_base;result_words[224+:32]=result_cycles;
  result_words[256+:64]=result_first;result_words[320+:32]=all_faults;result_words[352+:32]=microphone_status;
  result_words[384+:32]=missed_windows;result_words[416+:32]=dropped_samples;result_words[448+:32]=background_completions;
  result_words[480+:32]=overwritten_results;result_words[512+:32]=failed_frames;
  result_words[544+:32]={{16{temp[15]}},temp};result_words[576+:32]={16'b0,humidity};result_words[608+:32]=pressure;
  result_words[640+:32]=speed_float;result_words[672+:32]={26'b0,env_mode,env_valid,pose_valid,pressure_valid,temp_valid};
  result_words[704+:32]={pitch,roll};result_words[736+:32]={16'b0,yaw};result_words[768+:32]={qx,qw};result_words[800+:32]={qz,qy};
  result_words[832+:32]=env_seq;result_words[864+:32]=pose_seq;result_words[896+:32]={8'b0,sensor_faults,sensor_errors};
  result_words[928+:32]=lost_events;result_words[960+:32]=handoff_drops;result_words[992+:32]=32'h473b89c6;
 end
 runtime_control #(.CFG_WORDS(32),.PROTOCOL(3),.CAPABILITIES(64'h3)) control(.clk(clk_compute),.rst_n(rst_n),
 .awaddr(host_awaddr),.awvalid(host_awvalid),.awready(host_awready),.wdata(host_wdata),.wstrb(host_wstrb),.wvalid(host_wvalid),.wready(host_wready),
 .bresp(host_bresp),.bvalid(host_bvalid),.bready(host_bready),.araddr(host_araddr),.arvalid(host_arvalid),.arready(host_arready),.rdata(host_rdata),.rresp(host_rresp),.rvalid(host_rvalid),.rready(host_rready),
 .cfg_valid(host_cfg_valid),.cfg_ready(apply_state==0),.cfg_applied(applied),.cfg_rejected(rejected),.cfg_payload(host_cfg),.fft_slot_words(fft_slot_headers),.raw_cursor_words(raw_cursor_words),.result_valid(result_update),.result_words(result_words),
 .live_faults(all_faults),.active_config(active_cfg[32+:32]),.clip_valid(clip_valid),.clip_bank_in(clip_bank_out),.clip_words(clip_words),.clip_ready(clip_ready),.clip_release(clip_release),.clip_bank(release_bank),.clip_id(release_id),.irq(irq));
endmodule

