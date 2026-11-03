`timescale 1ns/1ps
module tb_adaptive_mode;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,arm=0,reference_qualified=0,short_valid=0,short_ready=1;
    reg [2:0] short_channel=0;reg [10:0] short_bin=0;
    reg signed [31:0] short_real=0,short_imag=0;
    wire use_cnn,clear_reference;reg cleared=0;
    pl_adaptive_mode dut(.*);
    always @(posedge clk)if(clear_reference)cleared<=1;
    always @(negedge clk)if(clear_reference)reference_qualified=0;
    task automatic window(input integer amplitude);
        begin
            @(negedge clk);arm=1;@(negedge clk);arm=0;
            for(integer t=0;t<20;t=t+1)
                for(integer f=0;f<257;f=f+1)
                begin
                    short_bin=f;short_real=amplitude<<16;short_valid=1;@(negedge clk);
                end
            short_valid=0;repeat(4)@(negedge clk);
        end
    endtask
    initial
    begin
        repeat(3)@(negedge clk);rst_n=1;
        window(100);if(use_cnn)$fatal(1,"unqualified reference enabled CNN");
        reference_qualified=1;repeat(3)@(negedge clk);
        if(!use_cnn)$fatal(1,"valid stationary background failed to enable CNN");
        window(500);if(!use_cnn)$fatal(1,"mid-band should retain noisy mode");
        window(800);if(use_cnn)$fatal(1,"strong foreground should choose quiet baseline");
        for(integer i=0;i<12;i=i+1)
        begin window(440+10*i);if(use_cnn)$fatal(1,"quiet mode chattered in hysteresis band");end
        window(350);if(!use_cnn)$fatal(1,"background-dominant frame failed to choose CNN");
        for(integer i=0;i<12;i=i+1)
        begin window(440+10*i);if(!use_cnn)$fatal(1,"noisy mode chattered in hysteresis band");end
        window(20);if(use_cnn || !cleared)$fatal(1,"obsolete loud reference was not discarded");
        reference_qualified=0;repeat(3)@(negedge clk);
        if(use_cnn)$fatal(1,"reference loss should fall back safely");
        $display("PASS adaptive quiet/CNN selection, qualified-reference safeguard, two-way transitions and 24 boundary windows without chatter");$finish;
    end
    initial begin #3000000;$fatal(1,"adaptive mode timeout");end
endmodule
