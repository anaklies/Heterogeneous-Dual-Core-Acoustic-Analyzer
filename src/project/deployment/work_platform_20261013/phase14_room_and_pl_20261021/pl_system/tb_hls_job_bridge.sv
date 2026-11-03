`timescale 1ns / 1ps
module tb_hls_job_bridge;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,job_valid=0;wire job_ready;
    reg [31:0] job_token=1,job_kernel_base=32'h44a00000,job_meta_base=32'h10000000;
    reg [4:0] job_arg_count=2;
    reg [127:0] job_offsets=0;reg [511:0] job_values=0;
    reg job_verify=1,job_check_magic=1,job_status_zero=1;
    reg [31:0] job_expected_magic=32'h53464631;reg [7:0] job_status_offset=52;
    reg memory_fault=0,completion_ready=0,recover_request=0,common_bus_reset_ack=0;
    reg kernel_dma_idle=1;wire [1:0] active_kernel;
    wire completion_valid,fault_latched;
    wire [31:0] completion_token,completion_error,result0,result1;
    wire [31:0] m_awaddr,m_wdata,m_araddr;
    wire m_awvalid,m_wvalid,m_bready,m_arvalid,m_rready;wire [3:0] m_wstrb;
    wire m_awready,m_wready,m_arready;
    reg m_bvalid=0,m_rvalid=0;reg [1:0] m_bresp=0,m_rresp=0;reg [31:0] m_rdata=0;
    integer cycle=0,checks=0,writes=0,reads=0,busy_reads=0;
    reg aw_seen=0,w_seen=0,kernel_running=0,never_complete=0,stall_read=0;
    reg inject_b_error=0,bad_magic=0;reg [31:0] status_value=0,aw_saved=0,w_saved=0;
    reg [31:0] register0=0,register1=0;
    wire aw_fire=m_awvalid&&m_awready,w_fire=m_wvalid&&m_wready;
    wire [31:0] write_address=aw_fire?m_awaddr:aw_saved;
    wire [31:0] write_value=w_fire?m_wdata:w_saved;
    assign m_awready=!aw_seen && !m_bvalid && cycle%3!=0;
    assign m_wready=!w_seen && !m_bvalid && cycle%4!=0;
    assign m_arready=!m_rvalid && !stall_read && cycle%3!=0;
    hls_job_bridge #(.TIMEOUT_CYCLES(300),.POLL_CYCLES(3)) dut(.*);
    task tick;begin @(posedge clk);#1;@(negedge clk);end endtask
    task check(input bit ok,input string why);
        begin checks++;if(!ok)$fatal(1,"%0d:%s error=%h",checks,why,completion_error);end
    endtask
    task submit;
        begin @(negedge clk);job_valid=1;wait(job_ready);@(posedge clk);#1;@(negedge clk);job_valid=0;end
    endtask
    task consume;
        begin check(completion_token==job_token,"token preserved");completion_ready=1;tick;completion_ready=0;job_token++;end
    endtask
    task recover;
        begin recover_request=1;common_bus_reset_ack=1;tick;recover_request=0;common_bus_reset_ack=0;end
    endtask
    always @(posedge clk) begin
        cycle<=cycle+1;
        if(!rst_n || common_bus_reset_ack)begin
            aw_seen<=0;w_seen<=0;m_bvalid<=0;m_rvalid<=0;
            kernel_running<=0;busy_reads<=0;
        end
        else begin
            if(aw_fire)begin aw_seen<=1;aw_saved<=m_awaddr;end
            if(w_fire)begin w_seen<=1;w_saved<=m_wdata;end
            if((aw_seen||aw_fire) && (w_seen||w_fire) && !m_bvalid)begin
                aw_seen<=0;w_seen<=0;m_bvalid<=1;m_bresp<=0;writes<=writes+1;
                if(write_address==job_kernel_base+16)begin register0<=write_value;if(inject_b_error)m_bresp<=2;end
                if(write_address==job_kernel_base+24)register1<=write_value;
                if(write_address==job_kernel_base && write_value[0])begin kernel_running<=1;busy_reads<=3;end
            end
            if(m_bvalid&&m_bready)m_bvalid<=0;
            if(m_arvalid&&m_arready)begin
                m_rvalid<=1;m_rresp<=0;reads<=reads+1;
                if(m_araddr==job_kernel_base)begin
                    if(kernel_running && (never_complete||busy_reads>0))begin
                        m_rdata<=0;if(!never_complete)busy_reads<=busy_reads-1;
                    end
                    else if(kernel_running)begin m_rdata<=6;kernel_running<=0;end
                    else m_rdata<=4;
                end
                else if(m_araddr==job_meta_base)m_rdata<=bad_magic?0:32'h53464631;
                else if(m_araddr==job_meta_base+52)m_rdata<=status_value;
                else begin m_rresp<=3;m_rdata<=0;end
            end
            if(m_rvalid&&m_rready)m_rvalid<=0;
        end
    end
    reg held_aw=0,held_w=0,held_ar=0;
    reg [31:0] last_aw,last_w,last_ar;
    always @(posedge clk)begin
        if(rst_n && !common_bus_reset_ack)begin
            if(held_aw)check(m_awvalid&&m_awaddr==last_aw,"AW stable under backpressure");
            if(held_w)check(m_wvalid&&m_wdata==last_w,"W stable under backpressure");
            if(held_ar)check(m_arvalid&&m_araddr==last_ar,"AR stable under backpressure");
        end
        held_aw<=m_awvalid&&!m_awready;last_aw<=m_awaddr;
        held_w<=m_wvalid&&!m_wready;last_w<=m_wdata;
        held_ar<=m_arvalid&&!m_arready;last_ar<=m_araddr;
        if(common_bus_reset_ack)begin held_aw<=0;held_w<=0;held_ar<=0;end
    end
    initial begin
        job_offsets[0+:8]=16;job_offsets[8+:8]=24;
        job_values[0+:32]=32'h12345678;job_values[32+:32]=32'h9abcdef0;
        tick;rst_n=1;tick;
        submit;wait(completion_valid);#1;
        check(completion_error==0 && result0==32'h53464631 && result1==0,"success metadata");
        check(register0==32'h12345678 && register1==32'h9abcdef0,"ordered argument writes");
        repeat(3)begin tick;check(completion_valid&&!job_ready,"completion held");end
        consume;
        kernel_dma_idle=0;submit;wait(dut.state==8);#1;
        check(!completion_valid,"APdone must wait for DMA responses");
        repeat(4)tick;
        check(!completion_valid,"pending DMA retains ownership");
        kernel_dma_idle=1;wait(completion_valid);#1;
        check(completion_error==0,"drained DMA completion");consume;
        status_value=1;submit;wait(completion_valid);#1;
        check(completion_error==32,"nonzero kernel status rejected");consume;status_value=0;
        bad_magic=1;submit;wait(completion_valid);#1;
        check(completion_error==16,"bad commit rejected");consume;bad_magic=0;
        inject_b_error=1;submit;wait(completion_valid);#1;
        check(completion_error[3] && fault_latched && !kernel_running,"B error before launch");consume;
        inject_b_error=0;recover;check(job_ready,"common reset recovery");
        never_complete=1;submit;wait(fault_latched);#1;
        check(!completion_valid && kernel_running,"timeout cannot release running DMA buffers");
        never_complete=0;wait(completion_valid);#1;
        check(completion_error[2],"late finished kernel rejected");consume;recover;
        stall_read=1;submit;wait(fault_latched);#1;
        check(m_arvalid && !completion_valid,"stalled AXI request retained after timeout");
        repeat(3)tick;recover;stall_read=0;
        check(completion_valid && completion_error[6],"common reset abort reported");consume;
        job_offsets[0+:8]=0;submit;wait(completion_valid);#1;
        check(completion_error==1 && !m_awvalid && !m_arvalid,"control register cannot be used as argument");consume;
        job_offsets[0+:8]=16;job_kernel_base=32'h10000000;
        submit;wait(completion_valid);#1;
        check(completion_error==1 && !m_awvalid && !m_arvalid,"kernel address whitelist rejects DDR write target");consume;
        $display("HLS_JOB_BRIDGE_PASS checks=%0d writes=%0d reads=%0d",checks,writes,reads);$finish;
    end
    initial begin #200000;$fatal(1,"test timeout");end
endmodule
