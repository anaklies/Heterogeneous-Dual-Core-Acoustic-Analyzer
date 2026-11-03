// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2025.2 (64-bit)
// Tool Version Limit: 2025.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2025 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
// control
// 0x00 : Control signals
//        bit 0  - ap_start (Read/Write/COH)
//        bit 1  - ap_done (Read/COR)
//        bit 2  - ap_idle (Read)
//        bit 3  - ap_ready (Read/COR)
//        bit 7  - auto_restart (Read/Write)
//        bit 9  - interrupt (Read)
//        others - reserved
// 0x04 : Global Interrupt Enable Register
//        bit 0  - Global Interrupt Enable (Read/Write)
//        others - reserved
// 0x08 : IP Interrupt Enable Register (Read/Write)
//        bit 0 - enable ap_done interrupt (Read/Write)
//        bit 1 - enable ap_ready interrupt (Read/Write)
//        others - reserved
// 0x0c : IP Interrupt Status Register (Read/TOW)
//        bit 0 - ap_done (Read/TOW)
//        bit 1 - ap_ready (Read/TOW)
//        others - reserved
// 0x10 : Data signal of input_r
//        bit 31~0 - input_r[31:0] (Read/Write)
// 0x14 : Data signal of input_r
//        bit 31~0 - input_r[63:32] (Read/Write)
// 0x18 : reserved
// 0x1c : Data signal of phase
//        bit 31~0 - phase[31:0] (Read/Write)
// 0x20 : Data signal of phase
//        bit 31~0 - phase[63:32] (Read/Write)
// 0x24 : reserved
// 0x28 : Data signal of support
//        bit 31~0 - support[31:0] (Read/Write)
// 0x2c : Data signal of support
//        bit 31~0 - support[63:32] (Read/Write)
// 0x30 : reserved
// 0x34 : Data signal of logits
//        bit 31~0 - logits[31:0] (Read/Write)
// 0x38 : Data signal of logits
//        bit 31~0 - logits[63:32] (Read/Write)
// 0x3c : reserved
// 0x40 : Data signal of vector
//        bit 31~0 - vector[31:0] (Read/Write)
// 0x44 : Data signal of vector
//        bit 31~0 - vector[63:32] (Read/Write)
// 0x48 : reserved
// 0x4c : Data signal of metadata
//        bit 31~0 - metadata[31:0] (Read/Write)
// 0x50 : Data signal of metadata
//        bit 31~0 - metadata[63:32] (Read/Write)
// 0x54 : reserved
// 0x58 : Data signal of counters
//        bit 31~0 - counters[31:0] (Read/Write)
// 0x5c : Data signal of counters
//        bit 31~0 - counters[63:32] (Read/Write)
// 0x60 : reserved
// (SC = Self Clear, COR = Clear on Read, TOW = Toggle on Write, COH = Clear on Handshake)

#define XNN_WINDOW_CONTROL_ADDR_AP_CTRL       0x00
#define XNN_WINDOW_CONTROL_ADDR_GIE           0x04
#define XNN_WINDOW_CONTROL_ADDR_IER           0x08
#define XNN_WINDOW_CONTROL_ADDR_ISR           0x0c
#define XNN_WINDOW_CONTROL_ADDR_INPUT_R_DATA  0x10
#define XNN_WINDOW_CONTROL_BITS_INPUT_R_DATA  64
#define XNN_WINDOW_CONTROL_ADDR_PHASE_DATA    0x1c
#define XNN_WINDOW_CONTROL_BITS_PHASE_DATA    64
#define XNN_WINDOW_CONTROL_ADDR_SUPPORT_DATA  0x28
#define XNN_WINDOW_CONTROL_BITS_SUPPORT_DATA  64
#define XNN_WINDOW_CONTROL_ADDR_LOGITS_DATA   0x34
#define XNN_WINDOW_CONTROL_BITS_LOGITS_DATA   64
#define XNN_WINDOW_CONTROL_ADDR_VECTOR_DATA   0x40
#define XNN_WINDOW_CONTROL_BITS_VECTOR_DATA   64
#define XNN_WINDOW_CONTROL_ADDR_METADATA_DATA 0x4c
#define XNN_WINDOW_CONTROL_BITS_METADATA_DATA 64
#define XNN_WINDOW_CONTROL_ADDR_COUNTERS_DATA 0x58
#define XNN_WINDOW_CONTROL_BITS_COUNTERS_DATA 64

