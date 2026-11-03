`timescale 1ns/1ps
module tb_cnn_overload;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,feature_valid=0,start=0,mask_ready=1;
    reg[15:0]feature_index=0;reg signed[23:0]feature_data=0;
    wire feature_ready,busy,done,load_error,mask_valid;wire[12:0]mask_address;wire[15:0]mask_data;
    cnn_v3_tiled #(.COEFF_DIR("C:/Users/sunxi/Desktop/sixmic3D_fpga/pl/coeff"),.TOTAL_FREQ(4),.OUTPUT_FREQ(1),.TILE_FREQ(8)) dut(.*);
    initial
    begin
        repeat(4)@(negedge clk);rst_n=1;
        for(integer i=0;i<640;i=i+1)
        begin feature_valid=1;feature_index=i;@(negedge clk);end
        for(integer i=0;i<2000;i=i+1)
        begin feature_valid=1;feature_index=0;@(negedge clk);end
        feature_valid=0;start=1;@(negedge clk);start=0;repeat(10)@(negedge clk);
        if(!load_error || busy || mask_valid)$fatal(1,"overload wrapped count or launched invalid CNN");
        $display("PASS CNN duplicate overload: counter bounded, fault sticky, invalid computation blocked");$finish;
    end
endmodule
