`timescale 1ns/1ps
// Normalized quaternion -> array-to-world rotation, signed Q16.16.
// Mount: IMU +X toward MIC1 (+Y array), +Z toward upper layer.
// One restoring divider serves all nine coefficients; no PS computation.

module imu_rotation_q16
(
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire signed [15:0] qw,
    input  wire signed [15:0] qx,
    input  wire signed [15:0] qy,
    input  wire signed [15:0] qz,
    output reg busy,
    output reg done,
    output reg valid,
    output reg [287:0] matrix_q16
);

    reg [143:0] pending_matrix;
    wire [255:0] expanded_pending;
    generate for(genvar e=0;e<8;e=e+1) begin: expand_pose
        assign expanded_pending[e*32+:32]={{14{pending_matrix[e*18+17]}},pending_matrix[e*18+:18]};
    end endgenerate
    reg signed [15:0] w, x, y, z;
    reg [3:0] index;
    reg [1:0] state;
    wire signed [31:0] ww = w * w, xx = x * x, yy = y * y, zz = z * z, xy = x * y, xz = x * z,
        yz = y * z,
        xw = x * w, yw = y * w, zw = z * w;
    (* use_dsp="yes" *) wire signed [33:0] norm = $signed({2'b0, ww}) + $signed({2'b0, xx}) + $signed({2'b0,
        yy}) + $signed({2'b0, zz});
    reg signed [33:0] numerator;
    reg [47:0] dividend;
    reg [16:0] quotient;
    reg [33:0] remainder, divisor;
    reg [5:0] bits;
    reg negative;
    wire [34:0] trial = {remainder, dividend[47]};
    (* use_dsp="yes" *) wire signed [35:0] division_difference = $signed({1'b0,trial}) - $signed({2'b0,divisor});
    wire division_accept = !division_difference[35];

    // Select operands first, then reuse the same exact arithmetic for
    // all nine matrix entries. No approximation or quaternion change.
    reg signed [31:0] operand_a, operand_b;
    reg subtract_b, negate_pair;
    reg [1:0] norm_kind;
    (* use_dsp="yes" *) wire signed [34:0] pair_result =
        $signed(operand_a) + (subtract_b ? -$signed({{3{operand_b[31]}},operand_b}) : $signed({{3{operand_b[31]}},operand_b}));
    wire signed [34:0] doubled = pair_result <<< 1;
    wire signed [34:0] signed_pair = negate_pair ? -doubled : doubled;
    wire signed [34:0] norm_term = norm_kind==1 ? $signed(norm) : (norm_kind==2 ? -$signed({norm[33],norm}) : 35'sd0);
    (* use_dsp="yes" *) wire signed [34:0] shared_numerator = signed_pair + norm_term;
    always @*
    begin
        operand_a=xx;operand_b=yy;subtract_b=0;negate_pair=1;norm_kind=1;
        case(index)
            0:begin operand_a=xy;operand_b=zw;subtract_b=1;negate_pair=1;norm_kind=0;end
            1:begin operand_a=yy;operand_b=zz;end
            2:begin operand_a=xz;operand_b=yw;negate_pair=0;norm_kind=0;end
            3:begin operand_a=xx;operand_b=zz;negate_pair=0;norm_kind=2;end
            4:begin operand_a=xy;operand_b=zw;negate_pair=0;norm_kind=0;end
            5:begin operand_a=yz;operand_b=xw;subtract_b=1;negate_pair=0;norm_kind=0;end
            6:begin operand_a=yz;operand_b=xw;norm_kind=0;end
            7:begin operand_a=xz;operand_b=yw;subtract_b=1;negate_pair=0;norm_kind=0;end
        endcase
        numerator=shared_numerator;
    end
    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            state <= 0;
            busy <= 0;
            done <= 0;
            valid <= 0;
            index <= 0;
            w <= 0;
            x <= 0;
            y <= 0;
            z <= 0;
            matrix_q16 <= 0;
            pending_matrix <= 0;
        end

        else
        begin
            done <= 0;
            case
                (state)
                0:if (start)
                begin
                    w <= qw;
                    x <= qx;
                    y <= qy;
                    z <= qz;
                    busy <= 1;
                    index <= 0;
                    state <= 1;
                end
                1:if (norm <= 0)
                begin
                    busy <= 0;
                    valid <= 0;
                    done <= 1;
                    state <= 0;
                end

                else
                begin
                    divisor <= norm;
                    dividend <= (numerator < 0?-numerator:numerator) << 16;
                    negative <= numerator < 0;
                    remainder <= 0;
                    quotient <= 0;
                    bits <= 48;
                    state <= 2;
                end
                2:
                begin
                    dividend <= dividend << 1;
                    quotient <= (quotient << 1) | (division_accept);
                    remainder <= division_accept?division_difference[33:0]:trial;
                    bits <= bits - 1;
                    if (bits == 1)state <= 3;
                end
                3:
                begin
                    // Publish all nine coefficients atomically; never expose a mixed pose.
                    if (index < 8) pending_matrix[index * 18 +: 18] <= negative?-$signed({1'b0, quotient[16:0]}):{1'b0, quotient[16:0]};
                    if (index == 8)
                    begin
                        matrix_q16 <= {negative?-$signed({15'b0, quotient[16:0]}):{15'b0, quotient[16:0]}, expanded_pending};
                        busy <= 0;
                        done <= 1;
                        valid <= 1;
                        state <= 0;
                    end

                    else
                    begin
                        index <= index + 1;
                        state <= 1;
                    end
                end
            endcase
        end
    end
endmodule
