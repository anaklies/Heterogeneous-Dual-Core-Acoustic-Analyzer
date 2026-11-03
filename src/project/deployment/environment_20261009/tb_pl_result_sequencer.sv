`timescale 1ns/1ps

module tb_pl_result_sequencer;

    reg clk = 0;

    always #10 clk = ~clk;
    reg rst_n = 0, request = 0, abort_window = 0;
    reg [31:0] dt_float = 32'h3e800000;
    wire ready, busy, done;
    wire [3:0] fault;
    wire [31:0] music_cycles, track_cycles, track_dt;
    wire music_start, track_start, cores_reset, track_reset;
    reg music_done = 0, track_done = 0, music_we0 = 0, music_we1 = 0, track_read0 = 0, track_read1 = 0,
        track_we0 = 0, track_we1 = 0, result_ready = 0;
    reg [5:0] music_address0 = 0, music_address1 = 0, track_address0 = 0, track_address1 = 0,
        track_read_address0 = 0, track_read_address1 = 0;
    reg [31:0] music_data0 = 0, music_data1 = 0, track_data0 = 0, track_data1 = 0;
    wire [31:0] track_q0, track_q1, result_data;
    wire result_valid;
    wire [5:0] result_address;
    pl_result_sequencer #(.MUSIC_TIMEOUT(200), .TRACK_TIMEOUT(200), .OUTPUT_TIMEOUT(400)) dut(.*);
    task launch;
    begin
        @(negedge clk);
        request = 1;
        @(negedge clk);
        request = 0;
    end
    endtask
    task music_frame;
    begin
        for (integer i = 0;i < 26;i = i + 1)
        begin
            @(negedge clk);
            music_we0 = 1;
            music_we1 = 1;
            music_address0 = 2 * i;
            music_address1 = 2 * i + 1;
            music_data0 = 100 + 2 * i;
            music_data1 = 101 + 2 * i;
        end
        @(negedge clk);
        music_we0 = 0;
        music_we1 = 0;
        music_done = 1;
        @(negedge clk);
        music_done = 0;
    end
    endtask
    task track_frame(input integer count);
    begin
        for (integer i = 0;i < 26;i = i + 1)
        begin
            @(negedge clk);
            track_we0 = 1;
            track_we1 = 1;
            track_address0 = 2 * i;
            track_address1 = 2 * i + 1;
            track_data0 = i == 0?count:200 + 2 * i;
            track_data1 = 201 + 2 * i;
        end
        @(negedge clk);
        track_we0 = 0;
        track_we1 = 0;
        track_done = 1;
        @(negedge clk);
        track_done = 0;
    end
    endtask
    initial
    begin
        repeat(3)@(negedge clk);
        rst_n = 1;
        launch();
        if (!music_start || !busy)$fatal(1, "launch");
        music_frame();
        if (!track_start || !track_reset)$fatal(1, "initial tracking reset");
        track_read0 = 1;
        track_read1 = 1;
        track_read_address0 = 4;
        track_read_address1 = 5;
        @(negedge clk);
        if (track_q0 != 104 || track_q1 != 105)$fatal(1, "synchronous dual read");
        track_read0 = 0;
        track_read1 = 0;
        track_frame(2);
        wait(result_valid);
        @(negedge clk);
        if (!result_valid)$fatal(1, "missing publication");
        for (integer i = 0;i < 52;i = i + 1)
        begin
            wait(result_valid);
            if (result_address != i || result_data != (i == 0?2:200 + i))$fatal(1, "result frame");
            repeat(2)
            begin
                @(negedge clk);
                if (result_address != i || !result_valid)$fatal(1, "backpressure");
            end
            result_ready = 1;
            @(negedge clk);
            result_ready = 0;
        end
        if (!done || !ready || fault)$fatal(1, "complete transaction");
        launch();
        music_done = 1;
        @(negedge clk);
        music_done = 0;
        wait(done);
        @(negedge clk);
        if (fault != 2 || result_valid)$fatal(1, "incomplete music accepted");
        launch();
        wait(done);
        @(negedge clk);
        if (fault != 3 || result_valid)$fatal(1, "music watchdog");
        launch();
        music_frame();
        track_frame(4);
        wait(done);
        @(negedge clk);
        if (fault != 7 || result_valid)$fatal(1, "invalid source count");
        launch();
        music_frame();
        wait(done);
        @(negedge clk);
        if (fault != 6)$fatal(1, "tracking watchdog");
        // The receiver may disappear; a stalled publish must not wait forever.
        launch();
        music_frame();
        track_frame(1);
        wait(result_valid);
        wait(done);
        @(negedge clk);
        if (fault != 9 || result_valid || !ready)$fatal(1, "output stall did not recover");
        launch();
        abort_window = 1;
        @(negedge clk);
        abort_window = 0;
        wait(done);
        @(negedge clk);
        if (fault != 10 || result_valid)$fatal(1, "invalid acquisition did not abort");
        // Conflicting writes must never publish a partial or corrupted result.
        launch();
        @(negedge clk);
        music_we0 = 1;
        music_we1 = 1;
        music_address0 = 3;
        music_address1 = 3;
        music_data0 = 1;
        music_data1 = 2;
        @(negedge clk);
        music_we0 = 0;
        music_we1 = 0;
        wait(done);
        @(negedge clk);
        if (fault != 1 || result_valid)$fatal(1, "conflicting MUSIC writes accepted");
        launch();
        music_frame();
        @(negedge clk);
        track_we0 = 1;
        track_we1 = 1;
        track_address0 = 8;
        track_address1 = 8;
        track_data0 = 1;
        track_data1 = 2;
        @(negedge clk);
        track_we0 = 0;
        track_we1 = 0;
        wait(done);
        @(negedge clk);
        if (fault != 4 || result_valid)$fatal(1, "conflicting TRACK writes accepted");
        launch();
        @(negedge clk);
        music_we0 = 1;
        music_address0 = 63;
        music_data0 = 1;
        @(negedge clk);
        music_we0 = 0;
        wait(done);
        @(negedge clk);
        if (fault != 1 || result_valid)$fatal(1, "out-of-range MUSIC write accepted");
        launch();
        music_frame();
        @(negedge clk);
        track_we0 = 1;
        track_address0 = 63;
        track_data0 = 1;
        @(negedge clk);
        track_we0 = 0;
        wait(done);
        @(negedge clk);
        if (fault != 4 || result_valid)$fatal(1, "out-of-range TRACK write accepted");
        $display("PASS result sequencer: dual ports, atomic frames, backpressure, partial rejection, both watchdogs, count guard, conflicting writes, invalid addresses, receiver stall timeout, recovery");
        $finish;
    end
    initial
    begin
        #100000;
        $fatal(1, "test timeout");
    end
endmodule
