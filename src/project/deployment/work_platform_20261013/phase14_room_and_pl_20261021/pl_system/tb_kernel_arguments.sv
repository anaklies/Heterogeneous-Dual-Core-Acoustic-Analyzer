`timescale 1ns / 1ps
module tb_kernel_arguments;
    reg [2:0] kernel=0;
    reg [31:0] arena_base=32'h10000000;reg [1:0] slot=1;
    reg [63:0] sample_id=64'h123456789abcdef0;
    reg [31:0] config_version=7,session_id=11;
    reg [31:0] front_pcm=32'h10050000,front_previous=32'h10300000,front_previous_meta=32'h10328000,
        front_current=32'h10314000,front_scratch=32'h10329000,front_qlogs=32'h10334000,
        front_features=32'h10150000,front_meta=32'h10328040;
    reg allow_reuse=1,model_active=1,quality_valid=0;
    reg [31:0] sound_speed_bits=32'h43ab8000,threshold_bits=32'h3dcccccd;
    reg [31:0] analysis_a_words=0,analysis_b_words=65536,analysis_out_words=131072,
        analysis_n=1025,analysis_frames=20,analysis_operation=8,
        analysis_df_bits=32'h41bb8000,analysis_parameter_bits=0;
    wire valid,verify_meta,check_magic,status_zero;
    wire [31:0] kernel_base,meta_base,expected_magic;
    wire [4:0] arg_count;wire [127:0] offsets;wire [511:0] values;wire [7:0] status_offset;
    integer checks=0;
    kernel_arguments dut(.*);
    task check(input bit ok,input string why);begin checks++;if(!ok)$fatal(1,"%s",why);end endtask
    initial begin
        #1;check(valid&&arg_count==13&&kernel_base==32'h44a00000,"frontend map");
        check(offsets[64+:8]==8'h50 && values[256+:32]==32'h9abcdef0 && values[288+:32]==32'h12345678,"sampleID64 ordering");
        check(check_magic&&status_zero&&expected_magic==32'h53464631&&status_offset==52,"frontend commit validation");
        kernel=1;#1;check(valid&&arg_count==14&&kernel_base==32'h44a10000,"NN map");
        check(values[0+:32]==32'h10150000&&values[32+:32]==0,"NN64bit pointer highzero");
        check(meta_base==32'h10206100&&status_offset==16&&!status_zero,"NN active flag is not an error");
        kernel=2;#1;check(valid&&arg_count==10&&kernel_base==32'h44a20000,"DOA map");
        check(values[128+:32]==32'h43ab8000&&values[224+:32]==0,"sound speed bits and invalid-quality gate");
        check(meta_base==32'h10341000&&!status_zero,"floatvalidfalse is not a transport error");
        kernel=3;#1;check(valid&&arg_count==10&&status_offset==8'h60&&status_zero,"analysis RO status");
        check(values[128+:32]==2097152,"arena size in float words");
        analysis_out_words=analysis_a_words;#1;check(!valid,"analysis output cannot overlap input");
        analysis_out_words=131072;analysis_n=32768;analysis_frames=1024;analysis_operation=10;
        #1;check(!valid,"oversized DAS request rejected without integer wrap");
        analysis_n=1025;analysis_frames=20;analysis_operation=8;analysis_out_words=32'hffffffff;
        #1;check(!valid,"wrapped arena offset rejected");analysis_out_words=131072;
        kernel=0;front_current=front_previous;#1;check(!valid,"front cache alias rejected");
        front_current=32'h10314000;
        kernel=4;#1;check(!valid,"unknown kernel rejected");
        kernel=1;slot=3;#1;check(!valid,"invalid slot rejected");
        slot=0;arena_base=32'h40000000;#1;check(!valid,"outside DDR arena rejected");
        $display("KERNEL_ARGUMENTS_PASS checks=%0d",checks);$finish;
    end
endmodule
