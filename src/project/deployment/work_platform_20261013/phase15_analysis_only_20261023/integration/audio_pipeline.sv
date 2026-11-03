`timescale 1ns/1ps
module audio_pipeline(
 input wire clk_compute,clk_audio,rst_n,
 input wire [5:0] mic_sd,output wire mic_sck,mic_ws,
 input wire cfg_valid,output wire cfg_ready,cfg_applied,cfg_rejected,
 input wire [31:0] cfg_session,cfg_version,cfg_arena_base,cfg_arena_words,cfg_reserved_low,cfg_reserved_high,
 input wire [31:0] cfg_p1_descriptor,cfg_p2_descriptor,
 input wire [3:0] cfg_p1_last_index,input wire [31:0] cfg_p1_stride,input wire cfg_p2_oneshot,
 input wire cfg_p1_enable,cfg_p2_enable,cfg_pause_p1_when_p2,
 input wire raw_enable,raw_cfg_valid,
 input wire [31:0] raw_base,raw_bytes,raw_reserved_low,raw_reserved_high,
 output wire raw_cfg_ready,raw_configured,
 input wire [1:0] kernel_dma_idle,kernel_memory_fault,
 output wire kernel_select,
 input wire common_bus_reset_ack,
 input wire event_cfg_commit,input wire [191:0] event_cfg_data,input wire [255:0] event_band_edges,
 output wire [34:0] event_power_before,output reg [34:0] event_power_now,
 output wire [15:0] event_reason_flags,output wire event_measurement_valid,
 output wire event_started,output wire [63:0] event_timestamp,
 output wire [31:0] raw_committed,raw_next_offset,raw_generation_id,output wire [63:0] raw_last_sample,
 output wire raw_cfg_accepted,output wire pcm_tick,output wire [31:0] microphone_status,
 output wire [31:0] feature_araddr,output wire feature_arvalid,feature_rready,
 input wire feature_arready,feature_rvalid,feature_rlast,input wire [31:0] feature_rdata,input wire [1:0] feature_rresp,
 output wire result_update,output wire [1:0] result_slot,
 output wire [31:0] result_frame,result_config,result_session,result_cycles,result_base,
 output wire [63:0] result_first,
 input wire result_ack,input wire [1:0] ack_slot,input wire [31:0] ack_frame,ack_session,
 output wire [3:0] snapshot_valid,
 output wire [1023:0] fft_slot_headers,
 output wire [31:0] missed_windows,dropped_samples,overwritten_results,failed_frames,background_completions,
 output wire [31:0] error_flags,
 output wire [31:0] raw_awaddr,output wire [7:0] raw_awlen,output wire [2:0] raw_awsize,output wire [1:0] raw_awburst,
 output wire raw_awvalid,input wire raw_awready,output wire [31:0] raw_wdata,output wire [3:0] raw_wstrb,
 output wire raw_wlast,raw_wvalid,input wire raw_wready,input wire [1:0] raw_bresp,input wire raw_bvalid,output wire raw_bready,
 output wire [31:0] win_awaddr,output wire [7:0] win_awlen,output wire [2:0] win_awsize,output wire [1:0] win_awburst,
 output wire win_awvalid,input wire win_awready,output wire [31:0] win_wdata,output wire [3:0] win_wstrb,
 output wire win_wlast,win_wvalid,input wire win_wready,input wire [1:0] win_bresp,input wire win_bvalid,output wire win_bready,
 output wire [31:0] ctl_awaddr,ctl_wdata,ctl_araddr,
 output wire ctl_awvalid,ctl_wvalid,ctl_bready,ctl_arvalid,ctl_rready,output wire [3:0] ctl_wstrb,
 input wire ctl_awready,ctl_wready,ctl_bvalid,ctl_arready,ctl_rvalid,
 input wire [1:0] ctl_bresp,ctl_rresp,input wire [31:0] ctl_rdata
);
 wire [31:0] background_failures;
 wire scheduler_cfg_ready,scheduler_cfg_rejected,scheduler_cfg_applied,ring_cfg_ready,ring_cfg_rejected;
 // External acknowledgement certifies the common fabric was drained/reset.
 // A local timeout alone must never withdraw any accepted AXI transaction.
 wire safe_reset_ack=common_bus_reset_ack&&(&kernel_dma_idle)&&
  !(raw_awvalid||raw_wvalid||raw_bready||win_awvalid||win_wvalid||win_bready||
    ctl_awvalid||ctl_wvalid||ctl_bready||ctl_arvalid||ctl_rready||feature_arvalid||feature_rready);
 reg region_error;
 reg analysis_region_valid;
 reg [31:0] analysis_begin,analysis_end,raw_begin,raw_end,pending_begin,pending_end;
 reg analysis_cfg_pending;
 wire [34:0] requested_end={3'b0,cfg_arena_base}+{1'b0,cfg_arena_words,2'b0};
 wire [32:0] requested_raw_end={1'b0,raw_base}+{1'b0,raw_bytes};
 wire analysis_regions_ok=!raw_cfg_valid&&(!raw_configured||requested_end<={1'b0,raw_begin}||cfg_arena_base>=raw_end);
 wire raw_regions_ok=!cfg_valid&&!analysis_cfg_pending&&!scheduler_cfg_applied&&(!analysis_region_valid||requested_raw_end<={1'b0,analysis_begin}||raw_base>=analysis_end);
 assign cfg_ready=scheduler_cfg_ready&&!analysis_cfg_pending&&!common_bus_reset_ack;assign raw_cfg_ready=ring_cfg_ready&&!analysis_cfg_pending&&!scheduler_cfg_applied&&!common_bus_reset_ack;
 assign cfg_applied=scheduler_cfg_applied;assign cfg_rejected=scheduler_cfg_rejected||(cfg_valid&&cfg_ready&&!analysis_regions_ok);
 always @(posedge clk_compute)begin
  if(!rst_n)begin region_error<=0;analysis_region_valid<=0;analysis_cfg_pending<=0;pending_begin<=0;pending_end<=0;analysis_begin<=0;analysis_end<=0;raw_begin<=0;raw_end<=0;end
  else begin
   if(safe_reset_ack)begin region_error<=0;analysis_region_valid<=0;analysis_cfg_pending<=0;end
   if(cfg_valid&&cfg_ready&&!analysis_regions_ok)region_error<=1;
   if(cfg_valid&&cfg_ready&&analysis_regions_ok)begin pending_begin<=cfg_arena_base;pending_end<=requested_end[31:0];analysis_cfg_pending<=1;end
   if(scheduler_cfg_applied)begin analysis_begin<=pending_begin;analysis_end<=pending_end;analysis_region_valid<=1;analysis_cfg_pending<=0;end
   if(scheduler_cfg_rejected)analysis_cfg_pending<=0;
   if(ring_cfg_rejected)region_error<=1;
   if(raw_cfg_valid&&raw_cfg_ready)begin
    if(!raw_regions_ok)region_error<=1;
    else if(raw_base[11:0]==0&&raw_bytes>=4096&&(raw_bytes&(raw_bytes-1))==0&&raw_base>=raw_reserved_low&&requested_raw_end<={1'b0,raw_reserved_high}&&raw_reserved_high>raw_reserved_low)begin raw_begin<=raw_base;raw_end<=requested_raw_end[31:0];end
   end
  end
 end
 wire pcm_valid,overflow_audio;wire [143:0] pcm;wire [63:0] sample_id;
 pcm_capture capture(.clk_audio(clk_audio),.clk_compute(clk_compute),.rst_n(rst_n),.mic_sd(mic_sd),.mic_sck(mic_sck),.mic_ws(mic_ws),.pcm_valid(pcm_valid),.pcm(pcm),.sample_id(sample_id),.overflow_audio(overflow_audio));
 (* ASYNC_REG="TRUE" *) reg [1:0] overflow_sync;
 always @(posedge clk_compute)if(!rst_n)overflow_sync<=0;else overflow_sync<={overflow_sync[0],overflow_audio};
 wire raw_fault,raw_timeout,raw_response;wire [31:0] committed,raw_generation,write_offset;wire [63:0] last_committed;wire raw_busy;
 pcm_axi_ring_writer ring_writer(.clk(clk_compute),.rst_n(rst_n),.enable(raw_enable),.clear_fault(safe_reset_ack),
 .cfg_valid(raw_cfg_valid&&raw_regions_ok&&!common_bus_reset_ack&&!analysis_cfg_pending&&!scheduler_cfg_applied),.cfg_ready(ring_cfg_ready),.cfg_base(raw_base),.cfg_bytes(raw_bytes),.cfg_reserved_low(raw_reserved_low),.cfg_reserved_high(raw_reserved_high),.cfg_rejected(ring_cfg_rejected),.configured(raw_configured),
 .sample_valid(pcm_valid),.pcm(pcm),.sample_id(sample_id),.dropped_samples(dropped_samples),.committed_samples(committed),.last_committed_sample_id(last_committed),.next_write_offset(write_offset),.region_generation(raw_generation),
 .fault_latched(raw_fault),.bus_timeout(raw_timeout),.bus_response_error(raw_response),.busy(raw_busy),
 .m_axi_awaddr(raw_awaddr),.m_axi_awlen(raw_awlen),.m_axi_awsize(raw_awsize),.m_axi_awburst(raw_awburst),.m_axi_awvalid(raw_awvalid),.m_axi_awready(raw_awready),.m_axi_wdata(raw_wdata),.m_axi_wstrb(raw_wstrb),.m_axi_wlast(raw_wlast),.m_axi_wvalid(raw_wvalid),.m_axi_wready(raw_wready),.m_axi_bresp(raw_bresp),.m_axi_bvalid(raw_bvalid),.m_axi_bready(raw_bready));
 wire window_valid,window_ready,window_bank;wire [31:0] frame,wconfig,wsession;wire [63:0] first;
 wire release_valid,release_bank,read_bank;wire [31:0] release_frame;wire [10:0] read_index;wire [143:0] read_data;
 wire [31:0] active_session,active_config,gaps,bad_release;wire [1:0] occupied;
 window_pool #(.HOP(2048)) pool(.clk(clk_compute),.rst_n(rst_n),.pcm_valid(pcm_valid),.pcm(pcm),.sample_id(sample_id),.config_version(active_config),.session_id(active_session),
 .window_valid(window_valid),.window_ready(window_ready),.window_bank(window_bank),.window_frame(frame),.window_config(wconfig),.window_session(wsession),.window_first(first),
 .release_valid(release_valid),.release_bank(release_bank),.release_frame(release_frame),.read_bank(read_bank),.read_index(read_index),.read_data(read_data),.missed_windows(missed_windows),.gaps(gaps),.bad_release(bad_release),.occupied(occupied));
 wire slot_valid,slot_take;wire [1:0] slot_id;wire [31:0] slot_address;
 wire fill_done,fill_ready,window_fault;wire [1:0] fill_slot;wire [31:0] fill_frame,fill_config,fill_session,fill_error;wire [63:0] fill_first;
 window_dma exporter(.clk(clk_compute),.rst_n(rst_n),.recover_ack(safe_reset_ack),.window_valid(window_valid),.window_ready(window_ready),.window_bank(window_bank),.window_frame(frame),.window_config(wconfig),.window_session(wsession),.window_first(first),
 .slot_valid(slot_valid),.slot_id(slot_id),.slot_address(slot_address),.slot_take(slot_take),.read_bank(read_bank),.read_index(read_index),.read_data(read_data),.release_valid(release_valid),.release_bank(release_bank),.release_frame(release_frame),
 .done_valid(fill_done),.done_ready(fill_ready),.done_slot(fill_slot),.done_frame(fill_frame),.done_config(fill_config),.done_session(fill_session),.done_error(fill_error),.done_first(fill_first),.fault_latched(window_fault),
 .awaddr(win_awaddr),.awlen(win_awlen),.awsize(win_awsize),.awburst(win_awburst),.awvalid(win_awvalid),.awready(win_awready),.wdata(win_wdata),.wstrb(win_wstrb),.wlast(win_wlast),.wvalid(win_wvalid),.wready(win_wready),.bresp(win_bresp),.bvalid(win_bvalid),.bready(win_bready));
 wire feature_request,feature_done,feature_consume,feature_quality,feature_fault;
 wire scheduler_fault;
 wire [31:0] feature_base;wire [63:0] feature_last,feature_time;
 wire [191:0] channel_power;wire [255:0] band_power;
 fft_event_features features(.clk(clk_compute),.rst_n(rst_n),.frame_valid(feature_request),.frame_base(feature_base),.frame_last(feature_last),
 .band_mask(event_cfg_data[15:8]),.band_edges(event_band_edges),.done_valid(feature_done),.done_ready(feature_consume||!feature_request),.feature_valid(feature_quality),
 .channel_power(channel_power),.band_power(band_power),.timestamp(feature_time),.fault(feature_fault),.araddr(feature_araddr),.arvalid(feature_arvalid),.arready(feature_arready),.rdata(feature_rdata),.rresp(feature_rresp),.rvalid(feature_rvalid),.rlast(feature_rlast),.rready(feature_rready));
 wire event_valid,event_on,event_ended,event_learned;wire [31:0] event_generation,event_output_generation;wire [7:0] event_reason,event_bands,event_fault;
 wire [34:0] background;wire [255:0] background_bands;
 event_power_detector detector(.clk(clk_compute),.rst_n(rst_n),.cfg_commit(event_cfg_commit),.cfg_data(event_cfg_data),.in_valid(feature_done&&feature_request),.feature_valid(feature_quality),.in_ready(feature_consume),
 .sample_timestamp(feature_time),.channel_power(channel_power),.band_power(band_power),.out_valid(event_valid),.out_ready(1'b1),.out_timestamp(event_timestamp),
 .config_generation(event_generation),.out_config_generation(event_output_generation),.out_reason(event_reason),.out_band_mask(event_bands),.out_started(event_on),.out_ended(event_ended),.out_active(),.learned(event_learned),.background_power(background),.background_bands(background_bands),.sticky_fault(event_fault));
 assign event_started=event_valid&&event_on;
 assign event_power_before=background;assign event_reason_flags={event_bands,event_reason};assign event_measurement_valid=feature_quality&&!scheduler_fault;
 always @*begin event_power_now=0;for(integer ec=0;ec<6;ec=ec+1)event_power_now=event_power_now+{3'b0,channel_power[32*ec+:32]};end
 assign raw_committed=committed;assign raw_next_offset=write_offset;assign raw_generation_id=raw_generation;assign raw_last_sample=last_committed;assign pcm_tick=pcm_valid;
 assign raw_cfg_accepted=raw_cfg_valid&&raw_cfg_ready&&raw_regions_ok&&raw_base[11:0]==0&&raw_bytes>=4096&&(raw_bytes&(raw_bytes-1))==0&&raw_base>=raw_reserved_low&&requested_raw_end<={1'b0,raw_reserved_high}&&raw_reserved_high>raw_reserved_low;
 wire mic_stale,mic_observation,mic_window;wire [5:0] mic_constant,mic_clip;wire [14:0] mic_pair;wire [31:0] mic_count;
 mic_health #(.CLK_HZ(50000000),.WINDOW_SAMPLES(48010)) mic_check(.clk(clk_compute),.rst_n(rst_n),.sample_valid(pcm_valid),.clear_faults(safe_reset_ack),.pcm(pcm),.acquisition_stale(mic_stale),.window_valid(mic_window),.observation_fresh(mic_observation),.constant_channel_warning(mic_constant),.clipping_warning(mic_clip),.identical_pair_warning(mic_pair),.sample_count(mic_count),.confirmed_wiring_fault());
 assign microphone_status={3'b0,mic_observation,mic_stale,mic_pair,mic_clip,mic_constant};
 wire command_valid,command_ready,completion_valid,completion_ready;wire [31:0] command_token,command_base;wire [4:0] command_count;wire [127:0] offsets;wire [511:0] values;
 wire [31:0] completion_token,completion_error,status0,status1;wire [1:0] active_kernel;wire bridge_fault;wire [31:0] stale,canceled;
 assign kernel_select=active_kernel[0];
 analysis_scheduler #(.WINDOW_CYCLES(2132900),.PUBLISH_WINDOWS(2),.FEATURES_ENABLED(1)) scheduler(.feature_request(feature_request),.feature_complete(feature_done&&feature_consume),.feature_base(feature_base),.feature_last(feature_last),
 .clk(clk_compute),.rst_n(rst_n),.cfg_valid(cfg_valid&&analysis_regions_ok&&!analysis_cfg_pending&&!common_bus_reset_ack),.cfg_ready(scheduler_cfg_ready),.cfg_applied(scheduler_cfg_applied),.cfg_rejected(scheduler_cfg_rejected),
 .cfg_session(cfg_session),.cfg_version(cfg_version),.cfg_arena_base(cfg_arena_base),.cfg_arena_words(cfg_arena_words),.cfg_reserved_low(cfg_reserved_low),.cfg_reserved_high(cfg_reserved_high),.cfg_p1_descriptor(cfg_p1_descriptor),
 .cfg_p1_last_index(cfg_p1_last_index),.cfg_p1_stride(cfg_p1_stride),.cfg_p2_oneshot(cfg_p2_oneshot),.cfg_p2_descriptor(cfg_p2_descriptor),.cfg_p1_enable(cfg_p1_enable),.cfg_p2_enable(cfg_p2_enable),.cfg_pause_p1_when_p2(cfg_pause_p1_when_p2),.active_session(active_session),.active_config(active_config),
 .slot_valid(slot_valid),.slot_id(slot_id),.slot_address(slot_address),.slot_take(slot_take),.taking_frame(frame),.taking_config(wconfig),.taking_session(wsession),.taking_first(first),
 .fill_done(fill_done),.fill_slot(fill_slot),.fill_frame(fill_frame),.fill_config(fill_config),.fill_session(fill_session),.fill_error(fill_error),.fill_ready(fill_ready),
 .command_valid(command_valid),.command_ready(command_ready),.command_token(command_token),.command_base(command_base),.command_count(command_count),.command_offsets(offsets),.command_values(values),
 .completion_valid(completion_valid),.completion_token(completion_token),.completion_error(completion_error),.completion_status(status1),.completion_ready(completion_ready),
 .result_update(result_update),.result_slot(result_slot),.result_frame(result_frame),.result_config(result_config),.result_session(result_session),.result_cycles(result_cycles),.result_first(result_first),.result_base(result_base),
 .result_ack(result_ack),.ack_slot(ack_slot),.ack_frame(ack_frame),.ack_session(ack_session),.snapshot_valid(snapshot_valid),.fft_slot_headers(fft_slot_headers),.overwritten_results(overwritten_results),.stale_completions(stale),.failed_frames(failed_frames),.background_completions(background_completions),.canceled_contexts(canceled),.background_failures(background_failures),.fault_latched(scheduler_fault),.common_reset_ack(safe_reset_ack));
 stream_job_bridge bridge(.clk(clk_compute),.rst_n(rst_n),.job_valid(command_valid),.job_ready(command_ready),.job_token(command_token),.job_kernel_base(command_base),.job_arg_count(command_count),.job_offsets(offsets),.job_values(values),
 .memory_fault(kernel_memory_fault[active_kernel[0]]),.kernel_dma_idle(kernel_dma_idle[active_kernel[0]]),.active_kernel(active_kernel),
 .completion_valid(completion_valid),.completion_ready(completion_ready),.completion_token(completion_token),.completion_error(completion_error),.result0(status0),.result1(status1),.fault_latched(bridge_fault),.recover_request(common_bus_reset_ack),.common_bus_reset_ack(safe_reset_ack),
 .m_awaddr(ctl_awaddr),.m_wdata(ctl_wdata),.m_araddr(ctl_araddr),.m_awvalid(ctl_awvalid),.m_wvalid(ctl_wvalid),.m_bready(ctl_bready),.m_arvalid(ctl_arvalid),.m_rready(ctl_rready),.m_wstrb(ctl_wstrb),
 .m_awready(ctl_awready),.m_wready(ctl_wready),.m_bvalid(ctl_bvalid),.m_arready(ctl_arready),.m_rvalid(ctl_rvalid),.m_bresp(ctl_bresp),.m_rresp(ctl_rresp),.m_rdata(ctl_rdata));
 assign error_flags={12'b0,|background_failures,event_fault,mic_stale,feature_fault,region_error,|kernel_memory_fault,bridge_fault,scheduler_fault,raw_response,raw_timeout,raw_fault,window_fault,overflow_sync[1]};
endmodule
