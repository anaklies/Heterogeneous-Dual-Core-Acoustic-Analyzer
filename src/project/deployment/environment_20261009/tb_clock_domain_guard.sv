`timescale 1ns/1ps

module tb_clock_domain_guard;

    reg ref_clk = 0;

    always #10 ref_clk = ~ref_clk;
    reg rst_n = 0, heartbeat = 0, clock_locked = 1, run = 1;
    wire clock_fault, reset_clock_generator;
    wire [3:0] restart_count;
    integer tick = 0, resets = 0;
    reg was_reset = 0;
    clock_domain_guard #(.TIMEOUT(10), .STARTUP(20), .RESET_HOLD(3), .GOOD_TICKS(20),
        .MAX_RETRIES(3)) dut(.*);

    always @(negedge ref_clk)
    begin
        tick = tick + 1;
        if (run && tick % 3 == 0)heartbeat = ~heartbeat;
        if (reset_clock_generator && !was_reset)resets = resets + 1;
        was_reset = reset_clock_generator;
    end
    initial
    begin
        repeat(4)@(posedge ref_clk);
        rst_n = 1;
        repeat(60)@(negedge ref_clk);
        if (clock_fault || restart_count || resets)$fatal(1, "normal clock falsely restarted");
        run = 0;
        repeat(110)@(negedge ref_clk);
        if (!clock_fault || restart_count != 3 || resets != 3 || reset_clock_generator)$fatal(1,
            "stopped clock recovery not bounded");
        run = 1;
        repeat(40)@(negedge ref_clk);
        if (clock_fault || restart_count)$fatal(1, "restored clock did not clear after stable period");
        clock_locked = 0;
        repeat(5)@(negedge ref_clk);
        if (!clock_fault)$fatal(1, "lock loss not reported");
        clock_locked = 1;
        repeat(60)@(negedge ref_clk);
        if (clock_fault)$fatal(1, "lock restore");
        $display("PASS independent clock guard: normal startup, stopped heartbeat, bounded PLL restart, stable rearm, lock loss");
        $finish;
    end
    initial
    begin
        #100000;
        $fatal(1, "clock guard timeout");
    end
endmodule
