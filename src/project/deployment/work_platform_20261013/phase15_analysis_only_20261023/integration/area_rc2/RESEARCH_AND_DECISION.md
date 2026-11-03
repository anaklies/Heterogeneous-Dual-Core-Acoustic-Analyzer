# RC2 bounded resource optimization

## Sources reviewed before implementation

- AMD, UG949, 2025.2, [Reducing Control Sets](https://docs.amd.com/r/2025.2-English/ug949-vivado-design-methodology/Reducing-Control-Sets). A 7-series Slice has shared register control signals. Unneeded reset/enable diversity can restrict packing. This is a reason to review storage initialization and control, not a promise that a synthesis switch will recover area. The previous unsuccessful CE-remap experiment is not repeated.
- Josipovic et al., [Resource Sharing in Dataflow Circuits](https://www.epfl.ch/labs/lap/wp-content/uploads/2024/02/JosipovicDec23-Resource-Sharing-in-Dataflow-Circuits-TRETS.pdf), TRETS 2023, author-hosted 2024 PDF. Sharing needs both a performance argument and correct data ordering. Naive sharing can introduce deadlock. RC2 uses a bounded single-frame FSM with one outstanding read, not speculative shared queues.
- Zhao et al., [Area-Efficient Pipelining for FPGA-Targeted High-Level Synthesis](https://www.csl.cornell.edu/~zhiruz/pdfs/pipemap-dac2015.pdf), DAC 2015. Scheduling and mapping costs must be considered together; fewer arithmetic operations are not automatically fewer physical resources. Local synthesis is followed by one full implementation comparison.
- Xu and Josipovic, [CRUSH](https://doi.org/10.1145/3669940.3707273), ASPLOS 2025, and the [Dynamatic project](https://github.com/EPFL-LAP/dynamatic). Public metadata/abstract and project information were checked; full-paper retrieval was blocked at the queried endpoints. No claim is made to reproduce CRUSH or its credit scheme. Its broader warning about sharing and deadlock is consistent with the fully accessible TRETS work.
- [PandA-Bambu](https://github.com/ferrandi/PandA-bambu), primary open-source HLS project. Its project overview was inspected as a resource-aware HLS reference. RC2 does not change compiler or import unverified generated circuitry.

Searches also returned surveys and general advice. They were not used to infer precise savings. Failed URL retrievals were not treated as successfully read papers. Published benchmark savings are not attributed to SixMic3D.

## Selected change

Only `fft_event_features.sv` changes. Eight parallel band accumulators become one time-shared add/compare path with small distributed storage. Per-frame initialization replaces resetting the storage array. Output registers, configuration latching, timeout/error flags, saturation, rounding and host ABI remain unchanged.

Accumulator width is 45 bits because there are at most 6150 unsigned 32-bit addends, so the exact sum is smaller than 2**45 even for saturated invalid input. This is a range proof, not reduced acoustic precision. Q30 conversion is copied exactly from RC1. Division and output rounding remain identical.

## Bounded evidence and stopping rule

- Same-device local synthesis, after opt_design: baseline 2167 LUT / 1472 FF; candidate 1015 LUT / 958 FF. Both use zero DSP and zero BRAM. These are OOC numbers, not whole-board totals.
- Differential simulation: eight cases, exact channel/band/valid/fault/timestamp/read-order results, independent request stalls, silence, valid powers, saturation, invalid floats, illegal edges, response errors, bad last, timeout and output backpressure. Candidate maximum 84688 cycles in this model, versus the already-tested scheduler feature allowance of 200000 cycles. No arbitrary external-memory stall bound is claimed.
- Existing short event-chain regression with the changed feature implementation: PASS, including detector, raw writer drain, seal, host read and ID release. Saved inputs reused; no repeated full FFT/PCM arithmetic simulation.
- One whole-board candidate only. Keep it only when routed LUT saves at least 1000 and Slice saves at least 100, with nonnegative setup/hold slack and no DRC errors. Otherwise retain RC1. No further directive sweep or module redesign.

The 51 non-DOA function implementations, HLS kernels and profile programs are unchanged. Existing valid evidence is inherited. Physical board tests, complete service timing and external electrical IO signoff remain separate.

## Recovery-archive defect found during the full build

The restored RC1 project initially lacked the FFT Hann ROM `.dat` file next to its HDL. Synthesis emitted `Synth 8-4445`. That candidate build was stopped and its log retained as `rejected_missing_rom_*`; none of its area numbers or artifacts are accepted. The original RC1 hardware build used the original HLS source location, where this file exists, and had no such critical warning. This is a project-recovery defect, not evidence that the already generated RC1 bitstream has a zero window.

The RC2 project explicitly registers the data file, keeps it beside the actual restored ROM HDL, and supplies it in the synthesis working directory. Its SHA256 is `3f5f15dc763556adbb48be828365deb2a18f0bf030f23bf4c0bf5cb1c1e1c7e4`, identical to the data used by the verified production FFT RTL. Critical synthesis warnings now block implementation. The final packer also requires this coefficient data in the recovery archive. Baseline HDL for local reproduction is preserved separately; do not add baseline/testbench modules to production compile sources.
