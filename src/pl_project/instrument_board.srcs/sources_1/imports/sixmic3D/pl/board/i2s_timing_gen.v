`timescale 1ns / 1ps

module i2s_timing_gen (
    input  wire clk_audio,      // Clocking Wizard 输出，约 49.16201 MHz
    input  wire rst_n,          // 低电平复位

    output reg  i2s_bclk,       // I2S bit clock，约 3.0726 MHz
    output reg  i2s_ws,         // I2S word select，约 48.01 kHz

    // 下面三个信号不给麦克风，用于后面的接收模块
    output reg  bclk_rise_ce,   // BCLK 上升沿时，在 clk_audio 域产生1周期脉冲
    output reg  bclk_fall_ce,   // BCLK 下降沿时，在 clk_audio 域产生1周期脉冲
    output reg  frame_start_ce  // 每个新的64-bit I2S帧开始时产生1周期脉冲
);

    // ============================================================
    // clk_audio ≈ 49.16201 MHz
    //
    // BCLK:
    //     49.16201 MHz / 16
    //     ≈ 3.0726256 MHz
    //
    // i2s_bclk 每8个 clk_audio 周期翻转一次：
    //     8周期低 + 8周期高 = 16周期
    // ============================================================

    reg [2:0] bclk_div_cnt;

    // 记录当前位于64-bit I2S帧中的第几个 BCLK
    //
    // 0~31  : Left slot
    // 32~63 : Right slot
    reg [5:0] bit_cnt;


    always @(posedge clk_audio or negedge rst_n)
    begin
        if (!rst_n)
        begin
            bclk_div_cnt <= 3'd0;

            i2s_bclk <= 1'b0;
            i2s_ws   <= 1'b0;

            bit_cnt <= 6'd0;

            bclk_rise_ce  <= 1'b0;
            bclk_fall_ce  <= 1'b0;
            frame_start_ce <= 1'b0;
        end

        else
        begin
            // 这些都是单周期脉冲，所以默认每个 clk_audio 周期先清零
            bclk_rise_ce   <= 1'b0;
            bclk_fall_ce   <= 1'b0;
            frame_start_ce <= 1'b0;


            // ----------------------------------------------------
            // 每8个 clk_audio 周期翻转一次 BCLK
            // ----------------------------------------------------
            if (bclk_div_cnt == 3'd7)
            begin
                bclk_div_cnt <= 3'd0;


                // =================================================
                // 当前 BCLK = 0
                // 下一拍将变成 1
                // => BCLK 上升沿
                // =================================================
                if (i2s_bclk == 1'b0)
                begin
                    i2s_bclk <= 1'b1;

                    bclk_rise_ce <= 1'b1;
                end


                // =================================================
                // 当前 BCLK = 1
                // 下一拍将变成 0
                // => BCLK 下降沿
                //
                // 我们在下降沿更新 bit counter 和 WS
                // =================================================
                else
                begin
                    i2s_bclk <= 1'b0;

                    bclk_fall_ce <= 1'b1;


                    // ---------------------------------------------
                    // 一个完整64-bit I2S frame结束
                    // ---------------------------------------------
                    if (bit_cnt == 6'd63)
                    begin
                        bit_cnt <= 6'd0;

                        // 回到 Left channel
                        i2s_ws <= 1'b0;

                        // 新的一帧开始
                        frame_start_ce <= 1'b1;
                    end


                    else
                    begin
                        bit_cnt <= bit_cnt + 1'b1;


                        // -----------------------------------------
                        // 前32个 BCLK 是 Left
                        //
                        // 到 bit 31 结束后切换成 Right
                        // -----------------------------------------
                        if (bit_cnt == 6'd31)
                        begin
                            i2s_ws <= 1'b1;
                        end
                    end
                end
            end


            else
            begin
                bclk_div_cnt <= bclk_div_cnt + 1'b1;
            end
        end
    end

endmodule