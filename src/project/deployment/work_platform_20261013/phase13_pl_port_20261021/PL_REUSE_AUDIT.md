# Phase13 PL reuse audit

Date: 2026-10-21. Read-only inspection, no synthesis or historical source edits.

## Confirmed board build

- Device: `xc7z020clg484-2`, Vivado 2025.2. Physical top: `s7_chain/sixmic_s7_system_top.sv`; processing top: `sixmic_s7_pl_top.sv`.
- Explicit source/IP build: `s7_chain/build_s7_board_development.tcl`. Last recorded full-board inputs: `s7_chain/board_runs/s7_board_1792137141/source_paths.tsv`; copies remain under `tmp/s7_board_1792137141/input_sources`.
- Current routed baseline is old MUSIC 0A, not SRP-DNN: 45132 LUT, 40396 FF, 13109 Slice, 213 DSP, 94 BRAM36; WNS +0.999ns, WHS +0.036ns (S7_FINAL_ACCEPTANCE.md and this run's implementation_gate.json/reports). These numbers cannot describe the new algorithm.
- Board wrapper connects PS DDR/MIO/HDMI/LCD through `deployment/system_candidate_20261012/vendor_bd/design_1.bd`. External PL header is microphone/sensor I/O only, not external AXI.

## Reusable modules and boundaries

1. **Physical acquisition:** `sixmic3D_fpga/pl/board/sixmic_capture_bridge.v` plus its `i2s_timing_gen.v`, `i2s_rx_6ch.v`; six synchronous signed24 channels, actual audio clock about49.162MHz. `s7_pcm_input_register.sv` registers one complete144-bit sample. Reuse I2S timing/constraints, not a fresh unsynchronized serial receiver.
2. **Clock/reset/health:** external formal copies `clock_domain_guard.sv`, `pl_health_monitor.sv`; new development wrappers already gate bad acquisition and coordinate warm resets through `s7_acquisition_guard.sv`, `s7_result_epoch.sv`. Silence is explicitly not proof of a disconnected microphone. Read these modules before adding duplicate watchdogs.
3. **Sensor/pose:** formal `sensor_i2c_hub.sv`, `i2c_transaction_master.sv`, `air_sound_speed.sv`; development `s7_imu_rotation_q16.sv`, `s7_pose_mounting.sv`. Temperature/humidity/pressure and quaternion are already wired to old top. Exact sensor configuration is a separate sensor audit.
4. **FFT:** `s7_chain/s7_stft_6ch_shared.sv` is the development copy. One `fft_pl` AMD FFT9.1, runtime power-of-two2048 (old optional512);24-bit input,18-bit phase, unscaled natural-order output. Hann/mean subtraction,4096samples/channel BRAM ring, sample-end timestamps. **Long output is cropped to85 bins (5..341 step4)**. Therefore this existing path is not dense PSD/CSD/STFT for the new analyzer. The512/hop128 path was old CNN V3, not new1536/hop384 SRP-DNN. A1536 mixed-radix path remains necessary; do not silently replace it with2048 and keep weights.
5. **Matrix/search:** old sliding covariance, Hermitian EVD/MDL, MUSIC spatial search/refinement and trk9 exist and have bounded evidence. They are retired for the new product scope. Do not instantiate them together with SRP-DNN merely to preserve the old wrapper. Old CNN V3 RTL in `pl/rtl` is also not a port of J's small SRP-DNN.
6. **Result ABI:** `s7_packet_axi_mailbox.sv` is a52-word immutable result packet endpoint (ABI3), not bulk PCM. Independent AW/W capture, ACK-after-read, finite read timeout/SLVERR, frame/config/algorithm/epoch/timestamps and active/latched diagnostics. It rotates XYZ/velocity on read with a latched pose. Need a new analyzer result schema, not reinterpret old XYZ words as spectra.
7. **Clock crossing:** `s7_axi_lite_guarded_bridge.sv` crosses100MHz GP0/mailbox to49.162MHz algorithm clock and bounds reset/response behavior. Can be reused for control after preserving its handshake contract.

## Actual PS/DDR access

- Vendor BD `M_AXI_GP0 -> axi_interconnect_0 -> M_AXI_MAILBOX` exposes only the control/result aperture to this PL algorithm top.
- `S_AXI_HP0` is enabled but presently connected to `smartconnect_0/M00_AXI`; its existing master is the display VDMA. No audio AXI master/stream DMA or raw PCM bulk port is exposed in `sixmic_s7_system_top.sv`.
- Therefore new pre/post recording, neural activations/templates, long FFT scratch and optional PCM export **do not yet have an implemented acoustic DDR path**. Add a separately arbitrated HP port/DMA/master in a NEW BD copy, with address isolation and slow-consumer protection. HP0 being enabled does not prove audio DMA already exists.
- The existing PS Ethernet controller is enabled in vendor BD. Ethernet hardware recommendation should follow the board-manual audit; PS networking avoids adding a new PL MAC for<1MB/s raw PCM.

## Migration blockers that must remain explicit

- J small SRP-DNN weights/features/inference have no verified RTL/HLS implementation in the inspected PL tree. Int16 resource estimates in Phase12M are assumptions, not quantization acceptance or synthesized resources.
- Dense2048 analysis and1536 neural features are distinct numerical contracts; old85-bin MUSIC frontend cannot be advertised as all-new P0/P1/P2.
- Old routed design is98.56%Slice/96.82%DSP, but removing old EVD/search changes the design substantially. Only a NEW integrated synthesis/route can establish resources. Subtracting independent OOC figures is invalid.
- Existing mailbox is read-only data plus ACK and has no profile subscription/config writes. New atomic scheduler and versioned analyzer result interface are needed.
- Page exit saves switching/workload, not static LUT/DSP. Actual area savings require shared FFT/MAC/BRAM/scratch, and long P2 work must yield to mandatory P0 deadlines.

All paths above are relative to `C:/Users/sunxi/Desktop/sixmic3D` unless explicitly `sixmic3D_fpga`. Inspection only; no new whole-board fit or real hardware claim.
