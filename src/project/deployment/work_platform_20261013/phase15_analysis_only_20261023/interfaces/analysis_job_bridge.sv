`timescale 1ns/1ps
// Analysis-only adapter around the previously tested AXI command engine.
// JOB reaches control registers only. Status is read from HLS, never DDR.
module analysis_job_bridge #(
 parameter integer TIMEOUT_CYCLES=50000000,
 parameter integer POLL_CYCLES=256
)(
 input wire clk,rst_n,job_valid,
 output wire job_ready,
 input wire [31:0] job_token,job_kernel_base,
 input wire [4:0] job_arg_count,
 input wire [127:0] job_offsets,
 input wire [511:0] job_values,
 input wire memory_fault,kernel_dma_idle,
 output wire [1:0] active_kernel,
 output wire completion_valid,
 input wire completion_ready,
 output wire [31:0] completion_token,completion_error,result0,result1,
 output wire fault_latched,
 input wire recover_request,common_bus_reset_ack,
 output wire [31:0] m_awaddr,m_wdata,m_araddr,
 output wire m_awvalid,m_wvalid,m_bready,m_arvalid,m_rready,
 output wire [3:0] m_wstrb,
 input wire m_awready,m_wready,m_bvalid,m_arready,m_rvalid,
 input wire [1:0] m_bresp,m_rresp,
 input wire [31:0] m_rdata
);
 wire is_analysis=job_kernel_base==32'h44a30000;
 wire is_fft=job_kernel_base==32'h44a40000;
 reg descriptor_valid;
 always @* begin
   descriptor_valid=(is_analysis && job_arg_count==10)||(is_fft && job_arg_count==6);
   for(integer i=0;i<16;i=i+1)
     if(i<job_arg_count && job_offsets[i*8+:8]!=(8'h10+i*8))descriptor_valid=0;
 end
 hls_job_bridge #(.MAX_ARGS(16),.TIMEOUT_CYCLES(TIMEOUT_CYCLES),
   .POLL_CYCLES(POLL_CYCLES),.CONTROL_MIN(32'h44a30000),.CONTROL_MAX(32'h44a4ffff)) core (
   .clk(clk),.rst_n(rst_n),.job_valid(job_valid),.job_ready(job_ready),
   .job_token(job_token),.job_kernel_base(descriptor_valid?job_kernel_base:32'b0),
   .job_meta_base(job_kernel_base+(is_analysis?32'h60:32'h40)),
   .job_arg_count(job_arg_count),.job_offsets(job_offsets),.job_values(job_values),
   .job_verify(1'b1),.job_check_magic(1'b0),.job_status_zero(1'b1),
   .job_expected_magic(32'b0),.job_status_offset(8'b0),
   .memory_fault(memory_fault),.kernel_dma_idle(kernel_dma_idle),.active_kernel(active_kernel),
   .completion_valid(completion_valid),.completion_ready(completion_ready),
   .completion_token(completion_token),.completion_error(completion_error),
   .result0(result0),.result1(result1),.fault_latched(fault_latched),
   .recover_request(recover_request),.common_bus_reset_ack(common_bus_reset_ack),
   .m_awaddr(m_awaddr),.m_wdata(m_wdata),.m_araddr(m_araddr),
   .m_awvalid(m_awvalid),.m_wvalid(m_wvalid),.m_bready(m_bready),
   .m_arvalid(m_arvalid),.m_rready(m_rready),.m_wstrb(m_wstrb),
   .m_awready(m_awready),.m_wready(m_wready),.m_bvalid(m_bvalid),
   .m_arready(m_arready),.m_rvalid(m_rvalid),.m_bresp(m_bresp),.m_rresp(m_rresp),.m_rdata(m_rdata)
 );
endmodule
