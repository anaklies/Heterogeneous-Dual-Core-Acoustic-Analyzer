from pathlib import Path
P=Path(__file__).resolve().parent
p=P/'imu_rotation_q16.sv';s=p.read_text()
a=s.index('    always @*');b=s.index('    always @(posedge clk)',a)
s=s[:a]+'''    // Select operands first, then reuse the same exact arithmetic for
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
''' +s[b:]
s=s.replace('wire signed [33:0] norm =','(* use_dsp="yes" *) wire signed [33:0] norm =')
p.write_text(s)
p=P/'covariance_6ch.sv';s=p.read_text()
s=s.replace('    wire [10:0] external_imag_address', '''    (* use_dsp="yes" *) wire signed [47:0] accumulated_real = previous_real + product_real;
    (* use_dsp="yes" *) wire signed [47:0] accumulated_imag = previous_imag + product_imag;
    wire [10:0] external_imag_address''')
s=s.replace('previous_real + product_real;\n            sum_imag','accumulated_real;\n            sum_imag').replace('sum_imag[internal_address] <= previous_imag + product_imag;', 'sum_imag[internal_address] <= accumulated_imag;')
p.write_text(s)
p=P/'pl_background_covariance.sv';s=p.read_text()
s=s.replace('    assign covariance_read_enable', '''    (* use_dsp="yes" *) wire [63:0] qualified_off = next_off * 6'd20;
    (* use_dsp="yes" *) wire [63:0] qualified_diag = next_diag * 6'd17;
    assign covariance_read_enable''')
s=s.replace('next_off * 20 < next_diag * 17','qualified_off < qualified_diag')
p.write_text(s)
print('Nine quaternion numerator operations shared; exact accumulators/qualification mapped to spare DSPs.')
