`timescale 1ns/1ps
module tb_pose;
    `include "pose_path.svh"
    reg clk=0;always #10 clk=~clk;
    reg rst_n=0,start=0,direction_valid=1,orientation_valid=1,heading_referenced=1;
    reg [31:0] frame_id=0;
    reg signed [15:0] ux=0,uy=0,uz=0,qw=0,qx=0,qy=0,qz=0;
    wire busy,done,output_direction_valid,world_valid,world_heading_referenced,rejected_start;
    wire [31:0] output_frame_id;
    wire signed [15:0] out_x,out_y,out_z;
    wire [15:0] recovery_count;
    direction_pose_transform dut(.*);
    reg [161:0] rows[0:31];
    integer i,cycles,ex,ey,ez;
    initial begin
        $readmemh(DATA_FILE,rows);
        repeat(3)@(negedge clk);rst_n=1;
        for(i=0;i<32;i=i+1)begin
            @(negedge clk);
            {direction_valid,orientation_valid}=rows[i][161:160];
            {qz,qy,qx,qw,uz,uy,ux}=rows[i][111:0];
            ex=$signed(rows[i][127:112]);ey=$signed(rows[i][143:128]);ez=$signed(rows[i][159:144]);
            frame_id=i;start=1;@(negedge clk);start=0;cycles=0;
            while(!done&&cycles<1100)begin @(negedge clk);cycles=cycles+1;end
            if(!done||output_frame_id!=i||output_direction_valid!=direction_valid) $fatal(1,"pose transaction mismatch");
            if(world_valid!=(direction_valid&&orientation_valid))$fatal(1,"pose validity mismatch");
            if(out_x-ex>5||ex-out_x>5||out_y-ey>5||ey-out_y>5||out_z-ez>5||ez-out_z>5)$fatal(1,"pose numerical mismatch %0d",i);
        end
        if(recovery_count!=0)$fatal(1,"unexpected pose timeout");
        $display("POSE_TRANSFORM_PASS32 mounting stale invalid");$finish;
    end
endmodule
