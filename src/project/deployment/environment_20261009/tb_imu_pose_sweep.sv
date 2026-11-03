`timescale 1ns/1ps

module tb_imu_pose_sweep;

    reg clk = 0;

    always #10 clk = ~clk;
    reg rst_n = 0, start = 0;
    reg signed [15:0] qw = 0, qx = 0, qy = 0, qz = 0;
    wire busy, done, valid;
    wire [287:0] matrix_q16;
    reg [287:0] previous;
    reg [63:0] poses[0:63];
    reg [31:0] expected[0:575];
    integer cycles = 0;
    imu_rotation_q16 dut(.*);
    initial
    begin
        $readmemh("imu_poses.mem", poses);
        $readmemh("imu_pose_expected.mem", expected);
        repeat(3)@(negedge clk);
        rst_n = 1;
        for (integer p = 0;p < 64;p = p + 1)
        begin
            {qz, qy, qx, qw} = poses[p];
            previous = matrix_q16;
            start = 1;
            @(negedge clk);
            start = 0;
            cycles = 0;
            while (!done)
            begin
                if (matrix_q16 !== previous)$fatal(1, "mixed pose %0d", p);
                cycles = cycles + 1;
                @(negedge clk);
            end
            if (cycles > 460 || !valid)$fatal(1, "pose latency/validity");
            for (integer k = 0;k < 9;k = k + 1)if (matrix_q16[k * 32 +: 32] !== expected[p * 9 + k])$fatal(1,
                "rotation mismatch pose %0d coefficient %0d", p, k);
            @(negedge clk);
        end
        $display("PASS 64 IMU poses: horizontal, vertical, tilted, yaw, signed quaternion, 576 exact coefficients, atomic updates, <=460 cycles");
        $finish;
    end
    initial
    begin
        #1000000;
        $fatal(1, "pose sweep timeout");
    end
endmodule
