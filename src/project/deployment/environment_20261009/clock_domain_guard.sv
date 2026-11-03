`timescale 1ns/1ps
// Independent reference-domain watchdog. It cannot recover loss of the reference clock/power.

module clock_domain_guard #(
    parameter TIMEOUT = 250000,
    STARTUP = 500000,
    RESET_HOLD = 32,
    GOOD_TICKS = 500000,
    MAX_RETRIES = 3
)
(
    input  wire ref_clk,
    input  wire rst_n,
    input  wire heartbeat,
    input  wire clock_locked,
    output wire clock_fault,
    output wire reset_clock_generator,
    output reg [3:0] restart_count
);

    (* ASYNC_REG="TRUE" *)reg [1:0] hb_sync, lock_sync;
    reg previous;
    reg [($clog2(TIMEOUT+1)>0?$clog2(TIMEOUT+1):1)-1:0] age;
    reg [($clog2(STARTUP+1)>0?$clog2(STARTUP+1):1)-1:0] startup_ticks;
    reg [($clog2(GOOD_TICKS+1)>0?$clog2(GOOD_TICKS+1):1)-1:0] good_ticks;
    reg [($clog2(RESET_HOLD+1)>0?$clog2(RESET_HOLD+1):1)-1:0] hold;
    assign clock_fault = !lock_sync[1] || (startup_ticks == 0 && age >= TIMEOUT);
    assign reset_clock_generator = hold != 0;

    always @(posedge ref_clk)
    begin
        if (!rst_n)
        begin
            hb_sync <= 0;
            lock_sync <= 0;
            previous <= 0;
            age <= 0;
            startup_ticks <= STARTUP;
            good_ticks <= 0;
            hold <= 0;
            restart_count <= 0;
        end

        else
        begin
            hb_sync <= {hb_sync[0], heartbeat};
            lock_sync <= {lock_sync[0], clock_locked};
            previous <= hb_sync[1];
            if (hb_sync[1] != previous)age <= 0;
            else if (age < TIMEOUT)age <= age + 1;
            if (hold != 0)hold <= hold - 1;
            if (startup_ticks != 0)
            begin
                startup_ticks <= startup_ticks - 1;
                good_ticks <= 0;
            end

            else if (clock_fault)
            begin
                good_ticks <= 0;
                if (hold == 0 && restart_count < MAX_RETRIES)
                begin
                    hold <= RESET_HOLD;
                    startup_ticks <= STARTUP;
                    age <= 0;
                    restart_count <= restart_count + 1;
                end
            end

            else
            begin
                if (good_ticks < GOOD_TICKS)good_ticks <= good_ticks + 1;
                else restart_count <= 0;
            end
        end
    end
endmodule
