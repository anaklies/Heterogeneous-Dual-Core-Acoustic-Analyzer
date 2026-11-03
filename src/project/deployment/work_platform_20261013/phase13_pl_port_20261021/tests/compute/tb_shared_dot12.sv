`timescale 1ns/1ps
module tb_shared_dot12;
    `include "counts.svh"
    reg clk=0;always #10 clk=~clk;
    reg rst_n=0,clear_faults=0,s_valid=0,s_first=0,s_last=0,m_ready=0;
    wire s_ready,m_valid,m_error,protocol_fault,overflow_fault;
    reg [191:0] s_a=0,s_b=0;
    reg [11:0] s_mask=0;
    reg [31:0] s_tag=0;
    wire signed [47:0] m_sum;
    wire [31:0] m_tag;
    shared_dot12 dut(.*);
    reg [429:0] inputs[0:INPUTS-1];
    reg [80:0] expected[0:OUTPUTS-1];
    reg [31:0] rng=32'h16ce812;
    integer output_count=0,cycles=0,i;
    reg was_stalled=0;
    reg [80:0] held;
    always @(negedge clk) begin
        rng <= {rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
        m_ready <= rng[2:0]!=0;
    end
    always @(posedge clk) if (rst_n) begin
        cycles=cycles+1;
        if (was_stalled && {m_error,m_tag,m_sum}!==held) $fatal(1,"Output changed while stalled");
        was_stalled=m_valid&&!m_ready;held={m_error,m_tag,m_sum};
        if (m_valid&&m_ready) begin
            if(output_count>=OUTPUTS) $fatal(1,"Extra output");
            if(expected[output_count][80]) begin
                if(!m_error) $fatal(1,"Orphan dot accepted");
            end else if ({m_error,m_tag,m_sum}!==expected[output_count])
                $fatal(1,"Dot mismatch index%0d got%h expected%h",output_count,{m_error,m_tag,m_sum},expected[output_count]);
            output_count=output_count+1;
        end
        if(cycles>30000) $fatal(1,"Timeout");
    end
    initial begin
        $readmemh({DATA_DIR,"/stimulus.mem"},inputs);$readmemh({DATA_DIR,"/expected.mem"},expected);
        repeat(4) @(negedge clk);rst_n=1;
        for(i=0;i<INPUTS;i=i+1) begin
            @(negedge clk);
            {s_tag,s_first,s_last,s_mask,s_a,s_b}=inputs[i];s_valid=1;
            @(posedge clk);while(!s_ready) @(posedge clk);
            @(negedge clk);s_valid=0;
            if(i%7==0) repeat(2) @(negedge clk);
        end
        wait(output_count==OUTPUTS);repeat(4) @(negedge clk);
        if(!protocol_fault || overflow_fault) $fatal(1,"Fault classification failed");
        $display("SHARED_DOT12_PASS valid100 invalid1 cycles%0d",cycles);$finish;
    end
endmodule
