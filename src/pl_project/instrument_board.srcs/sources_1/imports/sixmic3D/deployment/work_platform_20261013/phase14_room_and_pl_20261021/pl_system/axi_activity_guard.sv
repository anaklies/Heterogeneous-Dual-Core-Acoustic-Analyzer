`timescale 1ns / 1ps
// Observe the actual acoustic AXI master side. No data-path false paths or
// watchdog-driven withdrawal of VALID. rst_n must be a common bus reset.
module axi_activity_guard #(
    parameter integer MAX_PENDING=32
)(
    input wire clk,rst_n,
    input wire awvalid,awready,wvalid,wready,wlast,bvalid,bready,
    input wire arvalid,arready,rvalid,rready,rlast,
    input wire [1:0] bresp,rresp,
    input wire clear_response_fault,
    output wire quiescent,
    output reg response_fault,protocol_fault,
    output reg [31:0] error_responses,
    output wire [31:0] pending_reads,pending_write_addresses,pending_write_data
);
    localparam integer CW=$clog2(MAX_PENDING+1);
    reg [CW-1:0] reads,addresses,data_packets;
    reg partial_write;
    wire aa=awvalid&&awready,ww=wvalid&&wready;
    wire wl=ww&&wlast,bb=bvalid&&bready;
    wire rr=arvalid&&arready,rl=rvalid&&rready&&rlast;
    wire response_error=(bb&&bresp[1]) || (rvalid&&rready&&rresp[1]);
    assign pending_reads=reads;
    assign pending_write_addresses=addresses;
    assign pending_write_data=data_packets;
    assign quiescent=reads==0 && addresses==0 && data_packets==0 && !partial_write &&
        !protocol_fault && !awvalid && !wvalid && !arvalid && !rvalid && !bvalid;
    initial if(MAX_PENDING<1)$fatal(1,"MAX_PENDING must be positive");
    always @(posedge clk) begin
        if(!rst_n)begin
            reads<=0;addresses<=0;data_packets<=0;partial_write<=0;
            response_fault<=0;protocol_fault<=0;error_responses<=0;
        end
        else begin
            // AXI responses require a previously accepted request. A new
            // request on this edge cannot justify an orphan response.
            if((rl && reads==0) || (bb && (addresses==0 || data_packets==0)))
                protocol_fault<=1;
            if(ww)partial_write<=!wlast;
            case({rr,rl})
                2'b10:if(reads==MAX_PENDING)protocol_fault<=1;else reads<=reads+1;
                2'b01:if(reads==0)protocol_fault<=1;else reads<=reads-1;
                default:begin end
            endcase
            case({aa,bb})
                2'b10:if(addresses==MAX_PENDING)protocol_fault<=1;else addresses<=addresses+1;
                2'b01:if(addresses==0)protocol_fault<=1;else addresses<=addresses-1;
                default:begin end
            endcase
            case({wl,bb})
                2'b10:if(data_packets==MAX_PENDING)protocol_fault<=1;else data_packets<=data_packets+1;
                2'b01:if(data_packets==0)protocol_fault<=1;else data_packets<=data_packets-1;
                default:begin end
            endcase
            // Exact known-response errors may be cleared after draining.
            // Count loss/overflow invalidates quiescence until common reset.
            if(clear_response_fault && quiescent)response_fault<=0;
            if(response_error)begin
                response_fault<=1;
                if(error_responses!=32'hffffffff)error_responses<=error_responses+1;
            end
        end
    end
endmodule
