# Analysis-only PL continuation, 2026-10-23

User scope: remove NN and automatic DOA; keep other analysis functions in the
first delivery. No new product algorithms. Preserve all historical inputs and
builds. Work in this independent candidate directory, not a new product.

Ruling: the prior 52 entries remain historical. Disable NN and its dedicated
front end, not generic FFT or input-health checks. Keep manual DAS analysis.
Capability bits remain zero until actual end-to-end hardware acceptance.

Interfaces under test: shared FFT DDR command, analysis DDR command, event
power-summary stream and result backpressure, LCD asset/player input. These
are bounded public seams authorized by the existing user requirements.

Primary work: replace the 14x5 mixed fabric with separate data/control fabrics;
connect ordinary shared FFT and analysis, measure the new combined design.
Supplement only affected math/RTL checks. No historical PCM/frame replay.

LCD: independent worker owns lcd/. Event RTL: independent worker owns event/.
Main agent owns board/, fft/, interfaces/, analysis/ and final acceptance.
No board programming. No new bitstream before full physical gates pass.

Completed: real analysis-only BD without NN/automatic DOA/dedicated frontend;
ordinary shared 2048 FFT/IFFT, manual burst arena, separate data/control fabrics;
7 added scalar stages (peak hold, drift, harmonic bands, IR energy integration,
clarity, decay fit, correlation-to-F0). These are partial product chains.

Tests: final FFT vendor C model 20480 values +3 rejected descriptors; six-channel
PCM24 -> FFT -> PSD -> band integration C connection 24 checks; new scalar math
11 comparisons +7 invalid/alias and1 invalid fit checks. Old13 formula body matches exactly.
Event summary RTL36 checks. Analysis-only command adapter RTL249 checks.
Interface codec64bit roundtrip and7 rejection cases. LCD ARM/QEMU asset evidence.

Actual bugs fixed: quiet Schroeder tails lost by subtracting from a large total;
quiet clarity late energy lost by total-minus-early; overlapping DDR inputs and
outputs accepted at the kernel boundary. All have bounded numerical regressions.
Review records remain unchanged; the last two findings came from independent
GPT review. DeepSeek event review was incomplete with no usable text, not PASS.

Ruling: JOB cannot read DDR after fabric separation. New analysis_job_bridge
binds status verification to actual HLS registers 0x44A30060/0x44A40040 and
rejects old NN addresses, wrong argument counts and register order. Its core is
the unchanged previously tested bridge with explicit analysis-only limits.
The adapter still needs global scheduler/DMA-idle wiring in the physical top.

No periodic missing-pulse analysis added. Event loss means relative level drop.
Eight band indices do not imply arbitrary-Hz configuration end-to-end. Original
software event TP/FN is not the new RTL detector's performance result.

Final resource result: compact three-clock 3SI/1MI data fabric replaces the
cascaded data fabrics/converters. Same algorithm IP: LUT49334 ->45296,
FF48618 ->44012, DSP89 and BRAM36eq23 unchanged. Unique controlsets1779 ->1424.
Compact synthesis has zero unresolved blackboxes. SetupWNS+0.923ns but
holdWHS-3.255ns, so no final timing/physical acceptance or bitstream.

Evidence count clarification: the earlier review was told eight invalid cases;
the precise split is seven rejected inputs/aliases plus one invalid/unclosed fit.
No math rerun was needed for correcting that bookkeeping. No claim of tests
being run by the static reviewer is made.

LCD service audit: inherited runtime.env contains shell export lines, not valid
systemd EnvironmentFile syntax. Service now sets its known QtCore library path
explicitly. Preserve the shared /run/sixmic directory when optional player stops.
No actual service installation or old startup modification occurred.
