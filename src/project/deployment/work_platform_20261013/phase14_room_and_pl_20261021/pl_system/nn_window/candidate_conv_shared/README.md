# Shared convolution activation memory candidate

This candidate copies candidate_bias_bram into a new directory. It keeps all
weights, fixed formats, lookup tables, static bias alignment and bias banking.
The convolution output is now one12x864 banked RAM passed directly to depth12.
The depth12 copy into a second12x864 RAM is removed. Channel/frequency/time
layout and arithmetic do not change.

The one affected existing-window C regression passed:76576 int16 network
outputs,18 counters and the normalized direction vector are unchanged.
No training, new room simulation or audio RTL simulation was performed.

One75MHz HLS build completed in tmp/p16_nn_convshared. Relative to
candidate_bias_bram: LUT21804 ->21592; FF15788 ->15638;
DSP85 ->83; BRAM18K216 ->200. Best latency3848402cycles,
worst44527833cycles, estimated clock9.733ns. These are HLS estimates.

The memory port structure changed, so the old single-pair RTL cosimulation
does not automatically certify this new full-window memory interface.
Whole-system timing, DDR contention and continuous10Hz remain unverified.

Use probe.cfg for reproduction only after relevant changes. The existing
reports, C_ACCEPTANCE.json and RESOURCE_COMPARISON.json are reusable evidence.
All earlier NN candidates and frozen files remain unchanged.
