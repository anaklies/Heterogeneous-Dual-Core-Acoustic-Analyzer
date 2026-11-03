`timescale 1ns/1ps
// Freeze a diffuse background covariance only after a complete audio window.
// A coherent source fails qualification and the system retains plain MUSIC.

module pl_background_covariance
(
    input  wire clk,
    input  wire rst_n,
    input wire clear_reference,
    input  wire start,
    input  wire noise_present,
    output reg busy,
    output reg done,
    output reg valid,
    output wire covariance_read_enable,
    output wire [10:0] covariance_read_address,
    input  wire signed [47:0] covariance_real,
    input  wire signed [47:0] covariance_imag,
    input  wire bg_r_ce,
    input  wire [10:0] bg_r_address,
    output reg [63:0] bg_r_data,
    input  wire bg_i_ce,
    input  wire [10:0] bg_i_address,
    output reg [63:0] bg_i_data
);

    localparam IDLE = 0, REQUEST = 1, STORE = 2;
    reg [1:0] state;
    reg [10:0] index;
    reg [63:0] diag_sum, off_sum;
    (* ram_style="block" *) reg signed [47:0] saved_real[0:1784], saved_imag[0:1784];
    reg [4:0] pair;
    wire diagonal = pair == 0 || pair == 6 || pair == 11 || pair == 15 || pair == 18 || pair == 20;
    wire signed [48:0] extended_real = {covariance_real[47], covariance_real};
    wire [48:0] abs_real = extended_real < 0?-extended_real:extended_real;
    wire signed [48:0] extended_imag = {covariance_imag[47], covariance_imag};
    wire [48:0] abs_imag = extended_imag < 0?-extended_imag:extended_imag;
    wire [49:0] contribution = abs_real + abs_imag;
    (* use_dsp="yes" *) wire [63:0] next_diag = diag_sum + (diagonal?contribution:0);
    (* use_dsp="yes" *) wire [63:0] next_off = off_sum + (diagonal?0:contribution);
    (* use_dsp="yes" *) wire [63:0] qualified_off = next_off * 6'd20;
    (* use_dsp="yes" *) wire [63:0] qualified_diag = next_diag * 6'd17;
    assign covariance_read_enable = state == REQUEST;
    assign covariance_read_address = index;

    always @(posedge clk)
    begin
        if (state == STORE)
        begin
            saved_real[index] <= covariance_real;
            saved_imag[index] <= covariance_imag;
        end
        if (bg_r_ce && bg_r_address < 1785)bg_r_data <= {{16{saved_real[bg_r_address][47]}},
            saved_real[bg_r_address]};
        if (bg_i_ce && bg_i_address < 1785)bg_i_data <= {{16{saved_imag[bg_i_address][47]}},
            saved_imag[bg_i_address]};
    end

    always @(posedge clk)
    begin
        if (!rst_n || clear_reference)
        begin
            state <= IDLE;
            busy <= 0;
            done <= 0;
            valid <= 0;
            index <= 0;
            pair <= 0;
            diag_sum <= 0;
            off_sum <= 0;
        end

        else
        begin
            done <= 0;
            case
                (state)
                IDLE:if (start)
                begin
                    if (valid)done <= 1;
                    else
                    begin
                        busy <= 1;
                        index <= 0;
                        pair <= 0;
                        diag_sum <= 0;
                        off_sum <= 0;
                        state <= REQUEST;
                    end
                end
                REQUEST:state <= STORE;
                STORE:
                begin
                    diag_sum <= next_diag;
                    off_sum <= next_off;
                    if (index == 1784)
                    begin
                        // 20-frame diffuse reference. No target-name or frequency-class veto.
                        valid <= noise_present && next_diag != 0 && qualified_off < qualified_diag;
                        done <= 1;
                        busy <= 0;
                        state <= IDLE;
                    end

                    else
                    begin
                        index <= index + 1;
                        pair <= pair == 20?0:pair + 1;
                        state <= REQUEST;
                    end
                end
                default:state <= IDLE;
            endcase
        end
    end
endmodule
