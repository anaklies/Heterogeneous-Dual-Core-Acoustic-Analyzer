`timescale 1ns/1ps
// Autonomous six-microphone PL baseline. One complete acquisition window
// follows every committed result. PS-facing display is a separate consumer.

module sixmic_pl_top #(
    parameter COEFF_DIR = "pl/coeff"
)
(
    input  wire clk_50m,
    input  wire rst_n,
    input  wire clear_fault_history,
    input  wire mic1_sd,
    input  wire mic2_sd,
    input  wire mic3_sd,
    input  wire mic4_sd,
    input  wire mic5_sd,
    input  wire mic6_sd,
    output wire mic1_sck,
    output wire mic2_sck,
    output wire mic3_sck,
    output wire mic4_sck,
    output wire mic5_sck,
    output wire mic6_sck,
    output wire mic1_ws,
    output wire mic2_ws,
    output wire mic3_ws,
    output wire mic4_ws,
    output wire mic5_ws,
    output wire mic6_ws,
    inout wire sensor_scl,
    inout wire sensor_sda,
    input  wire [11:0] s_axi_awaddr,
    input  wire s_axi_awvalid,
    output wire s_axi_awready,
    input  wire [31:0] s_axi_wdata,
    input  wire [3:0] s_axi_wstrb,
    input  wire s_axi_wvalid,
    output wire s_axi_wready,
    output wire [1:0] s_axi_bresp,
    output wire s_axi_bvalid,
    input  wire s_axi_bready,
    input  wire [11:0] s_axi_araddr,
    input  wire s_axi_arvalid,
    output wire s_axi_arready,
    output wire [31:0] s_axi_rdata,
    output wire [1:0] s_axi_rresp,
    output wire s_axi_rvalid,
    input  wire s_axi_rready,
    output wire irq,
    output wire [3:0] restart_count,
    output wire algorithm_clk_out,
    output wire algorithm_resetn_out,
    output wire window_committed,
    output wire [3:0] window_fault
);

    wire clk, clock_locked, core_reset_n, clock_fault, reference_clock_fault;
    assign algorithm_clk_out = clk;
    assign algorithm_resetn_out = core_reset_n;
    wire [3:0] clock_restart_count;
    wire [7:0] sensor_faults;
    wire signed [15:0] temperature_centi, qw, qx, qy, qz, roll, pitch, yaw;
    wire temperature_valid, orientation_valid, world_rotation_valid;
    wire [15:0] sensor_error_count;
    wire [287:0] world_rotation_q16;
    wire diagnostic_sample_valid, overrun, window_clip, fft_protocol_error;
    wire [143:0] diagnostic_pcm;
    wire signed [47:0] covariance_real, covariance_imag;
    wire [31:0] observation_count;
    wire covariance_busy;
    wire short_valid, short_ready;
    wire [2:0] short_channel;
    wire [10:0] short_bin;
    wire signed [31:0] short_real, short_imag;
    wire [31:0] short_frame_samples;
    wire covariance_clear, covariance_pause, short_arm, config_capture, features_start, backend_request;
    wire recovery_request, coordinates_permitted;
    wire scheduler_busy, short_complete, short_error, config_done, features_done, features_error;
    wire reduced_done, reduced_error, flat_start, flat_done, flat_error;
    wire backend_ready, backend_busy, backend_done, backend_load_error;
    wire [3:0] backend_fault;
    wire reset_processing_n = core_reset_n && !recovery_request;
    wire [10:0] cov_r_address, cov_i_address, bg_r_address, bg_i_address;
    wire cov_r_ce, cov_i_ce, bg_r_ce, bg_i_ce;
    wire [63:0] cov_r_data = {{16{covariance_real[47]}}, covariance_real};
    wire [63:0] cov_i_data = {{16{covariance_imag[47]}}, covariance_imag};
    wire [7:0] sensor_fault_details = sensor_faults;
    wire [31:0] active_faults, latched_faults, dropped_frames, rejected_frames;
    wire [31:0] music_cycles, track_cycles;
    wire config_write_valid, config_write_ready;
    wire [3:0] config_write_address;
    wire [31:0] config_write_float;
    wire backend_weight_ready;
    wire flat_weight_valid, flat_weight_ready;
    wire [6:0] flat_weight_address;
    wire [31:0] flat_weight_float;
    wire cnn_weight_valid, cnn_weight_ready;
    wire [6:0] cnn_weight_address;
    wire [31:0] cnn_weight_float;
    wire [13:0] spectrum_address;
    wire [63:0] spectrum_data;
    wire spectrum_valid, spectrum_ready;
    wire mask_valid, mask_ready;
    wire [12:0] mask_address;
    wire [15:0] mask_data;
    wire bg_write_ready, band_busy, band_done, band_error;
    reg [8:0] background_index;
    reg [2:0] background_phase;
    reg mode_for_window;
    wire reference_ready, reference_noisy;
    wire adaptive_use_cnn, clear_reference;
    wire [15:0] humidity_raw;
    wire [31:0] pressure_pa;
    wire pressure_valid;
    wire [31:0] reference_float;

    reg config_done_seen;
    wire background_valid = background_phase == 3 && background_index < 257;
    wire background_ready = background_index == 257;

    wire spatial_reference_busy, spatial_reference_done, spatial_reference_valid, spatial_cov_read;
    wire config_mode = reference_ready && reference_noisy && background_ready && spatial_reference_valid;
    wire [10:0] spatial_cov_address;
    wire [63:0] spatial_bg_r_data, spatial_bg_i_data;
    reg spatial_done_seen;
    wire [31:0] dt_float = 32'h3e5a740e;
    // 20*512/48000 s; bounded tracker dt
    // The trained CNN requires a trusted reference. Until that reference is
    // established, ordinary MUSIC remains active and no target is trained away.
    wire cnn_required = mode_for_window;
    wire acquisition_valid = coordinates_permitted && !clock_fault && !covariance_busy;
    wire pipeline_error = short_error || band_error || reduced_error || flat_error || backend_load_error ||
        window_fault != 0;
    wire world_frame_valid, temp_compensated;

    sixmic_frontend_top #(.COEFF_DIR(COEFF_DIR)) frontend(
    .clk_50m(clk_50m), .rst_n(rst_n), .processing_restart(recovery_request),
        .mic1_sd(mic1_sd), .mic2_sd(mic2_sd), .mic3_sd(mic3_sd), .mic4_sd(mic4_sd), .mic5_sd(mic5_sd),
        .mic6_sd(mic6_sd),
        .mic1_sck(mic1_sck), .mic2_sck(mic2_sck), .mic3_sck(mic3_sck), .mic4_sck(mic4_sck), .mic5_sck(mic5_sck),
        .mic6_sck(mic6_sck),
        .mic1_ws(mic1_ws), .mic2_ws(mic2_ws), .mic3_ws(mic3_ws), .mic4_ws(mic4_ws), .mic5_ws(mic5_ws),
        .mic6_ws(mic6_ws),
        .clock_locked(clock_locked), .algorithm_clk(clk), .algorithm_rst_n(core_reset_n),
        .covariance_clear(covariance_clear), .covariance_read_enable(spatial_reference_busy?spatial_cov_read:cov_r_ce),
        .covariance_pause(covariance_pause),
        .covariance_read_imag_enable(spatial_reference_busy?spatial_cov_read:cov_i_ce),
        .covariance_read_address(spatial_reference_busy?spatial_cov_address:cov_r_address),
        .covariance_read_imag_address(spatial_reference_busy?spatial_cov_address:cov_i_address),
        .covariance_real(covariance_real), .covariance_imag(covariance_imag),
        .observation_count(observation_count),
        .covariance_busy(covariance_busy),
        .short_valid(short_valid), .short_ready(short_ready), .short_channel(short_channel),
        .short_bin(short_bin),
        .short_real(short_real), .short_imag(short_imag), .short_frame_samples(short_frame_samples),
        .sensor_scl(sensor_scl), .sensor_sda(sensor_sda), .temperature_centi(temperature_centi),
        .imu_qw(qw), .imu_qx(qx), .imu_qy(qy), .imu_qz(qz), .imu_roll(roll), .imu_pitch(pitch), .imu_yaw(yaw),
        .temperature_valid(temperature_valid), .orientation_valid(orientation_valid),
        .humidity_raw(humidity_raw), .pressure_pa(pressure_pa), .pressure_valid(pressure_valid),
        .sensor_error_count(sensor_error_count),
        .world_rotation_q16(world_rotation_q16), .world_rotation_valid(world_rotation_valid),
        .clock_fault(clock_fault), .reference_clock_fault(reference_clock_fault),
        .clock_restart_count(clock_restart_count),
        .sensor_faults(sensor_faults), .diagnostic_sample_valid(diagnostic_sample_valid),
        .diagnostic_pcm(diagnostic_pcm),
        .overrun(overrun), .window_clip(window_clip), .fft_protocol_error(fft_protocol_error));
    short_spectrum_window short_window(.clk(clk), .rst_n(reset_processing_n), .arm(short_arm),
        .abort_window(recovery_request),
        .short_valid(short_valid), .short_ready(short_ready), .short_channel(short_channel),
        .short_bin(short_bin),
        .short_real(short_real), .short_imag(short_imag), .spectrum_valid(spectrum_valid),
        .spectrum_ready(spectrum_ready),
        .spectrum_address(spectrum_address), .spectrum_data(spectrum_data), .busy(), .complete(short_complete),
        .protocol_error(short_error));
    pl_adaptive_mode adaptive_mode(.clk(clk), .rst_n(reset_processing_n), .arm(short_arm),
        .reference_qualified(spatial_reference_valid), .short_valid(short_valid), .short_ready(short_ready),
        .short_channel(short_channel), .short_bin(short_bin), .short_real(short_real), .short_imag(short_imag),
        .use_cnn(adaptive_use_cnn), .clear_reference(clear_reference));
    pl_noise_floor reference_floor(.clk(clk), .rst_n(reset_processing_n), .clear_reference(clear_reference), .arm(short_arm),
        .retain_reference(spatial_reference_valid),
        .short_valid(short_valid), .short_ready(short_ready), .short_channel(short_channel),
        .short_bin(short_bin),
        .short_real(short_real), .short_imag(short_imag), .read_address(background_index),
        .read_float(reference_float), .ready(reference_ready), .noisy(reference_noisy));
    pl_background_covariance spatial_reference(.clk(clk), .rst_n(reset_processing_n), .clear_reference(clear_reference),
        .start(config_capture),
        .noise_present(reference_ready && reference_noisy), .busy(spatial_reference_busy),
        .done(spatial_reference_done), .valid(spatial_reference_valid),
        .covariance_read_enable(spatial_cov_read), .covariance_read_address(spatial_cov_address),
        .covariance_real(covariance_real), .covariance_imag(covariance_imag),
        .bg_r_ce(bg_r_ce), .bg_r_address(bg_r_address), .bg_r_data(spatial_bg_r_data),
        .bg_i_ce(bg_i_ce), .bg_i_address(bg_i_address), .bg_i_data(spatial_bg_i_data));

    always @(posedge clk)
    begin
        if (!reset_processing_n)
        begin
            background_index <= 0;
            background_phase <= 0;
            mode_for_window <= 0;
            config_done_seen <= 0;
            spatial_done_seen <= 0;
        end

        else
        begin
            if ((short_arm && !spatial_reference_valid) || clear_reference)
            begin
                background_index <= 0;
                background_phase <= 0;
            end
            if (config_capture)
            begin
                mode_for_window <= config_mode && adaptive_use_cnn;
                config_done_seen <= 0;
                spatial_done_seen <= 0;
            end
            if (config_done)config_done_seen <= 1;
            if (spatial_reference_done)spatial_done_seen <= 1;
            if (!((short_arm && !spatial_reference_valid) || clear_reference)) case
            (background_phase)
            0:if (reference_ready)background_phase <= 1;
            1:background_phase <= 2;
            2:background_phase <= 3;
            3:if (background_valid && bg_write_ready)
            begin
                if (background_index == 256)
                begin
                    background_index <= 257;
                    background_phase <= 4;
                end

                else
                begin
                    background_index <= background_index + 1;
                    background_phase <= 1;
                end
            end
            default:background_phase <= 4;
        endcase
    end
    end
    band_features_pipeline #(.COEFF_DIR(COEFF_DIR)) band(.clk(clk), .rst_n(reset_processing_n),
        .start(features_start),
        .spectrum_write_valid(spectrum_valid), .spectrum_write_ready(spectrum_ready),
        .spectrum_write_address(spectrum_address), .spectrum_write_data(spectrum_data),
        .background_write_valid(background_valid), .background_write_ready(bg_write_ready),
        .background_write_address(background_index), .background_write_data(reference_float),
        .busy(band_busy), .done(band_done), .pipeline_error(band_error),
        .mask_valid(mask_valid), .mask_ready(mask_ready), .mask_address(mask_address), .mask_data(mask_data));
    cnn_mask_reduce reducer(.clk(clk), .rst_n(reset_processing_n), .mask_valid(mask_valid),
        .mask_ready(mask_ready),
        .mask_address(mask_address), .mask_data(mask_data), .weight_valid(cnn_weight_valid),
        .weight_ready(cnn_weight_ready),
        .weight_address(cnn_weight_address), .weight_float(cnn_weight_float), .done(reduced_done),
        .error(reduced_error));
    pl_flat_weights flat(.clk(clk), .rst_n(reset_processing_n), .start(flat_start), .busy(),
        .weight_valid(flat_weight_valid), .weight_ready(flat_weight_ready),
        .weight_address(flat_weight_address),
        .weight_float(flat_weight_float), .done(flat_done), .error(flat_error));
    assign flat_weight_ready = backend_weight_ready && !cnn_required;
    assign cnn_weight_ready = backend_weight_ready && cnn_required;
    wire weight_valid = cnn_required?cnn_weight_valid:flat_weight_valid;
    wire [6:0] weight_address = cnn_required?cnn_weight_address:flat_weight_address;
    wire [31:0] weight_float = cnn_required?cnn_weight_float:flat_weight_float;
    wire air_done, air_busy;
    wire signed [19:0] temperature_correction_q16;
    wire [1:0] air_mode;
    air_speed_correction #(.COEFF_FILE({COEFF_DIR,"/air_delta_coeff.mem"})) air(
        .clk(clk), .rst_n(reset_processing_n), .start(config_capture),
        .temperature_centi(temperature_centi), .temperature_valid(temperature_valid),
        .humidity_raw(humidity_raw), .humidity_valid(temperature_valid && !sensor_faults[2] && !sensor_faults[1]),
        .pressure_pa(pressure_pa), .pressure_valid(pressure_valid && !sensor_faults[5]),
        .busy(air_busy), .done(air_done), .temperature_correction_q16(temperature_correction_q16), .environment_mode(air_mode));
    sensor_config_writer #(.HAS_AIR_SOUND_SPEED(1)) config_writer(.clk(clk), .rst_n(reset_processing_n), .start(config_capture),
        .temperature_centi(temperature_centi), .temperature_valid(temperature_valid),
        .temperature_correction_q16(temperature_correction_q16), .sound_speed_valid(air_done),
        .rotation_q16(world_rotation_q16), .rotation_valid(world_rotation_valid),
        .observations(observation_count > 200?8'd200:observation_count[7:0]),
        .background_observations(8'd20), .background_enabled(config_mode && adaptive_use_cnn),
        .background_ratio_float((config_mode && adaptive_use_cnn)?32'h3f800000:32'd0), .dt_float(dt_float),
        .busy(), .done(config_done), .world_frame_valid(world_frame_valid), .temp_compensated(temp_compensated),
        .write_valid(config_write_valid), .write_ready(config_write_ready), .write_address(config_write_address), .write_float(config_write_float));
    localization_backend_axi #(.HAS_TEMPERATURE_TELEMETRY(1)) backend(.clk(clk), .rst_n(reset_processing_n), .request(backend_request),
        .acquisition_valid(acquisition_valid), .dt_float(dt_float), .weight_write_valid(weight_valid),
        .weight_write_ready(backend_weight_ready), .weight_write_address(weight_address),
        .weight_write_float(weight_float),
        .config_write_valid(config_write_valid), .config_write_ready(config_write_ready),
        .config_write_address(config_write_address), .config_write_float(config_write_float),
        .ready(backend_ready), .busy(backend_busy), .done(backend_done), .fault(backend_fault),
        .load_error(backend_load_error),
        .music_cycles(music_cycles), .track_cycles(track_cycles),
        .m_cov_r_address0(cov_r_address), .m_cov_r_ce0(cov_r_ce), .m_cov_r_q0(cov_r_data),
        .m_cov_i_address0(cov_i_address), .m_cov_i_ce0(cov_i_ce), .m_cov_i_q0(cov_i_data),
        .m_bg_r_address0(bg_r_address), .m_bg_r_ce0(bg_r_ce), .m_bg_r_q0(spatial_bg_r_data),
        .m_bg_i_address0(bg_i_address), .m_bg_i_ce0(bg_i_ce), .m_bg_i_q0(spatial_bg_i_data),
        .active_faults(active_faults), .latched_faults(latched_faults), .sensor_fault_details(sensor_faults),
        .temperature_centi(temperature_centi), .temperature_valid(temperature_valid),
        .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb), .s_axi_wvalid(s_axi_wvalid),
        .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid), .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp), .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(s_axi_rready),
        .irq(irq), .dropped_frames(dropped_frames), .rejected_frames(rejected_frames));
    pl_health_monitor health(.clk(clk), .rst_n(core_reset_n), .clear_latched(clear_fault_history),
        .sample_valid(diagnostic_sample_valid), .pcm(diagnostic_pcm), .orientation_valid(orientation_valid),
        .temperature_valid(temperature_valid), .sensor_faults(sensor_faults), .overrun(overrun),
        .window_clip(window_clip),
        .fft_error(fft_protocol_error), .pipeline_error(pipeline_error), .backend_busy(backend_busy ||
        band_busy),
        .backend_done(backend_done), .backend_fault(backend_fault), .result_frame_committed(backend_done &&
        backend_fault == 0),
        .active_faults(active_faults), .latched_faults(latched_faults), .recovery_request(recovery_request),
        .coordinates_permitted(coordinates_permitted), .restart_count(restart_count));
    pl_window_scheduler scheduler(.clk(clk), .rst_n(reset_processing_n), .enable(coordinates_permitted),
        .acquisition_valid(coordinates_permitted && !clock_fault), .covariance_busy(covariance_busy),
        .observation_count(observation_count), .short_complete(short_complete), .short_error(short_error),
        .config_done(config_done_seen && spatial_done_seen), .features_done(band_done),
        .features_error(band_error),
        .weights_done(reduced_done),
        .cnn_required(cnn_required), .flat_weights_done(flat_done), .flat_weights_error(flat_error),
        .flat_weights_start(flat_start), .backend_ready(backend_ready), .backend_done(backend_done),
        .backend_fault(backend_fault),
        .covariance_clear(covariance_clear), .short_arm(short_arm), .config_capture(config_capture),
        .features_start(features_start), .backend_request(backend_request), .covariance_pause(covariance_pause),
        .window_committed(window_committed), .recovery_request(), .fault(window_fault), .busy(scheduler_busy));
endmodule
