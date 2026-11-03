`timescale 1ns/1ps

module tb_pl_health_monitor;

    reg clk = 0;

    always #10 clk = ~clk;
    reg rst_n = 0, clear_latched = 0, sample_valid = 0;
    reg [143:0] pcm = 0;
    reg orientation_valid = 1, temperature_valid = 1;
    reg [7:0] sensor_faults = 0;
    reg overrun = 0, window_clip = 0, fft_error = 0, pipeline_error = 0, backend_busy = 0, backend_done = 0;
    reg [3:0] backend_fault = 0;
    reg result_frame_committed = 0;
    wire [31:0] active_faults, latched_faults;
    wire recovery_request, coordinates_permitted;
    wire [3:0] restart_count;
    integer pulses = 0;
    pl_health_monitor #(.STUCK_SAMPLES(8), .CLIP_SAMPLES(3), .SAMPLE_TIMEOUT(100), .STAGE_TIMEOUT(30),
        .COOLDOWN(5),
        .MAX_RETRIES(3)) dut(.*);

    always @(posedge clk)if (recovery_request)pulses = pulses + 1;
    task audio(input integer mode);
    begin
        for (integer t = 0;t < 12;t = t + 1)
        begin
            @(negedge clk);
            sample_valid = 1;
            for (integer c = 0;c < 6;c = c + 1)pcm[c * 24 +: 24] = 100 * (c + 1) + t;
            if (mode == 1)pcm[2 * 24 +: 24] = 0;
            if (mode == 2)pcm[3 * 24 +: 24] = 24'h7fffff;
            if (mode == 3)pcm[4 * 24 +: 24] = pcm[23:0];
        end
        @(negedge clk);
        sample_valid = 0;
    end
    endtask
    task fault_pulse;
    begin
        @(negedge clk);
        pipeline_error = 1;
        repeat(3)@(negedge clk);
        pipeline_error = 0;
        repeat(8)@(negedge clk);
    end
    endtask
    initial
    begin
        repeat(3)@(negedge clk);
        rst_n = 1;
        audio(0);
        if (active_faults[17:0] || !coordinates_permitted)$fatal(1, "normal audio rejected");
        audio(1);
        if (!active_faults[2] || coordinates_permitted)$fatal(1, "stuck channel");
        audio(0);
        if (active_faults[2] || !coordinates_permitted || !latched_faults[2])$fatal(1,
            "channel recovery/history");
        audio(2);
        if (!active_faults[9] || coordinates_permitted)$fatal(1, "clipping");
        audio(0);
        audio(3);
        if (!active_faults[15] || !coordinates_permitted)$fatal(1, "duplicate diagnostic");
        audio(0);
        orientation_valid = 0;
        temperature_valid = 0;
        sensor_faults = 8'h0f;
        repeat(2)@(negedge clk);
        if (active_faults[23:18] != 6'b111111 || !coordinates_permitted)$fatal(1,
            "sensor fallback/fault causes");
        orientation_valid = 1;
        temperature_valid = 1;
        sensor_faults = 0;
        repeat(101)@(negedge clk);
        if (!active_faults[17] || coordinates_permitted)$fatal(1, "sample timeout");
        audio(0);
        if (active_faults[17] || !coordinates_permitted)$fatal(1, "audio restart");
        fault_pulse();
        fault_pulse();
        fault_pulse();
        fault_pulse();
        if (pulses != 3 || restart_count != 3 || !active_faults[31] || coordinates_permitted)$fatal(1,
            "bounded restarts");
        // Reset history clear must not erase a still active failure or restart budget.
        clear_latched = 1;
        @(negedge clk);
        clear_latched = 0;
        @(negedge clk);
        if (!latched_faults[31] || restart_count != 3)$fatal(1, "clear bypassed active failure");
        $display("PASS health: stream loss, six channel checks, clipping, duplicates, sensor causes, fallback, sticky history, bounded recovery");
        $finish;
    end
    initial
    begin
        #100000;
        $fatal(1, "test timeout");
    end
endmodule
