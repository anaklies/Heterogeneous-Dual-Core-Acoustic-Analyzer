// Generated from instrument_top.sv; do not hand edit.
module instrument_bd(
 (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk_compute CLK", X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF RAW:WIN:FFT:SCALAR:FEATURE:HOST, ASSOCIATED_RESET rst_n, FREQ_HZ 50000000" *)
 input wire  clk_compute,
 (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk_audio CLK", X_INTERFACE_PARAMETER = "FREQ_HZ 49162011" *)
 input wire  clk_audio,
 (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 rst_n RST", X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
 input wire  rst_n,
 input wire [5:0] mic_sd,
 output wire  mic_sck,
 output wire  mic_ws,
 output wire [4:0] mic_sck_copy, mic_ws_copy,
 input wire  common_bus_reset_ack,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW AWADDR", X_INTERFACE_PARAMETER = "PROTOCOL AXI4, DATA_WIDTH 32, ADDR_WIDTH 32, READ_WRITE_MODE WRITE_ONLY, HAS_BURST 1, MAX_BURST_LENGTH 16, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1" *)
 output wire [31:0] raw_awaddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW AWLEN" *)
 output wire [7:0] raw_awlen,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW AWSIZE" *)
 output wire [2:0] raw_awsize,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW AWBURST" *)
 output wire [1:0] raw_awburst,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW AWVALID" *)
 output wire  raw_awvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW AWREADY" *)
 input wire  raw_awready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW WDATA" *)
 output wire [31:0] raw_wdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW WSTRB" *)
 output wire [3:0] raw_wstrb,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW WLAST" *)
 output wire  raw_wlast,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW WVALID" *)
 output wire  raw_wvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW WREADY" *)
 input wire  raw_wready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW BRESP" *)
 input wire [1:0] raw_bresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW BVALID" *)
 input wire  raw_bvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 RAW BREADY" *)
 output wire  raw_bready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN AWADDR", X_INTERFACE_PARAMETER = "PROTOCOL AXI4, DATA_WIDTH 32, ADDR_WIDTH 32, READ_WRITE_MODE WRITE_ONLY, HAS_BURST 1, MAX_BURST_LENGTH 16, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1" *)
 output wire [31:0] win_awaddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN AWLEN" *)
 output wire [7:0] win_awlen,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN AWSIZE" *)
 output wire [2:0] win_awsize,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN AWBURST" *)
 output wire [1:0] win_awburst,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN AWVALID" *)
 output wire  win_awvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN AWREADY" *)
 input wire  win_awready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN WDATA" *)
 output wire [31:0] win_wdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN WSTRB" *)
 output wire [3:0] win_wstrb,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN WLAST" *)
 output wire  win_wlast,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN WVALID" *)
 output wire  win_wvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN WREADY" *)
 input wire  win_wready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN BRESP" *)
 input wire [1:0] win_bresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN BVALID" *)
 input wire  win_bvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 WIN BREADY" *)
 output wire  win_bready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT AWADDR", X_INTERFACE_PARAMETER = "PROTOCOL AXI4, DATA_WIDTH 32, ADDR_WIDTH 32, READ_WRITE_MODE READ_WRITE, HAS_BURST 1, MAX_BURST_LENGTH 16, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1" *)
 output wire [31:0] fft_awaddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT AWLEN" *)
 output wire [7:0] fft_awlen,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT AWSIZE" *)
 output wire [2:0] fft_awsize,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT AWBURST" *)
 output wire [1:0] fft_awburst,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT AWVALID" *)
 output wire  fft_awvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT AWREADY" *)
 input wire  fft_awready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT WDATA" *)
 output wire [31:0] fft_wdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT WSTRB" *)
 output wire [3:0] fft_wstrb,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT WLAST" *)
 output wire  fft_wlast,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT WVALID" *)
 output wire  fft_wvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT WREADY" *)
 input wire  fft_wready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT BRESP" *)
 input wire [1:0] fft_bresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT BVALID" *)
 input wire  fft_bvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT BREADY" *)
 output wire  fft_bready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT ARADDR" *)
 output wire [31:0] fft_araddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT ARLEN" *)
 output wire [7:0] fft_arlen,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT ARSIZE" *)
 output wire [2:0] fft_arsize,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT ARBURST" *)
 output wire [1:0] fft_arburst,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT ARVALID" *)
 output wire  fft_arvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT ARREADY" *)
 input wire  fft_arready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT RDATA" *)
 input wire [31:0] fft_rdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT RRESP" *)
 input wire [1:0] fft_rresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT RLAST" *)
 input wire  fft_rlast,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT RVALID" *)
 input wire  fft_rvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FFT RREADY" *)
 output wire  fft_rready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR AWADDR", X_INTERFACE_PARAMETER = "PROTOCOL AXI4, DATA_WIDTH 32, ADDR_WIDTH 32, READ_WRITE_MODE READ_WRITE, HAS_BURST 1, MAX_BURST_LENGTH 16, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1" *)
 output wire [31:0] scalar_awaddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR AWLEN" *)
 output wire [7:0] scalar_awlen,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR AWSIZE" *)
 output wire [2:0] scalar_awsize,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR AWBURST" *)
 output wire [1:0] scalar_awburst,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR AWVALID" *)
 output wire  scalar_awvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR AWREADY" *)
 input wire  scalar_awready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR WDATA" *)
 output wire [31:0] scalar_wdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR WSTRB" *)
 output wire [3:0] scalar_wstrb,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR WLAST" *)
 output wire  scalar_wlast,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR WVALID" *)
 output wire  scalar_wvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR WREADY" *)
 input wire  scalar_wready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR BRESP" *)
 input wire [1:0] scalar_bresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR BVALID" *)
 input wire  scalar_bvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR BREADY" *)
 output wire  scalar_bready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR ARADDR" *)
 output wire [31:0] scalar_araddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR ARLEN" *)
 output wire [7:0] scalar_arlen,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR ARSIZE" *)
 output wire [2:0] scalar_arsize,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR ARBURST" *)
 output wire [1:0] scalar_arburst,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR ARVALID" *)
 output wire  scalar_arvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR ARREADY" *)
 input wire  scalar_arready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR RDATA" *)
 input wire [31:0] scalar_rdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR RRESP" *)
 input wire [1:0] scalar_rresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR RLAST" *)
 input wire  scalar_rlast,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR RVALID" *)
 input wire  scalar_rvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 SCALAR RREADY" *)
 output wire  scalar_rready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FEATURE ARADDR", X_INTERFACE_PARAMETER = "PROTOCOL AXI4, DATA_WIDTH 32, ADDR_WIDTH 32, READ_WRITE_MODE READ_ONLY, HAS_BURST 1, MAX_BURST_LENGTH 1, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1" *)
 output wire [31:0] feature_araddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FEATURE ARVALID" *)
 output wire  feature_arvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FEATURE RREADY" *)
 output wire  feature_rready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FEATURE ARREADY" *)
 input wire  feature_arready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FEATURE RVALID" *)
 input wire  feature_rvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FEATURE RLAST" *)
 input wire  feature_rlast,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FEATURE RDATA" *)
 input wire [31:0] feature_rdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FEATURE RRESP" *)
 input wire [1:0] feature_rresp,
 inout wire  sensor_scl,
 inout wire  sensor_sda,
 inout wire imu_scl, imu_sda,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST AWADDR", X_INTERFACE_PARAMETER = "PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 12, READ_WRITE_MODE READ_WRITE, HAS_BURST 0, MAX_BURST_LENGTH 16, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1" *)
 input wire [11:0] host_awaddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST ARADDR" *)
 input wire [11:0] host_araddr,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST AWVALID" *)
 input wire  host_awvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST WVALID" *)
 input wire  host_wvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST BREADY" *)
 input wire  host_bready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST ARVALID" *)
 input wire  host_arvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST RREADY" *)
 input wire  host_rready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST WDATA" *)
 input wire [31:0] host_wdata,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST WSTRB" *)
 input wire [3:0] host_wstrb,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST AWREADY" *)
 output wire  host_awready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST WREADY" *)
 output wire  host_wready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST BVALID" *)
 output wire  host_bvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST ARREADY" *)
 output wire  host_arready,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST RVALID" *)
 output wire  host_rvalid,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST BRESP" *)
 output wire [1:0] host_bresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST RRESP" *)
 output wire [1:0] host_rresp,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 HOST RDATA" *)
 output wire [31:0] host_rdata,
 (* X_INTERFACE_INFO = "xilinx.com:signal:interrupt:1.0 irq INTERRUPT", X_INTERFACE_PARAMETER = "SENSITIVITY LEVEL_HIGH" *)
 output wire  irq,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FEATURE ARLEN" *)
 output wire [7:0] feature_arlen,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FEATURE ARSIZE" *)
 output wire [2:0] feature_arsize,
 (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 FEATURE ARBURST" *)
 output wire [1:0] feature_arburst
);
 instrument_top u_core(
  .clk_compute(clk_compute),
  .clk_audio(clk_audio),
  .rst_n(rst_n),
  .mic_sd(mic_sd),
  .mic_sck(mic_sck),
  .mic_ws(mic_ws),
  .mic_sck_copy(mic_sck_copy), .mic_ws_copy(mic_ws_copy),
  .common_bus_reset_ack(common_bus_reset_ack),
  .raw_awaddr(raw_awaddr),
  .raw_awlen(raw_awlen),
  .raw_awsize(raw_awsize),
  .raw_awburst(raw_awburst),
  .raw_awvalid(raw_awvalid),
  .raw_awready(raw_awready),
  .raw_wdata(raw_wdata),
  .raw_wstrb(raw_wstrb),
  .raw_wlast(raw_wlast),
  .raw_wvalid(raw_wvalid),
  .raw_wready(raw_wready),
  .raw_bresp(raw_bresp),
  .raw_bvalid(raw_bvalid),
  .raw_bready(raw_bready),
  .win_awaddr(win_awaddr),
  .win_awlen(win_awlen),
  .win_awsize(win_awsize),
  .win_awburst(win_awburst),
  .win_awvalid(win_awvalid),
  .win_awready(win_awready),
  .win_wdata(win_wdata),
  .win_wstrb(win_wstrb),
  .win_wlast(win_wlast),
  .win_wvalid(win_wvalid),
  .win_wready(win_wready),
  .win_bresp(win_bresp),
  .win_bvalid(win_bvalid),
  .win_bready(win_bready),
  .fft_awaddr(fft_awaddr),
  .fft_awlen(fft_awlen),
  .fft_awsize(fft_awsize),
  .fft_awburst(fft_awburst),
  .fft_awvalid(fft_awvalid),
  .fft_awready(fft_awready),
  .fft_wdata(fft_wdata),
  .fft_wstrb(fft_wstrb),
  .fft_wlast(fft_wlast),
  .fft_wvalid(fft_wvalid),
  .fft_wready(fft_wready),
  .fft_bresp(fft_bresp),
  .fft_bvalid(fft_bvalid),
  .fft_bready(fft_bready),
  .fft_araddr(fft_araddr),
  .fft_arlen(fft_arlen),
  .fft_arsize(fft_arsize),
  .fft_arburst(fft_arburst),
  .fft_arvalid(fft_arvalid),
  .fft_arready(fft_arready),
  .fft_rdata(fft_rdata),
  .fft_rresp(fft_rresp),
  .fft_rlast(fft_rlast),
  .fft_rvalid(fft_rvalid),
  .fft_rready(fft_rready),
  .scalar_awaddr(scalar_awaddr),
  .scalar_awlen(scalar_awlen),
  .scalar_awsize(scalar_awsize),
  .scalar_awburst(scalar_awburst),
  .scalar_awvalid(scalar_awvalid),
  .scalar_awready(scalar_awready),
  .scalar_wdata(scalar_wdata),
  .scalar_wstrb(scalar_wstrb),
  .scalar_wlast(scalar_wlast),
  .scalar_wvalid(scalar_wvalid),
  .scalar_wready(scalar_wready),
  .scalar_bresp(scalar_bresp),
  .scalar_bvalid(scalar_bvalid),
  .scalar_bready(scalar_bready),
  .scalar_araddr(scalar_araddr),
  .scalar_arlen(scalar_arlen),
  .scalar_arsize(scalar_arsize),
  .scalar_arburst(scalar_arburst),
  .scalar_arvalid(scalar_arvalid),
  .scalar_arready(scalar_arready),
  .scalar_rdata(scalar_rdata),
  .scalar_rresp(scalar_rresp),
  .scalar_rlast(scalar_rlast),
  .scalar_rvalid(scalar_rvalid),
  .scalar_rready(scalar_rready),
  .feature_araddr(feature_araddr),
  .feature_arvalid(feature_arvalid),
  .feature_rready(feature_rready),
  .feature_arready(feature_arready),
  .feature_rvalid(feature_rvalid),
  .feature_rlast(feature_rlast),
  .feature_rdata(feature_rdata),
  .feature_rresp(feature_rresp),
  .sensor_scl(sensor_scl),
  .sensor_sda(sensor_sda),
  .imu_scl(imu_scl), .imu_sda(imu_sda),
  .host_awaddr(host_awaddr),
  .host_araddr(host_araddr),
  .host_awvalid(host_awvalid),
  .host_wvalid(host_wvalid),
  .host_bready(host_bready),
  .host_arvalid(host_arvalid),
  .host_rready(host_rready),
  .host_wdata(host_wdata),
  .host_wstrb(host_wstrb),
  .host_awready(host_awready),
  .host_wready(host_wready),
  .host_bvalid(host_bvalid),
  .host_arready(host_arready),
  .host_rvalid(host_rvalid),
  .host_bresp(host_bresp),
  .host_rresp(host_rresp),
  .host_rdata(host_rdata),
  .irq(irq)
 );
 assign feature_arlen=8'd0; assign feature_arsize=3'd2; assign feature_arburst=2'b01;
endmodule
