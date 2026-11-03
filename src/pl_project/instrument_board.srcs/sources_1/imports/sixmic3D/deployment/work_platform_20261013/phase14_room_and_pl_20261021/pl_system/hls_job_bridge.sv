`timescale 1ns / 1ps
// An autonomous register/metadata master. The connected interconnect routes
// AXI-Lite requests to HLS controls and reserved DDR. No DSP runs in PS.
module hls_job_bridge #(
    parameter integer MAX_ARGS=16,
    parameter integer TIMEOUT_CYCLES=75000000,
    parameter integer POLL_CYCLES=256,
    parameter [31:0] CONTROL_MIN=32'h44a00000,
    parameter [31:0] CONTROL_MAX=32'h44a3ffff
)(
    input wire clk,rst_n,
    input wire job_valid,
    output wire job_ready,
    input wire [31:0] job_token,job_kernel_base,job_meta_base,
    input wire [4:0] job_arg_count,
    input wire [MAX_ARGS*8-1:0] job_offsets,
    input wire [MAX_ARGS*32-1:0] job_values,
    input wire job_verify,job_check_magic,job_status_zero,
    input wire [31:0] job_expected_magic,
    input wire [7:0] job_status_offset,
    input wire memory_fault,
    input wire kernel_dma_idle,
    output wire [1:0] active_kernel,
    output wire completion_valid,
    input wire completion_ready,
    output reg [31:0] completion_token,completion_error,result0,result1,
    output reg fault_latched,
    input wire recover_request,common_bus_reset_ack,
    output reg [31:0] m_awaddr,m_wdata,m_araddr,
    output reg m_awvalid,m_wvalid,m_bready,m_arvalid,m_rready,
    output wire [3:0] m_wstrb,
    input wire m_awready,m_wready,m_bvalid,m_arready,m_rvalid,
    input wire [1:0] m_bresp,m_rresp,
    input wire [31:0] m_rdata
);
    localparam [3:0] IDLE=0,R_ADDR=1,R_DATA=2,WRITE=3,B_RESP=4,
        DELAY=5,COMPLETE=6,HALT=7,WAIT_DMA=8;
    localparam [1:0] CHECK=0,POLL=1,META0=2,META1=3;
    localparam [31:0] ERR_ARGUMENT=1,ERR_BUSY=2,ERR_TIMEOUT=4,
        ERR_BUS=8,ERR_MAGIC=16,ERR_RESULT=32,ERR_ABORT=64,ERR_MEMORY=128;
    reg [3:0] state;
    reg [1:0] read_kind;
    reg [31:0] kernel_base,meta_base,expected_magic,errors,age,delay_age;
    reg [MAX_ARGS*8-1:0] offsets;
    reg [MAX_ARGS*32-1:0] values;
    reg [4:0] arg_count,arg_index;
    reg verify_meta,check_magic,status_zero,started,finished,start_write;
    reg [7:0] status_offset;
    wire expired=state!=IDLE && state!=COMPLETE && age>=TIMEOUT_CYCLES-1;
    wire [31:0] effective_error=errors | (expired?ERR_TIMEOUT:0) | (memory_fault?ERR_MEMORY:0);
    reg bad_offsets;
    integer i;
    always @* begin
        bad_offsets=0;
        for(integer j=0;j<MAX_ARGS;j=j+1)
            if(j<job_arg_count && (job_offsets[j*8+:8]<8'h10 || job_offsets[j*8+:2]!=0))
                bad_offsets=1;
    end
    assign job_ready=state==IDLE && !fault_latched && !memory_fault;
    assign completion_valid=state==COMPLETE;
    assign m_wstrb=4'b1111;
    assign active_kernel=(kernel_base-CONTROL_MIN)>>16;
    initial if(MAX_ARGS<1 || MAX_ARGS>16 || TIMEOUT_CYCLES<1 || POLL_CYCLES<1)
        $fatal(1,"Invalid HLS bridge limits");
    task issue_read(input [31:0] address,input [1:0] kind);
        begin m_araddr<=address;m_arvalid<=1;read_kind<=kind;state<=R_ADDR;end
    endtask
    task issue_write(input [31:0] address,input [31:0] value,input bit is_start);
        begin
            m_awaddr<=address;m_wdata<=value;m_awvalid<=1;m_wvalid<=1;
            start_write<=is_start;if(is_start)started<=1;state<=WRITE;
        end
    endtask
    task complete(input [31:0] error);
        begin completion_error<=error;state<=COMPLETE;end
    endtask
    task next_argument_or_start;
        begin
            if(arg_index<arg_count)
                issue_write(kernel_base+offsets[arg_index*8+:8],values[arg_index*32+:32],0);
            else issue_write(kernel_base,1,1);
        end
    endtask
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;read_kind<=CHECK;kernel_base<=0;meta_base<=0;expected_magic<=0;
            offsets<=0;values<=0;arg_count<=0;arg_index<=0;errors<=0;age<=0;delay_age<=0;
            verify_meta<=0;check_magic<=0;status_zero<=0;started<=0;finished<=0;start_write<=0;
            status_offset<=0;completion_token<=0;completion_error<=0;result0<=0;result1<=0;
            fault_latched<=0;m_awaddr<=0;m_wdata<=0;m_araddr<=0;
            m_awvalid<=0;m_wvalid<=0;m_bready<=0;m_arvalid<=0;m_rready<=0;
        end
        else begin
            if(state!=IDLE && state!=COMPLETE)begin
                if(age!=32'hffffffff)age<=age+1;
                if(expired || memory_fault)begin errors<=effective_error;fault_latched<=1;end
            end
            case(state)
                IDLE:if(job_valid && job_ready)begin
                    completion_token<=job_token;completion_error<=0;result0<=0;result1<=0;
                    kernel_base<=job_kernel_base;meta_base<=job_meta_base;expected_magic<=job_expected_magic;
                    offsets<=job_offsets;values<=job_values;arg_count<=job_arg_count;arg_index<=0;
                    verify_meta<=job_verify;check_magic<=job_check_magic;status_zero<=job_status_zero;
                    status_offset<=job_status_offset;errors<=0;age<=0;started<=0;finished<=0;
                    if(job_kernel_base[15:0]!=0 || job_kernel_base<CONTROL_MIN ||
                        job_kernel_base>CONTROL_MAX || job_meta_base[1:0]!=0 ||
                        job_status_offset[1:0]!=0 || job_arg_count>MAX_ARGS || bad_offsets)
                        complete(ERR_ARGUMENT);
                    else issue_read(job_kernel_base,CHECK);
                end
                R_ADDR:if(m_arvalid && m_arready)begin m_arvalid<=0;m_rready<=1;state<=R_DATA;end
                R_DATA:if(m_rvalid && m_rready)begin
                    m_rready<=0;
                    if(m_rresp!=0)begin
                        errors<=effective_error|ERR_BUS;fault_latched<=1;
                        if(!started || finished)complete(effective_error|ERR_BUS);
                        else state<=HALT;
                    end
                    else case(read_kind)
                        CHECK:if(!m_rdata[2])begin fault_latched<=1;complete(effective_error|ERR_BUSY);end
                            else if(effective_error!=0)complete(effective_error);
                            else next_argument_or_start;
                        POLL:if(m_rdata[1] || (expired && m_rdata[2]))begin
                            finished<=1;
                            // AP completion is not a replacement for observing
                            // all target-core DMA responses. Do not include
                            // this bridge's own register reads in that guard.
                            state<=WAIT_DMA;
                        end
                        else begin delay_age<=0;state<=DELAY;end
                        META0:begin
                            result0<=m_rdata;
                            if(check_magic && m_rdata!=expected_magic)complete(effective_error|ERR_MAGIC);
                            else issue_read(meta_base+status_offset,META1);
                        end
                        META1:begin result1<=m_rdata;complete(effective_error|((status_zero && m_rdata!=0)?ERR_RESULT:0));end
                    endcase
                end
                WRITE:begin
                    if(m_awvalid && m_awready)m_awvalid<=0;
                    if(m_wvalid && m_wready)m_wvalid<=0;
                    if((!m_awvalid || m_awready) && (!m_wvalid || m_wready))begin m_bready<=1;state<=B_RESP;end
                end
                B_RESP:if(m_bvalid && m_bready)begin
                    m_bready<=0;
                    if(m_bresp!=0)begin
                        errors<=effective_error|ERR_BUS;fault_latched<=1;
                        if(!started)complete(effective_error|ERR_BUS);else state<=HALT;
                    end
                    else if(start_write)begin delay_age<=0;state<=DELAY;end
                    else if(effective_error!=0)complete(effective_error);
                    else if(arg_index+1<arg_count)begin
                        arg_index<=arg_index+1;
                        issue_write(kernel_base+offsets[(arg_index+1)*8+:8],values[(arg_index+1)*32+:32],0);
                    end
                    else begin arg_index<=arg_index+1;issue_write(kernel_base,1,1);end
                end
                DELAY:if(delay_age>=POLL_CYCLES-1)issue_read(kernel_base,POLL);
                    else delay_age<=delay_age+1;
                WAIT_DMA:if(kernel_dma_idle)begin
                    if(effective_error!=0)complete(effective_error);
                    else if(verify_meta)issue_read(meta_base,META0);
                    else complete(0);
                end
                COMPLETE:if(completion_ready)state<=IDLE;
                HALT:begin end
                default:state<=HALT;
            endcase
            // This acknowledgement means the common AXI fabric AND DMA
            // masters were reset. Mere controller timeout is insufficient.
            if(recover_request && common_bus_reset_ack)begin
                fault_latched<=0;errors<=0;age<=0;
                if(state!=IDLE && state!=COMPLETE)begin
                    m_awvalid<=0;m_wvalid<=0;m_bready<=0;m_arvalid<=0;m_rready<=0;
                    complete(effective_error|ERR_ABORT);
                end
            end
        end
    end
endmodule
