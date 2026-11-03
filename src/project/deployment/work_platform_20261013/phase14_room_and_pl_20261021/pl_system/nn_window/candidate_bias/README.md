# Exact matrix bias alignment candidate

This independent candidate preserves the accepted parent nn_window and the old V4 files.

Measured cause: the baseline matrix12 hierarchy has eleven direct align instances and one finish-pipeline align. Each is reported as 958 LUT and 202 FF. The first eleven plus the remaining lane align are not ROM padding; the lane initialization calls a generic 64-bit variable-shift align with dynamic fraction parameters.

Change: align each bias inside its kind switch with a constant positive scale. The only matrix12 caller always sets input fraction10 for point/embed/GRU-input and14 for GRU-hidden/phase/support. Therefore all six bias conversions are exact constant left shifts, with shifts9,8,9,13,13,13. Signed multiplication by a power of two preserves the previous signed rounding semantics, because none of these conversions rounds. Invalid rows remain zero. The shared matrix engine, weights, finish path, GRU, nonlinear LUTs, and window aggregation are unchanged.

Scope: matrix12 remains an internal function with exactly one caller. This optimization relies on the caller's kind/input-fraction mapping; it is not a general-purpose matrix API accepting arbitrary fractions.

Validation: check_window.py uses the existing room0_speech Q11 window and existing fixed golden. All76576 network outputs and18 original counters are bit exact. The normalized1890-element vector and metadata are unchanged. This is one requested regression of changed implementation, not a rerun of unrelated acoustic tests.

Build: probe.cfg requests75MHz onxc7z020clg484-2. The unique candidate probe uses tmp/p15_nnwindow_bias. No RTL cosim, full PCM, acoustic experiment or board implementation is performed. See RESOURCE_COMPARISON.json for measured HLS results and limitations after completion.

## Single HLS result

LUT32721 ->21735 (-10986,33.6% reduction); FF18411 ->15227 (-3184). DSP85 andBRAM18K234 unchanged. matrix12 LUT13206 ->2964. Best cycles4072037 ->4003997; worst45091668 ->44683428. Estimatedclock9.733ns unchanged. This is an HLS improvement only, not board placement or10Hz acceptance.
