`timescale 1ns / 1ps

module i2s_rx_6ch (
    input  wire clk_audio,
    input  wire rst_n,

    input  wire i2s_ws,
    input  wire bclk_rise_ce,

    input  wire mic1_sd,
    input  wire mic2_sd,
    input  wire mic3_sd,
    input  wire mic4_sd,
    input  wire mic5_sd,
    input  wire mic6_sd,

    output reg signed [23:0] mic1_data,
    output reg signed [23:0] mic2_data,
    output reg signed [23:0] mic3_data,
    output reg signed [23:0] mic4_data,
    output reg signed [23:0] mic5_data,
    output reg signed [23:0] mic6_data,

    output reg sample_valid
);

    // 当前32-bit slot中的位置
    reg [5:0] slot_bit;

    // 上一拍WS
    reg ws_d;

    // 只有看到真正的 Right -> Left 边界以后
    // 才认为Left slot同步完成
    reg left_synced;

    // 六路移位寄存器
    reg [23:0] shift1;
    reg [23:0] shift2;
    reg [23:0] shift3;
    reg [23:0] shift4;
    reg [23:0] shift5;
    reg [23:0] shift6;


    always @(posedge clk_audio or negedge rst_n)
    begin
        if (!rst_n)
        begin
            slot_bit    <= 6'd0;
            ws_d        <= 1'b0;
            left_synced <= 1'b0;

            shift1 <= 24'd0;
            shift2 <= 24'd0;
            shift3 <= 24'd0;
            shift4 <= 24'd0;
            shift5 <= 24'd0;
            shift6 <= 24'd0;

            mic1_data <= 24'sd0;
            mic2_data <= 24'sd0;
            mic3_data <= 24'sd0;
            mic4_data <= 24'sd0;
            mic5_data <= 24'sd0;
            mic6_data <= 24'sd0;

            sample_valid <= 1'b0;
        end

        else
        begin
            // 默认只产生一个clk_audio周期的有效脉冲
            sample_valid <= 1'b0;

            // 保存WS
            ws_d <= i2s_ws;


            // ====================================================
            // WS发生变化
            // ====================================================
            if (i2s_ws != ws_d)
            begin
                // 新slot开始
                slot_bit <= 6'd0;

                // Right -> Left
                // 说明真正进入一个新的Left slot
                if ((ws_d == 1'b1) && (i2s_ws == 1'b0))
                    left_synced <= 1'b1;

                // Left -> Right
                else
                    left_synced <= 1'b0;
            end


            // ====================================================
            // BCLK上升沿采样
            // ====================================================
            else if (bclk_rise_ce)
            begin

                // =================================================
                // LEFT SLOT
                // 六个INMP441全部L/R接GND
                // =================================================
                if (i2s_ws == 1'b0)
                begin

                    if (left_synced)
                    begin

                        // slot_bit = 0：
                        // I2S的一位延迟，不采数据
                        //
                        // slot_bit = 1~24：
                        // D23 ~ D0

                        if ((slot_bit >= 6'd1) &&
                            (slot_bit <= 6'd24))
                        begin
                            shift1 <= {shift1[22:0], mic1_sd};
                            shift2 <= {shift2[22:0], mic2_sd};
                            shift3 <= {shift3[22:0], mic3_sd};
                            shift4 <= {shift4[22:0], mic4_sd};
                            shift5 <= {shift5[22:0], mic5_sd};
                            shift6 <= {shift6[22:0], mic6_sd};


                            // 收到第24位，也就是D0
                            if (slot_bit == 6'd24)
                            begin
                                mic1_data <= {shift1[22:0], mic1_sd};
                                mic2_data <= {shift2[22:0], mic2_sd};
                                mic3_data <= {shift3[22:0], mic3_sd};
                                mic4_data <= {shift4[22:0], mic4_sd};
                                mic5_data <= {shift5[22:0], mic5_sd};
                                mic6_data <= {shift6[22:0], mic6_sd};

                                sample_valid <= 1'b1;
                            end
                        end
                    end


                    if (slot_bit < 6'd31)
                        slot_bit <= slot_bit + 1'b1;
                end


                // =================================================
                // RIGHT SLOT
                // 当前不采数据，只维持slot计数
                // =================================================
                else
                begin
                    if (slot_bit < 6'd31)
                        slot_bit <= slot_bit + 1'b1;
                end

            end

        end
    end

endmodule