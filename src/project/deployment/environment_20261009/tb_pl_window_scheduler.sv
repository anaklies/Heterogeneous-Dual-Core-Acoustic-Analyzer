`timescale 1ns/1ps

module tb_pl_window_scheduler;

    reg clk = 0;

    always #10 clk = ~clk;
    reg rst_n = 0, enable = 0, acquisition_valid = 1, covariance_busy = 0;
    reg [31:0]observation_count = 0;
    reg short_complete = 0, short_error = 0, config_done = 0, features_done = 0, features_error = 0,
        weights_done = 0, backend_ready = 0, backend_done = 0;
    reg [3:0]backend_fault = 0;
    reg cnn_required = 1, flat_weights_done = 0, flat_weights_error = 0;
    wire flat_weights_start;
    wire covariance_clear, short_arm, config_capture, features_start, backend_request, covariance_pause,
        window_committed, recovery_request, busy;
    wire [3:0]fault;
    pl_window_scheduler #(.ACQUIRE_TIMEOUT(100), .COMPUTE_TIMEOUT(100))dut(.*);
    task tick;
    begin
        @(posedge clk);
        #1;
    end
    endtask
    task reset;
    begin
        @(negedge clk);
        rst_n = 0;
        enable = 0;
        covariance_busy = 0;
        observation_count = 0;
        short_complete = 0;
        short_error = 0;
        config_done = 0;
        features_done = 0;
        weights_done = 0;
        backend_ready = 0;
        backend_done = 0;
        backend_fault = 0;
        acquisition_valid = 1;
        cnn_required = 1;
        flat_weights_done = 0;
        flat_weights_error = 0;
        features_error = 0;
        tick;
        @(negedge clk);
        rst_n = 1;
        tick;
    end
    endtask
    task acquisition;
    begin
        @(negedge clk);
        enable = 1;
        tick;
        tick;
        if (!covariance_clear)$fatal(1, "clear missing");
        @(negedge clk);
        covariance_busy = 1;
        tick;
        if (!short_arm)$fatal(1, "arm missing");
        @(negedge clk);
        covariance_busy = 0;
        observation_count = 20;
        short_complete = 1;
        tick;
        @(negedge clk);
        short_complete = 0;
        tick;
        if (covariance_pause)$fatal(1, "froze at partial boundary");
        @(negedge clk);
        observation_count = 21;
        tick;
        if (!covariance_pause)$fatal(1, "not frozen at boundary");
        tick;
        if (!config_capture)$fatal(1, "config capture missing");
    end
    endtask
    initial
    begin
        reset;
        acquisition;
        @(negedge clk);
        config_done = 1;
        tick;
        if (!features_start)$fatal(1, "features missing");
        @(negedge clk);
        config_done = 0;
        weights_done = 1;
        tick;
        @(negedge clk);
        weights_done = 0;
        features_done = 1;
        tick;
        @(negedge clk);
        features_done = 0;
        backend_ready = 1;
        tick;
        if (!backend_request)$fatal(1, "request missing");
        @(negedge clk);
        backend_ready = 0;
        repeat(3)tick;
        if (!covariance_pause)$fatal(1, "snapshot released during compute");
        @(negedge clk);
        enable = 0;
        backend_done = 1;
        tick;
        if (!window_committed || fault)$fatal(1, "commit failed");
        // Feature done may precede the final reduced weight by several clocks.
        reset;
        acquisition;
        @(negedge clk);
        config_done = 1;
        tick;
        @(negedge clk);
        config_done = 0;
        features_done = 1;
        tick;
        @(negedge clk);
        features_done = 0;
        repeat(3)tick;
        if (dut.state != 6)$fatal(1, "early launch without weights");
        @(negedge clk);
        weights_done = 1;
        tick;
        @(negedge clk);
        weights_done = 0;
        backend_ready = 1;
        tick;
        if (!backend_request)$fatal(1, "done pulses lost in reverse order");
        // Quiet mode does not wait for or start the expensive feature/CNN path.
        reset;
        acquisition;
        @(negedge clk);
        cnn_required = 0;
        features_error = 1;
        config_done = 1;
        tick;
        if (features_start || !flat_weights_start || dut.state != 10)$fatal(1, "quiet bypass not selected");
        @(negedge clk);
        config_done = 0;
        features_error = 1;
        cnn_required = 1;
        repeat(4)tick;
        if (fault || dut.state != 10 || backend_request)$fatal(1, "quiet mode not captured or early request");
        @(negedge clk);
        flat_weights_done = 1;
        tick;
        @(negedge clk);
        flat_weights_done = 0;
        backend_ready = 1;
        tick;
        if (!backend_request)$fatal(1, "quiet request missing");
        @(negedge clk);
        backend_done = 1;
        enable = 0;
        tick;
        if (!window_committed)$fatal(1, "quiet commit missing");
        reset;
        acquisition;
        @(negedge clk);
        cnn_required = 0;
        features_error = 1;
        config_done = 1;
        tick;
        @(negedge clk);
        config_done = 0;
        repeat(105)tick;
        if (fault != 3)$fatal(1, "quiet weights have no timeout");
        reset;
        enable = 1;
        repeat(105)tick;
        if (fault != 2 || dut.state != 9)$fatal(1, "acquire timeout");
        reset;
        acquisition;
        repeat(105)tick;
        if (fault != 3)$fatal(1, "compute timeout");
        reset;
        acquisition;
        @(negedge clk);
        acquisition_valid = 0;
        tick;
        if (fault != 1 || window_committed)$fatal(1, "acq rejection");
        repeat(5)tick;
        if (dut.state != 9 || recovery_request)$fatal(1, "unbounded recovery");
        $display("PASS scheduler: covariance clear/complete-boundary freeze, ordered config/features/weights/compute, snapshot retention, acquire and compute watchdogs, invalid acquisition rejection, bounded recovery");
        $finish;
    end
    initial
    begin
        #100000;
        $fatal(1, "test timeout");
    end
endmodule
