`timescale 1ns/1ps
module tb_raw_cursor;
 reg clk=0;always #5 clk=~clk;reg rst_n=0;reg[31:0]gen=0,off=0;reg[63:0]last=0;wire[511:0]words;
 raw_cursor dut(.clk(clk),.rst_n(rst_n),.configured(1'b1),.record_arm(1'b1),.writer_enable(1'b1),.generation(gen),.base(32'h100000),.bytes(32'd4096),.next_offset(off),.dropped(32'd0),.faults(32'd0),.session(32'd3),.config_version(32'd7),.last_sample(last),.leased(2'd0),.words(words));
 initial begin
 repeat(3)@(negedge clk);rst_n=1;gen=1;@(negedge clk);if(words[160+:64]!=0)$fatal(1,"generation reset");
 off=32;last=1000;#1;if(words[160+:64]!=1)$fatal(1,"commit visibility lag");@(negedge clk);if(words[160+:64]!=1)$fatal(1,"double count");
 off=64;last=1002;#1;if(words[160+:64]!=2)$fatal(1,"sample IDs confused with record count");@(negedge clk);
 dut.records=64'hffffffff;dut.observed_offset=4064;off=0;#1;if(words[160+:64]!=64'h100000000)$fatal(1,"32-bit lifetime limit");@(negedge clk);
 gen=2;off=0;#1;if(words[160+:64]!=0)$fatal(1,"new ring not empty");@(negedge clk);
 dut.records=127;dut.observed_offset=4064;off=0;#1;if(words[160+:64]!=128)$fatal(1,"ring wrap count");@(negedge clk);
 if(words[0+:32]!=32'h43555231||words[224+:64]!=1002||words[448+:32]!=1)$fatal(1,"schema/ID fields");
 $display("RAW_CURSOR_PASS atomic commit visibility record/sample distinction 64bit lifetime bank generation wrap");$finish;end
endmodule
