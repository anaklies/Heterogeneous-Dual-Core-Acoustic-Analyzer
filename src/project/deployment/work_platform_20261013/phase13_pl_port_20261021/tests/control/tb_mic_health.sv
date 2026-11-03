`timescale 1ns/1ps
module tb_mic_health;
    reg clk=0;always #10 clk=~clk;
    reg rst_n=0,sample_valid=0,clear_faults=0;
    reg [143:0] pcm=0;
    wire acquisition_stale,window_valid,confirmed_wiring_fault;
    wire observation_fresh;
    wire [5:0] constant_channel_warning,clipping_warning;
    wire [14:0] identical_pair_warning;
    wire [31:0] sample_count;
    mic_health #(.WINDOW_SAMPLES(8),.NO_SAMPLE_CYCLES(16),.ACTIVE_PEAK(50)) dut(.*);
    integer i,j;
    task sample;
        begin @(negedge clk);sample_valid=1;@(negedge clk);sample_valid=0;end
    endtask
    initial begin
        repeat(3)@(negedge clk);rst_n=1;
        for(i=0;i<16;i=i+1)sample();
        if(constant_channel_warning!=63||clipping_warning||identical_pair_warning||confirmed_wiring_fault)$fatal(1,"silence wrongly diagnosed as confirmed failure");
        for(i=0;i<8;i=i+1)begin
            for(j=0;j<6;j=j+1)pcm[j*24+:24]=(j<2)?(100+i):(200+i+j);
            if(i==3)pcm[2*24+:24]=24'h7fffff;
            sample();
        end
        if(constant_channel_warning||!identical_pair_warning[0]||clipping_warning!=4)$fatal(1,"channel plausibility failed");
        repeat(18)@(negedge clk);if(!acquisition_stale)$fatal(1,"capture watchdog missed outage");
        sample();if(acquisition_stale)$fatal(1,"capture did not recover");
        if(sample_count!=25||confirmed_wiring_fault)$fatal(1,"counter or semantic fault");
        for(i=0;i<6;i=i+1)sample();
        repeat(18)@(negedge clk);
        sample();
        if(window_valid||observation_fresh)$fatal(1,"partial pre-gap health window leaked after recovery");
        for(i=0;i<7;i=i+1)sample();
        if(!observation_fresh)$fatal(1,"new complete health window not published");
        $display("MIC_HEALTH_PASS silence duplicate clipping acquisition_stale recovery");$finish;
    end
endmodule
