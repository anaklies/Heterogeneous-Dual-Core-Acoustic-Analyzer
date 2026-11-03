`timescale 1ns/1ps
// Single-master I2C, open-drain, repeated START, read ACK/NACK, clock stretch.
// byte zero lives in bits [7:0] of both packed write and read data.

module i2c_transaction_master #(
    parameter CLK_HZ = 50000000,
    I2C_HZ = 100000,
    SPLIT_SENSOR_BUS = 0
)
(
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire [6:0] address,
    input  wire [2:0] write_count,
    input  wire [31:0] write_data,
    input  wire [4:0] read_count,
    output reg [127:0] read_data,
    output wire busy,
    output reg done,
    output reg error,
    inout wire scl,
    inout wire sda,
    inout wire imu_scl,
    inout wire imu_sda
);

    localparam DIV = CLK_HZ / (I2C_HZ * 4), TIMEOUT = I2C_HZ * 4 / 100;
    localparam DW = $clog2(DIV + 1) > 0?$clog2(DIV + 1):1;
    localparam SW = $clog2(TIMEOUT + 1) > 0?$clog2(TIMEOUT + 1):1;
    localparam AW = $clog2(CLK_HZ / 20 + 2) > 0?$clog2(CLK_HZ / 20 + 2):1;
    localparam IDLE = 0, START_WAIT = 1, START_PULL = 2, BIT_LOW = 3, BIT_RISE = 4, BIT_HIGH = 5,
        BIT_FALL = 6,
        ACK_LOW = 7, ACK_RISE = 8, ACK_HIGH = 9, ACK_FALL = 10, STOP_LOW = 11, STOP_RISE = 12, STOP_HIGH = 13,
        STOP_RELEASE = 14, RESTART_RELEASE = 15, BUS_CLEAR_LOW = 16, BUS_CLEAR_RISE = 17, BUS_CLEAR_HIGH = 18;
    reg [4:0] state;
    reg [3:0] clear_pulses;
    reg scl_low, sda_low;
    reg [1:0] scl_sync, sda_sync;
    reg [DW - 1:0] divider;
    reg [SW - 1:0] stretch;
    reg [AW - 1:0] transaction_age;
    reg [6:0] addr;
    reg [2:0] nw, wi;
    reg [4:0] nr, ri;
    reg [31:0] wd;
    reg [7:0] tx, rx;
    reg [2:0] bit_index;
    reg [1:0] stage;
    reg reading, nack;
    // The hub issues only SHT 0x44/0x45 and IMU 0x50. Address bit4
    // is latched at START; bus selection cannot change during a transaction.
    wire selected_imu = SPLIT_SENSOR_BUS && addr[4];
    wire selected_scl = selected_imu ? imu_scl : scl;
    wire selected_sda = selected_imu ? imu_sda : sda;
    assign scl = (!selected_imu && scl_low) ? 1'b0 : 1'bz;
    assign sda = (!selected_imu && sda_low) ? 1'b0 : 1'bz;
    assign imu_scl = (selected_imu && scl_low) ? 1'b0 : 1'bz;
    assign imu_sda = (selected_imu && sda_low) ? 1'b0 : 1'bz;
    assign busy = state != IDLE;

    always @(posedge clk)
    begin
        scl_sync <= {scl_sync[0], selected_scl};
        sda_sync <= {sda_sync[0], selected_sda};
    end

    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            transaction_age <= 0;
            clear_pulses <= 0;
            state <= IDLE;
            scl_low <= 0;
            sda_low <= 0;
            divider <= 0;
            stretch <= 0;
            done <= 0;
            error <= 0;
            read_data <= 0;
            addr <= 0;
            nw <= 0;
            nr <= 0;
            wd <= 0;
            wi <= 0;
            ri <= 0;
            tx <= 0;
            rx <= 0;
            bit_index <= 7;
            stage <= 0;
            reading <= 0;
            nack <= 0;
        end

        else
        begin
            done <= 0;
            if (state == IDLE)transaction_age <= 0;
            else transaction_age <= transaction_age + 1;
            if (state != IDLE && transaction_age >= CLK_HZ / 20)
            begin
                state <= IDLE;
                scl_low <= 0;
                sda_low <= 0;
                done <= 1;
                error <= 1;
                divider <= 0;
                stretch <= 0;
            end

            else if (state == IDLE)
            begin
                divider <= 0;
                scl_low <= 0;
                sda_low <= 0;
                stretch <= 0;
                if (start)
                begin
                    error <= 0;
                    read_data <= 0;
                    if (write_count > 4 || read_count > 16)
                    begin
                        error <= 1;
                        done <= 1;
                    end

                    else
                    begin
                        addr <= address;
                        nw <= write_count;
                        nr <= read_count;
                        wd <= write_data;
                        wi <= 0;
                        ri <= 0;
                        stage <= (write_count == 0 && read_count > 0)?2:0;
                        tx <= {address, (write_count == 0 && read_count > 0)};
                        reading <= 0;
                        state <= START_WAIT;
                    end
                end
            end

            else if (divider == DIV - 1)
            begin
                divider <= 0;
                if ((state == START_WAIT || state == BIT_HIGH || state == ACK_HIGH || state == STOP_HIGH || state ==
                    BUS_CLEAR_HIGH) && !scl_sync[1])
                begin
                    if (stretch >= TIMEOUT)
                    begin
                        state <= IDLE;
                        scl_low <= 0;
                        sda_low <= 0;
                        done <= 1;
                        error <= 1;
                    end

                    else stretch <= stretch + 1;
                end

                else
                begin
                    stretch <= 0;
                    case
                        (state)
                        START_WAIT:
                        begin
                            if (!sda_sync[1])
                            begin
                                error <= 1;
                                clear_pulses <= 0;
                                sda_low <= 0;
                                scl_low <= 1;
                                state <= BUS_CLEAR_LOW;
                            end

                            else
                            begin
                                sda_low <= 1;
                                state <= START_PULL;
                            end
                        end
                        START_PULL:
                        begin
                            scl_low <= 1;
                            bit_index <= 7;
                            state <= BIT_LOW;
                        end
                        BIT_LOW:
                        begin
                            scl_low <= 1;
                            sda_low <= reading?0:!tx[bit_index];
                            state <= BIT_RISE;
                        end
                        BIT_RISE:
                        begin
                            scl_low <= 0;
                            state <= BIT_HIGH;
                        end
                        BIT_HIGH:
                        begin
                            // SCL has been released for a full quarter-period; stretch safely.
                            if (scl_sync[1])
                            begin
                                if (reading)rx[bit_index] <= sda_sync[1];
                                state <= BIT_FALL;
                            end

                            else
                            begin
                                state <= BIT_RISE;
                            end
                        end
                        BIT_FALL:
                        begin
                            scl_low <= 1;
                            if (bit_index == 0)state <= ACK_LOW;
                            else
                            begin
                                bit_index <= bit_index - 1;
                                state <= BIT_LOW;
                            end
                        end
                        ACK_LOW:
                        begin
                            scl_low <= 1;
                            sda_low <= reading && ri < nr - 1;
                            state <= ACK_RISE;
                        end
                        ACK_RISE:
                        begin
                            scl_low <= 0;
                            state <= ACK_HIGH;
                        end
                        ACK_HIGH:
                        begin
                            if (scl_sync[1])
                            begin
                                nack <= !reading && sda_sync[1];
                                state <= ACK_FALL;
                            end

                            else state <= ACK_RISE;
                        end
                        ACK_FALL:
                        begin
                            scl_low <= 1;
                            sda_low <= 0;
                            bit_index <= 7;
                            if (nack)
                            begin
                                error <= 1;
                                state <= STOP_LOW;
                            end

                            else if (reading)
                            begin
                                read_data[ri * 8 +: 8] <= rx;
                                if (ri == nr - 1)state <= STOP_LOW;
                                else
                                begin
                                    ri <= ri + 1;
                                    state <= BIT_LOW;
                                end
                            end

                            else if (stage == 2)
                            begin
                                reading <= 1;
                                rx <= 0;
                                state <= BIT_LOW;
                            end

                            else if (stage == 0 && nw > 0)
                            begin
                                stage <= 1;
                                tx <= wd[7:0];
                                wi <= 0;
                                state <= BIT_LOW;
                            end

                            else if (stage == 1 && wi + 1 < nw)
                            begin
                                wi <= wi + 1;
                                tx <= wd[(wi + 1) * 8 +: 8];
                                state <= BIT_LOW;
                            end

                            else if (nr > 0)
                            begin
                                stage <= 2;
                                tx <= {addr, 1'b1};
                                scl_low <= 1;
                                sda_low <= 0;
                                state <= RESTART_RELEASE;
                            end

                            else state <= STOP_LOW;
                        end
                        RESTART_RELEASE:
                        begin
                            scl_low <= 0;
                            sda_low <= 0;
                            state <= START_WAIT;
                        end
                        BUS_CLEAR_LOW:
                        begin
                            scl_low <= 1;
                            sda_low <= 0;
                            state <= BUS_CLEAR_RISE;
                        end
                        BUS_CLEAR_RISE:
                        begin
                            scl_low <= 0;
                            state <= BUS_CLEAR_HIGH;
                        end
                        BUS_CLEAR_HIGH:
                        begin
                            // Release a slave left in the middle of a read. At most nine clocks.
                            // This transaction remains failed; the hub retries at its next poll.
                            if (sda_sync[1] || clear_pulses == 8)
                            begin
                                scl_low <= 1;
                                state <= STOP_LOW;
                            end

                            else
                            begin
                                clear_pulses <= clear_pulses + 1;
                                state <= BUS_CLEAR_LOW;
                            end
                        end
                        STOP_LOW:
                        begin
                            scl_low <= 1;
                            sda_low <= 1;
                            state <= STOP_RISE;
                        end
                        STOP_RISE:
                        begin
                            scl_low <= 0;
                            state <= STOP_HIGH;
                        end
                        STOP_HIGH:
                        begin
                            if (scl_sync[1])
                            begin
                                sda_low <= 0;
                                state <= STOP_RELEASE;
                            end

                            else state <= STOP_RISE;
                        end
                        STOP_RELEASE:
                        begin
                            done <= 1;
                            state <= IDLE;
                            scl_low <= 0;
                            sda_low <= 0;
                        end
                        default:
                        begin
                            state <= IDLE;
                            scl_low <= 0;
                            sda_low <= 0;
                            error <= 1;
                            done <= 1;
                        end
                    endcase
                end
            end

            else divider <= divider + 1;
        end
    end
endmodule
