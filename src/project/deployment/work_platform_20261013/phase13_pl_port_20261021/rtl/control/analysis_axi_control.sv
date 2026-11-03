`timescale 1ns / 1ps
// Single-clock AXI-Lite control, versioned capability and atomic result mailbox.
// AW/W arrive independently. Old/source-incompatible results are never fabricated.
module analysis_axi_control(
    input wire clk,rst_n,
    input wire [11:0] s_axi_awaddr,
    input wire s_axi_awvalid,
    output wire s_axi_awready,
    input wire [31:0] s_axi_wdata,
    input wire [3:0] s_axi_wstrb,
    input wire s_axi_wvalid,
    output wire s_axi_wready,
    output reg [1:0] s_axi_bresp,
    output reg s_axi_bvalid,
    input wire s_axi_bready,
    input wire [11:0] s_axi_araddr,
    input wire s_axi_arvalid,
    output wire s_axi_arready,
    output reg [31:0] s_axi_rdata,
    output reg [1:0] s_axi_rresp,
    output reg s_axi_rvalid,
    input wire s_axi_rready,
    input wire [63:0] implemented_mask,mandatory_missing_mask,
    input wire [31:0] algorithm_version,
    input wire [31:0] live_faults,active_config_version,timeout_count,dropped_samples,
    input wire cfg_applied,cfg_rejected,
    input wire [31:0] cfg_response_request_id,
    output reg cfg_valid,
    input wire cfg_ready,
    output reg [31:0] cfg_request_id,
    output reg [63:0] ps_periodic_mask,pc_periodic_mask,ps_optional_mask,pc_optional_mask,
    output reg pause_unrelated_periodic,
    output reg clear_fault,clear_counters,
    input wire result_valid,
    input wire [1023:0] result_words,
    output wire irq
);
    reg aw_pending,w_pending;
    reg [11:0] awaddr;
    reg [31:0] wdata;
    reg [3:0] wstrb;
    reg [31:0] shadow[0:9];
    reg [31:0] snapshot[0:31];
    reg [31:0] result_epoch,sticky_faults,ack_request;
    reg result_irq,cfg_ack,cfg_error;
    reg [2:0] irq_mask;
    reg fault_irq_pending;
    reg [31:0] previous_faults;
    wire [31:0] new_fault_edges=live_faults&~previous_faults;
    assign irq=|(irq_mask&{fault_irq_pending,(cfg_ack||cfg_error),result_irq});
    assign s_axi_awready=!aw_pending&&!s_axi_bvalid;
    assign s_axi_wready=!w_pending&&!s_axi_bvalid;
    assign s_axi_arready=!s_axi_rvalid||s_axi_rready;
    integer i,byte_index;
    reg [31:0] merged;
    always @(posedge clk) begin
        if(!rst_n)begin
            aw_pending<=0;w_pending<=0;awaddr<=0;wdata<=0;wstrb<=0;
            s_axi_bvalid<=0;s_axi_bresp<=0;s_axi_rvalid<=0;s_axi_rdata<=0;s_axi_rresp<=0;
            cfg_valid<=0;cfg_request_id<=0;ps_periodic_mask<=0;pc_periodic_mask<=0;
            ps_optional_mask<=0;pc_optional_mask<=0;pause_unrelated_periodic<=0;
            clear_fault<=0;clear_counters<=0;result_epoch<=0;sticky_faults<=0;
            result_irq<=0;cfg_ack<=0;cfg_error<=0;ack_request<=0;
            irq_mask<=0;fault_irq_pending<=0;previous_faults<=0;
            for(i=0;i<10;i=i+1)shadow[i]<=0;
            for(i=0;i<32;i=i+1)snapshot[i]<=0;
        end else begin
            clear_fault<=0;clear_counters<=0;
            sticky_faults<=sticky_faults|live_faults;
            previous_faults<=live_faults;
            if(|new_fault_edges)fault_irq_pending<=1;
            if(s_axi_bvalid&&s_axi_bready)s_axi_bvalid<=0;
            if(s_axi_rvalid&&s_axi_rready)s_axi_rvalid<=0;
            if(cfg_valid&&cfg_ready)cfg_valid<=0;
            if(cfg_applied||cfg_rejected)begin
                ack_request<=cfg_response_request_id;cfg_ack<=cfg_applied;cfg_error<=cfg_rejected;
            end
            if(result_valid)begin
                for(i=0;i<32;i=i+1)snapshot[i]<=result_words[i*32+:32];
                result_epoch<=result_epoch+1;result_irq<=1;
            end
            if(s_axi_awvalid&&s_axi_awready)begin aw_pending<=1;awaddr<=s_axi_awaddr;end
            if(s_axi_wvalid&&s_axi_wready)begin w_pending<=1;wdata<=s_axi_wdata;wstrb<=s_axi_wstrb;end
            if(aw_pending&&w_pending&&!s_axi_bvalid)begin
                aw_pending<=0;w_pending<=0;s_axi_bvalid<=1;s_axi_bresp<=0;
                if(awaddr[1:0]!=0)s_axi_bresp<=2;
                else if(awaddr>=12'h040&&awaddr<=12'h064)begin
                    merged=shadow[(awaddr-12'h040)>>2];
                    for(byte_index=0;byte_index<4;byte_index=byte_index+1)
                        if(wstrb[byte_index])merged[byte_index*8+:8]=wdata[byte_index*8+:8];
                    shadow[(awaddr-12'h040)>>2]<=merged;
                end else case(awaddr)
                    12'h028:if(wstrb[0])begin
                        if(wdata[0]&&!result_valid)result_irq<=0;
                        if(wdata[1]&&!cfg_applied&&!cfg_rejected)begin cfg_ack<=0;cfg_error<=0;end
                        if(wdata[2])begin
                            sticky_faults<=live_faults;
                            if(!(|new_fault_edges))fault_irq_pending<=0;
                        end
                    end
                    12'h02c:if(wstrb[0])begin clear_fault<=wdata[0];clear_counters<=wdata[1];end
                    12'h068:if(wstrb[0]&&wdata[0])begin
                        if(cfg_valid)s_axi_bresp<=2;
                        else begin
                            cfg_valid<=1;cfg_request_id<=shadow[0];
                            if(!cfg_applied&&!cfg_rejected)begin cfg_ack<=0;cfg_error<=0;end
                            ps_periodic_mask<={shadow[2],shadow[1]};pc_periodic_mask<={shadow[4],shadow[3]};
                            ps_optional_mask<={shadow[6],shadow[5]};pc_optional_mask<={shadow[8],shadow[7]};
                            pause_unrelated_periodic<=shadow[9][0];
                        end
                    end
                    12'h070:if(wstrb[0])irq_mask<=wdata[2:0];
                    default:s_axi_bresp<=2;
                endcase
            end
            if(s_axi_arvalid&&s_axi_arready)begin
                s_axi_rvalid<=1;s_axi_rresp<=0;s_axi_rdata<=0;
                if(s_axi_araddr[1:0]!=0)s_axi_rresp<=2;
                else if(s_axi_araddr>=12'h100&&s_axi_araddr<12'h180)
                    s_axi_rdata<=snapshot[(s_axi_araddr-12'h100)>>2];
                else if(s_axi_araddr>=12'h040&&s_axi_araddr<=12'h064)
                    s_axi_rdata<=shadow[(s_axi_araddr-12'h040)>>2];
                else case(s_axi_araddr)
                    12'h000:s_axi_rdata<=32'h534d4131;
                    12'h004:s_axi_rdata<=32'h00010000;
                    12'h008:s_axi_rdata<=algorithm_version;
                    12'h00c:s_axi_rdata<={27'd0,cfg_error,cfg_ack,result_irq,cfg_valid,irq};
                    12'h010:s_axi_rdata<=implemented_mask[31:0];
                    12'h014:s_axi_rdata<=implemented_mask[63:32];
                    12'h018:s_axi_rdata<=mandatory_missing_mask[31:0];
                    12'h01c:s_axi_rdata<=mandatory_missing_mask[63:32];
                    12'h020:s_axi_rdata<=sticky_faults;
                    12'h024:s_axi_rdata<=result_epoch;
                    12'h028:s_axi_rdata<={28'd0,fault_irq_pending,cfg_error,cfg_ack,result_irq};
                    12'h030:s_axi_rdata<=active_config_version;
                    12'h034:s_axi_rdata<=ack_request;
                    12'h038:s_axi_rdata<=timeout_count;
                    12'h03c:s_axi_rdata<=dropped_samples;
                    12'h070:s_axi_rdata<={29'd0,irq_mask};
                    default:s_axi_rresp<=2;
                endcase
            end
        end
    end
endmodule
