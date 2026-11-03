`timescale 1ns / 1ps
// Array-local Q2.14 unit vector to world Q2.14, with exact fixed mounting.
// Inherited quaternion core ALREADY includes Rz(-90deg). Do not rotate twice.
module direction_pose_transform #(
    parameter integer TIMEOUT_CYCLES=1024
)(
    input wire clk,rst_n,start,
    input wire [31:0] frame_id,
    input wire direction_valid,orientation_valid,heading_referenced,
    input wire signed [15:0] ux,uy,uz,qw,qx,qy,qz,
    output reg busy,done,
    output reg [31:0] output_frame_id,
    output reg output_direction_valid,world_valid,world_heading_referenced,
    output reg signed [15:0] out_x,out_y,out_z,
    output reg [15:0] recovery_count,
    output reg rejected_start
);
    localparam integer CW=$clog2(TIMEOUT_CYCLES+1);
    reg [2:0] state;
    reg core_start,core_reset;
    wire core_busy,core_done,core_valid;
    wire [287:0] matrix;
    reg [287:0] rotation;
    reg signed [15:0] vector[0:2];
    reg signed [15:0] w,x,y,z;
    reg valid_latch,pose_latch,heading_latch;
    reg [31:0] frame_latch;
    reg [CW-1:0] age;
    reg [1:0] row,col;
    reg signed [49:0] sum;
    reg signed [47:0] product;
    wire signed [31:0] coefficient=rotation[(row*3+col)*32+:32];
    wire signed [49:0] next_sum=sum+$signed({{2{product[47]}},product});
    wire signed [49:0] scaled=next_sum>>>16;
    wire signed [15:0] saturated=scaled>32767?16'sh7fff:(scaled< -32768?16'sh8000:scaled[15:0]);
    s7_imu_rotation_q16 core(.clk(clk),.rst_n(rst_n&&!core_reset),.start(core_start),
        .qw(w),.qx(x),.qy(y),.qz(z),.busy(core_busy),.done(core_done),.valid(core_valid),.matrix_q16(matrix));
    initial if(TIMEOUT_CYCLES<600) $fatal(1,"pose timeout shorter than inherited divider latency");
    always @(posedge clk) begin
        if(!rst_n) begin
            state<=0;busy<=0;done<=0;core_start<=0;core_reset<=0;age<=0;
            output_frame_id<=0;output_direction_valid<=0;world_valid<=0;world_heading_referenced<=0;
            out_x<=0;out_y<=0;out_z<=0;recovery_count<=0;rejected_start<=0;
            valid_latch<=0;pose_latch<=0;heading_latch<=0;frame_latch<=0;
            w<=0;x<=0;y<=0;z<=0;row<=0;col<=0;sum<=0;product<=0;rotation<=0;
        end else begin
            done<=0;core_start<=0;core_reset<=0;rejected_start<=0;
            if(start&&busy) rejected_start<=1;
            if(busy) age<=age+1;
            if(busy&&age>=TIMEOUT_CYCLES-1) begin
                state<=0;busy<=0;done<=1;core_reset<=1;
                output_frame_id<=frame_latch;output_direction_valid<=valid_latch;
                world_valid<=0;world_heading_referenced<=0;
                out_x<=vector[0];out_y<=vector[1];out_z<=vector[2];
                if(recovery_count!=16'hffff) recovery_count<=recovery_count+1;
            end else case(state)
                0:if(start) begin
                    busy<=1;age<=0;frame_latch<=frame_id;valid_latch<=direction_valid;
                    pose_latch<=orientation_valid;heading_latch<=heading_referenced;
                    vector[0]<=ux;vector[1]<=uy;vector[2]<=uz;
                    w<=qw;x<=qx;y<=qy;z<=qz;state<=1;
                end
                1:if(!valid_latch||!pose_latch) begin
                    out_x<=valid_latch?vector[0]:16'sd0;out_y<=valid_latch?vector[1]:16'sd0;out_z<=valid_latch?vector[2]:16'sd0;
                    output_direction_valid<=valid_latch;world_valid<=0;world_heading_referenced<=0;
                    output_frame_id<=frame_latch;done<=1;busy<=0;state<=0;
                end else begin core_start<=1;state<=2;end
                2:if(core_done) begin
                    if(core_valid) begin rotation<=matrix;row<=0;col<=0;sum<=0;state<=3;end
                    else begin
                        pose_latch<=0;state<=1;
                    end
                end
                3:begin product<=coefficient*$signed(vector[col]);state<=4;end
                4:begin
                    if(col==2) begin
                        case(row)0:out_x<=saturated;1:out_y<=saturated;2:out_z<=saturated;endcase
                        col<=0;sum<=0;
                        if(row==2) begin
                            output_frame_id<=frame_latch;output_direction_valid<=1;world_valid<=1;
                            world_heading_referenced<=heading_latch;done<=1;busy<=0;state<=0;
                        end else begin row<=row+1;state<=3;end
                    end else begin sum<=next_sum;col<=col+1;state<=3;end
                end
            endcase
        end
    end
endmodule
