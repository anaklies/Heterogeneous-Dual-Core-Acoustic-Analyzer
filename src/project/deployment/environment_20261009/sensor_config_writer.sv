`timescale 1ns/1ps
// Latch one complete sensor/config epoch before MUSIC can read it.
// Converts bounded Q16 values exactly to IEEE float; temperature rounding is
// <= 1/65536 degree before float conversion. No angle-zero command is sent.

module sensor_config_writer #(parameter HAS_AIR_SOUND_SPEED = 0)
(
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire signed [15:0] temperature_centi,
    input  wire temperature_valid,
    input wire signed [19:0] temperature_correction_q16,
    input wire sound_speed_valid,
    input  wire [287:0] rotation_q16,
    input  wire rotation_valid,
    input  wire [7:0] observations,
    input  wire [7:0] background_observations,
    input  wire background_enabled,
    input  wire [31:0] background_ratio_float,
    input  wire [31:0] dt_float,
    output reg busy,
    output reg done,
    output reg world_frame_valid,
    output reg temp_compensated,
    output wire write_valid,
    input  wire write_ready,
    output wire [3:0] write_address,
    output reg [31:0] write_float
);

    reg signed [31:0] temp_q16;
    reg [161:0] pose;
    wire [161:0] compact_pose;
    reg pose_encoding_ok;
    generate
        for (genvar g = 0;g < 9;g = g + 1)
        begin
            assign compact_pose[g * 18 +: 18] = rotation_q16[g * 32 +: 18];
        end
    endgenerate

    always @*
    begin
        pose_encoding_ok = 1;
        for (integer g = 0;g < 9;g = g + 1)if (rotation_q16[g * 32 + 18 +: 14] !=
            {14{rotation_q16[g * 32 + 17]}})pose_encoding_ok = 0;
    end
    reg [7:0] obs, bgobs;
    reg bg;
    reg [31:0] ratio, dt;
    reg air_ready;
    reg signed [19:0] air_delta;
    reg [3:0] index;
    localparam PREPARE = 0, NORMALIZE = 1, EMIT = 2, TEMP_DIVIDE = 3, AIR_WAIT = 4;
    reg [2:0] state;
    reg [23:0] magnitude;
    reg sign;
    reg [7:0] exponent;
    reg signed [31:0] selected;
    reg [28:0] temp_dividend;
    reg [21:0] temp_quotient;
    reg [6:0] temp_remainder;
    reg [5:0] temp_bits;
    reg temp_negative;
    wire [7:0] temp_trial = {temp_remainder, temp_dividend[28]};
    wire [21:0] temp_next_quotient = {temp_quotient[20:0], temp_trial >= 100};
    wire [15:0] temp_magnitude = temperature_centi < 0?-temperature_centi:temperature_centi;
    wire temp_usable = temperature_valid && temperature_centi >= - 2000 && temperature_centi <= 6000;
    assign write_valid = busy && state == EMIT;
    assign write_address = index;

    always @*
    begin
        case
            (index)
            0:selected = temp_q16;
            1:selected = {8'b0, obs, 16'b0};
            2:selected = {8'b0, bgobs, 16'b0};
            4, 5, 6, 7, 8, 9, 10, 11, 12:selected = $signed(pose[(index - 4) * 18 +: 18]);
            default:selected = 0;
        endcase
    end

    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            busy <= 0;
            done <= 0;
            if (HAS_AIR_SOUND_SPEED && busy && sound_speed_valid)
            begin air_ready <= 1;air_delta <= temperature_correction_q16;end
            index <= 0;
            state <= PREPARE;
            temp_dividend <= 0;
            temp_quotient <= 0;
            temp_remainder <= 0;
            temp_bits <= 0;
            temp_negative <= 0;
            write_float <= 0;
            magnitude <= 0;
            sign <= 0;
            exponent <= 134;
            world_frame_valid <= 0;
            temp_compensated <= 0;
            temp_q16 <= 0;
            pose <= 0;
            obs <= 2;
            bgobs <= 1;
            bg <= 0;
            ratio <= 0;
            dt <= 0;
            air_ready <= 0;air_delta <= 0;
        end

        else
        begin
            done <= 0;
            if (HAS_AIR_SOUND_SPEED && busy && sound_speed_valid)
            begin air_ready <= 1;air_delta <= temperature_correction_q16;end
            if (start && !busy)
            begin
                busy <= 1;
                index <= 0;
                state <= PREPARE;
                world_frame_valid <= rotation_valid && pose_encoding_ok;
                temp_compensated <= temperature_valid && temperature_centi >= - 2000 && temperature_centi <= 6000;
                temp_q16 <= 32'sd1264844;
                air_ready <= 0;
                if(HAS_AIR_SOUND_SPEED)state <= AIR_WAIT;
                if (temp_usable)
                begin
                    state <= TEMP_DIVIDE;
                    temp_dividend <= {temp_magnitude[12:0], 16'b0};
                    temp_quotient <= 0;
                    temp_remainder <= 0;
                    temp_bits <= 29;
                    temp_negative <= temperature_centi[15];
                end
                pose <= (rotation_valid && pose_encoding_ok)?compact_pose:{18'd65536, 18'd0, 18'd0, 18'd0,
                    18'd65536, 18'd0,
                    18'd0, 18'd0, 18'd65536};
                obs <= observations < 2?2:(observations > 200?200:observations);
                bgobs <= background_observations == 0?1:background_observations;
                bg <= background_enabled;
                ratio <= background_ratio_float;
                dt <= dt_float;
            end

            else if (busy) case
            (state)
            TEMP_DIVIDE:
            begin
                temp_dividend <= temp_dividend << 1;
                temp_quotient <= temp_next_quotient;
                temp_remainder <= temp_trial >= 100?temp_trial - 100:temp_trial;
                temp_bits <= temp_bits - 1;
                if (temp_bits == 1)
                begin
                    temp_q16 <= temp_negative?-$signed({10'b0, temp_next_quotient}):$signed({10'b0, temp_next_quotient});
                    state <= HAS_AIR_SOUND_SPEED ? AIR_WAIT : PREPARE;
                end
            end
            AIR_WAIT:if (air_ready || sound_speed_valid)
            begin
                temp_q16 <= temp_q16 + $signed(sound_speed_valid ? temperature_correction_q16 : air_delta);
                state <= PREPARE;
            end
            PREPARE:
            begin
                if (index == 3 || index >= 13)
                begin
                    case
                        (index)3:write_float <= bg?32'h3f800000:0;
                        13:write_float <= dt;
                        14:write_float <= 0;
                        default:write_float <= ratio;
                    endcase
                    state <= EMIT;
                end

                else if (index >= 4 && index <= 12 && (selected > 65536 || selected < -65536))
                begin
                    write_float <= 0;
                    world_frame_valid <= 0;
                    state <= EMIT;
                end

                else if (selected == 0)
                begin
                    write_float <= 0;
                    state <= EMIT;
                end

                else
                begin
                    magnitude <= selected < 0?-selected:selected;
                    sign <= selected[31];
                    exponent <= 134;
                    state <= NORMALIZE;
                end
            end
            NORMALIZE:if (magnitude == 0)
            begin
                write_float <= 0;
                world_frame_valid <= 0;
                state <= EMIT;
            end

            else if (magnitude[23])
            begin
                write_float <= {sign, exponent, magnitude[22:0]};
                state <= EMIT;
            end

            else
            begin
                magnitude <= magnitude << 1;
                exponent <= exponent - 1;
            end
            EMIT:if (write_ready)
            begin
                if (index == 15)
                begin
                    busy <= 0;
                    done <= 1;
                end

                else
                begin
                    index <= index + 1;
                    state <= PREPARE;
                end
            end
            default:state <= PREPARE;
        endcase
    end
    end
endmodule
