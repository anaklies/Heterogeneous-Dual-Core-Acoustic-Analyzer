`timescale 1ns / 1ps
module tb_frontend_lease;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0;
    reg [31:0] arena_base=32'h10000000,active_config=7,active_session=11;
    reg request_valid=0;wire request_ready;
    reg [1:0] request_slot=0;
    reg [31:0] request_frame=0,request_config=7,request_session=11;
    reg [63:0] request_sample=100000;
    wire command_valid;reg command_ready=0;
    wire [31:0] command_token,command_frame,command_config,command_session;
    wire [1:0] command_slot;wire [63:0] command_sample;wire command_reuse;
    wire [31:0] pcm_address,feature_address,scratch_address,qlogs_address;
    wire [31:0] previous_address,current_address,previous_meta_address,current_meta_address;
    reg done_valid=0;wire done_ready;reg [31:0] done_token=0,done_error=0;
    reg memory_fault=0;wire completion_valid;reg completion_ready=0;
    wire [31:0] completion_error;wire cache_available,fault_latched;
    wire [31:0] timeout_count,stale_done_count,accepted_count;
    reg recover_request=0,bus_quiescent_ack=0;
    integer checks=0;reg [31:0] token,write_bank,old_read;
    reg [383:0] held_command;
    frontend_lease #(.COLD_TIMEOUT(40),.WARM_TIMEOUT(20),.INITIAL_TOKEN(32'hfffffffe)) dut(.*);
    task check(input bit condition,input string message);
        begin checks=checks+1;if(!condition)$fatal(1,"check%0d:%s",checks,message);end
    endtask
    task submit(input [31:0] frame,input [63:0] sample,input [1:0] slot);
        begin
            @(negedge clk);request_frame=frame;request_sample=sample;request_slot=slot;
            request_config=active_config;request_session=active_session;request_valid=1;
            wait(request_ready);@(posedge clk);#1;
            @(negedge clk);request_valid=0;
        end
    endtask
    task launch;
        begin
            check(command_valid,"command offered");token=command_token;
            @(negedge clk);command_ready=1;@(posedge clk);#1;
            @(negedge clk);command_ready=0;
            check(!command_valid,"one command acceptance");
        end
    endtask
    task finish(input [31:0] error);
        begin
            @(negedge clk);done_token=token;done_error=error;done_valid=1;
            @(posedge clk);#1;@(negedge clk);done_valid=0;done_error=0;
            check(completion_valid,"matching completion");
        end
    endtask
    task consume;
        begin
            @(negedge clk);completion_ready=1;@(posedge clk);#1;
            @(negedge clk);completion_ready=0;
        end
    endtask
    task recover;
        begin
            @(negedge clk);recover_request=1;bus_quiescent_ack=1;
            @(posedge clk);#1;@(negedge clk);recover_request=0;bus_quiescent_ack=0;
        end
    endtask
    initial begin
        repeat(3)@(posedge clk);@(negedge clk);rst_n=1;
        submit(1,100000,0);
        check(!command_reuse,"first frame cold");
        check(current_address==32'h10300000 && previous_address==32'h10314000,"cold banks distinct");
        check(current_meta_address!=previous_meta_address,"metadata banks distinct");
        check(pcm_address==32'h10000000 && feature_address==32'h10100000,"slot0 layout");
        held_command={command_token,command_frame,command_config,command_session,
            command_sample,pcm_address,feature_address,current_address,previous_address,scratch_address,qlogs_address};
        repeat(4)begin
            @(posedge clk);#1;
            check(command_valid && held_command=={command_token,command_frame,command_config,command_session,
                command_sample,pcm_address,feature_address,current_address,previous_address,scratch_address,qlogs_address},"command held under backpressure");
        end
        launch;check(token==32'hfffffffe,"initial token");write_bank=current_address;
        finish(0);check(completion_error==0 && cache_available,"cold commit");
        repeat(3)begin @(posedge clk);#1;check(completion_valid && !request_ready,"completion holds lease");end
        consume;
        submit(2,104608,1);
        check(command_reuse,"adjacent window reuse");
        check(previous_address==write_bank && current_address!=write_bank,"swap only after complete");
        check(pcm_address==32'h10050000 && feature_address==32'h10150000,"slot1 layout");
        launch;check(token==32'hffffffff,"second token");
        @(negedge clk);done_token=32'hfffffffe;done_valid=1;
        @(posedge clk);#1;@(negedge clk);done_valid=0;
        check(!completion_valid && stale_done_count==1,"old completion rejected");
        finish(0);check(completion_error==0,"warm completion");consume;

        // A changed reserved arena cannot reuse old physical cache addresses.
        arena_base=32'h11000000;
        submit(3,109216,2);check(!command_reuse,"arena move invalidates reuse");
        launch;check(token==0,"token wrap");finish(0);consume;
        active_config=8;
        submit(4,113824,0);check(!command_reuse,"config change cold");
        launch;active_config=9;finish(0);
        check(completion_error[1] && !cache_available,"config changed during processing rejected");consume;

        submit(5,118432,0);launch;memory_fault=1;
        @(posedge clk);#1;memory_fault=0;
        check(fault_latched && !request_ready,"bus fault holds allocations");
        finish(0);check(completion_error[3] && !cache_available,"bus fault result invalid");consume;
        @(negedge clk);recover_request=1;bus_quiescent_ack=0;
        @(posedge clk);#1;@(negedge clk);recover_request=0;
        check(fault_latched && !request_ready,"no unsafe local recovery");
        recover;check(!fault_latched && request_ready,"quiescent recovery");

        submit(6,123040,1);launch;repeat(42)@(posedge clk);#1;
        check(fault_latched && timeout_count==1 && !request_ready && !completion_valid,"timeout retains in-flight lease");
        finish(0);check(completion_error[2] && !cache_available,"late done discarded");consume;recover;
        submit(7,127648,0); // Stalled command also times out without withdrawal.
        repeat(42)@(posedge clk);#1;
        check(command_valid && fault_latched,"timeout does not withdraw command");
        recover;check(completion_valid && completion_error[5],"quiescent reset reports abort");consume;

        submit(8,132256,3);check(completion_valid && completion_error[0] && !command_valid,"invalid slot rejected");consume;
        arena_base=32'h3f801000;
        submit(9,136864,0);check(completion_valid && completion_error[0],"arena beyond mapped DDR rejected");consume;
        arena_base=32'h10000001;
        submit(10,141472,0);check(completion_error[0],"unaligned arena rejected");consume;
        arena_base=32'h10000000;
        submit(11,64'hfffffffffffff000,0);check(completion_error[0],"sample ID overflow rejected");consume;
        submit(12,146080,0);launch;finish(1);
        check(completion_error[4] && !cache_available,"kernel metadata error rejected");consume;
        check(accepted_count==12,"accepted requests counted");
        $display("FRONTEND_LEASE_PASS checks=%0d",checks);$finish;
    end
    initial begin #100000;$fatal(1,"test timeout");end
endmodule
