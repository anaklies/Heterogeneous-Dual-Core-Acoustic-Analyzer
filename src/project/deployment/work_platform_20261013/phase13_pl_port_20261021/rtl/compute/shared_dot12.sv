`timescale 1ns / 1ps
// Twelve signed products per accepted beat. One 48-bit dot accumulator.
// Stalling the output stalls the complete arithmetic pipeline.
module shared_dot12 #(
    parameter integer LANES = 12,
    parameter integer MAX_BEATS = 128
)
(
    input  wire clk,
    input  wire rst_n,
    input  wire clear_faults,
    input  wire s_valid,
    output wire s_ready,
    input  wire [LANES*16-1:0] s_a,
    input  wire [LANES*16-1:0] s_b,
    input  wire [LANES-1:0] s_mask,
    input  wire s_first,
    input  wire s_last,
    input  wire [31:0] s_tag,
    output reg m_valid,
    input  wire m_ready,
    output reg signed [47:0] m_sum,
    output reg [31:0] m_tag,
    output reg m_error,
    output reg protocol_fault,
    output reg overflow_fault
);
    initial begin
        if (LANES != 12 || MAX_BEATS < 1) $fatal(1, "shared_dot12 requires12 lanes and positive bound");
    end
    wire advance = !m_valid || m_ready;
    assign s_ready = advance;
    reg [3:0] valid;
    reg [3:0] first;
    reg [3:0] last;
    reg [31:0] tag [0:3];
    (* use_dsp = "yes" *) reg signed [31:0] product [0:11];
    reg signed [32:0] pair_sum [0:5];
    reg signed [33:0] quad_sum [0:2];
    reg signed [35:0] beat_sum;
    reg signed [47:0] accumulator;
    reg active, transaction_bad;
    reg [31:0] active_tag;
    localparam integer CW = $clog2(MAX_BEATS+2);
    reg [CW-1:0] beats;
    wire signed [48:0] extended_sum = $signed(first[3] ? 48'sd0 : accumulator) +
                                                $signed({{13{beat_sum[35]}},beat_sum});
    wire overflow = extended_sum[48] != extended_sum[47];
    wire bad_beat = (first[3] ? active : (!active || tag[3] != active_tag || beats >= MAX_BEATS));
    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            valid <= 0; first <= 0; last <= 0;
            m_valid <= 0; m_sum <= 0; m_tag <= 0; m_error <= 0;
            accumulator <= 0; active <= 0; active_tag <= 0;
            transaction_bad <= 0; beats <= 0;
            protocol_fault <= 0; overflow_fault <= 0;
        end else begin
            if (clear_faults) begin protocol_fault <= 0; overflow_fault <= 0; end
            if (advance) begin
                m_valid <= 0;
                valid <= {valid[2:0],s_valid};
                first <= {first[2:0],s_first};
                last <= {last[2:0],s_last};
                tag[0] <= s_tag;
                for (i=1;i<4;i=i+1) tag[i] <= tag[i-1];
                if (s_valid) begin
                    for (i=0;i<12;i=i+1)
                        product[i] <= s_mask[i] ? $signed(s_a[i*16+:16]) * $signed(s_b[i*16+:16]) : 32'sd0;
                end
                if (valid[0]) begin
                    for (i=0;i<6;i=i+1)
                        pair_sum[i] <= $signed({product[2*i][31],product[2*i]}) +
                                       $signed({product[2*i+1][31],product[2*i+1]});
                end
                if (valid[1]) begin
                    for (i=0;i<3;i=i+1)
                        quad_sum[i] <= $signed({pair_sum[2*i][32],pair_sum[2*i]}) +
                                       $signed({pair_sum[2*i+1][32],pair_sum[2*i+1]});
                end
                if (valid[2]) beat_sum <= $signed({{2{quad_sum[0][33]}},quad_sum[0]}) +
                                        $signed({{2{quad_sum[1][33]}},quad_sum[1]}) +
                                        $signed({{2{quad_sum[2][33]}},quad_sum[2]});
                if (valid[3]) begin
                    if (bad_beat) protocol_fault <= 1;
                    if (overflow) overflow_fault <= 1;
                    transaction_bad <= (first[3] ? 1'b0 : transaction_bad) || bad_beat || overflow;
                    accumulator <= overflow ? (extended_sum[48] ? 48'sh800000000000 : 48'sh7fffffffffff) : extended_sum[47:0];
                    active <= !last[3];
                    if (first[3]) begin active_tag <= tag[3]; beats <= 1; end
                    else if (beats < MAX_BEATS+1) beats <= beats+1;
                    if (last[3]) begin
                        m_valid <= 1;
                        m_sum <= overflow ? (extended_sum[48] ? 48'sh800000000000 : 48'sh7fffffffffff) : extended_sum[47:0];
                        m_tag <= first[3] ? tag[3] : active_tag;
                        m_error <= (first[3] ? 1'b0 : transaction_bad) || bad_beat || overflow;
                        active <= 0;
                    end
                end
            end
        end
    end
endmodule
