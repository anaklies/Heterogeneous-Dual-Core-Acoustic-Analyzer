`timescale 1ns / 1ps
// Electrical/digital plausibility only. Quiet audio is not a confirmed bad mic.
module mic_health #(
    parameter integer CLK_HZ=49162010,
    parameter integer WINDOW_SAMPLES=48000,
    parameter integer NO_SAMPLE_CYCLES=CLK_HZ/10,
    parameter integer ACTIVE_PEAK=8389
)(
    input wire clk,rst_n,sample_valid,clear_faults,
    input wire [143:0] pcm,
    output reg acquisition_stale,
    output reg window_valid,
    output reg observation_fresh,
    output reg [5:0] constant_channel_warning,clipping_warning,
    output reg [14:0] identical_pair_warning,
    output reg [31:0] sample_count,
    output wire confirmed_wiring_fault
);
    // Cross-wiring and acoustic silence cannot be proved from passive PCM alone.
    assign confirmed_wiring_fault=1'b0;
    reg [31:0] idle_age,window_count;
    reg signed [23:0] previous[0:5];
    reg [5:0] changed,clipped,active;
    reg [14:0] different_pair;
    wire signed [23:0] values[0:5];
    genvar g;
    generate for(g=0;g<6;g=g+1) begin:channels
        assign values[g]=$signed(pcm[g*24+:24]);
    end endgenerate
    integer ci,cj,cp;
    reg [5:0] changes_now,clips_now,active_now;
    reg [14:0] difference_now;
    always @* begin
        changes_now=0;clips_now=0;active_now=0;difference_now=0;cp=0;
        for(ci=0;ci<6;ci=ci+1) begin
            changes_now[ci]=values[ci]!=previous[ci];
            clips_now[ci]=values[ci]==24'sh800000||values[ci]==24'sh7fffff;
            active_now[ci]=values[ci]>ACTIVE_PEAK||values[ci]<-ACTIVE_PEAK;
            for(cj=ci+1;cj<6;cj=cj+1) begin
                difference_now[cp]=values[ci]!=values[cj];cp=cp+1;
            end
        end
    end
    integer k,si,sj,sp;
    always @(posedge clk) begin
        if(!rst_n) begin
            acquisition_stale<=0;window_valid<=0;observation_fresh<=0;constant_channel_warning<=0;clipping_warning<=0;
            identical_pair_warning<=0;sample_count<=0;idle_age<=0;window_count<=0;
            changed<=0;clipped<=0;active<=0;different_pair<=0;
            for(k=0;k<6;k=k+1)previous[k]<=0;
        end else begin
            window_valid<=0;
            if(clear_faults) begin constant_channel_warning<=0;clipping_warning<=0;identical_pair_warning<=0;end
            if(sample_valid) begin
                idle_age<=0;acquisition_stale<=0;
                if(sample_count!=32'hffffffff)sample_count<=sample_count+1;
                for(k=0;k<6;k=k+1)previous[k]<=values[k];
                if(window_count==WINDOW_SAMPLES-1) begin
                    window_count<=0;window_valid<=1;observation_fresh<=1;
                    constant_channel_warning<=~(changed|changes_now);clipping_warning<=clipped|clips_now;
                    sp=0;
                    for(si=0;si<6;si=si+1)for(sj=si+1;sj<6;sj=sj+1)begin
                        identical_pair_warning[sp]<=!(different_pair[sp]||difference_now[sp])&&(active[si]||active_now[si])&&(active[sj]||active_now[sj]);sp=sp+1;
                    end
                    changed<=0;clipped<=0;active<=0;different_pair<=0;
                end else begin
                    window_count<=window_count+1;changed<=window_count==0?6'd0:(changed|changes_now);clipped<=clipped|clips_now;
                    active<=active|active_now;different_pair<=different_pair|difference_now;
                end
            end else if(idle_age>=NO_SAMPLE_CYCLES-1)begin
                acquisition_stale<=1;observation_fresh<=0;window_count<=0;
                changed<=0;clipped<=0;active<=0;different_pair<=0;
            end
            else idle_age<=idle_age+1;
        end
    end
    initial if(WINDOW_SAMPLES<2||NO_SAMPLE_CYCLES<1) $fatal(1,"invalid health observation limits");
endmodule
