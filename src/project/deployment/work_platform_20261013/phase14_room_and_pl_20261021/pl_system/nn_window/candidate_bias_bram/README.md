# Small bias ROM bank candidate

Parent candidate_bias is preserved. This candidate retains its exact static bias alignment and changes only storage directives for W_GRU_BIAS_IH_L0, W_GRU_BIAS_HH_L0, W_PHASE_BIAS inside matrix12.

Evidence: candidate_bias/matrix12_csynth.rpt records6BRAM18K for each of the144x16,144x16,126x16 bias ROMs. The declared payloads are2304,2304,2016bits, yet parallel read replication uses18BRAM18K.

Change: cyclic partition factor12 plus rom_1p/lutram binding. The unrolled12lane initialization and II=1 MAC loop remain unchanged. Weight tables, bias values, constant alignment shifts, all inference math, rounding, counters and window aggregation remain unchanged. This is one storage optimization applied to three tiny arrays, not a change to network parallelism.

Validation: one existing room0_speech fullwindow comparison yields76576 exact int16 outputs and18 exact counters against the original fixed golden. The1890-element aggregate vector is also unchanged. No new acoustic, RTL or PCM tests.

probe.cfg runs one75MHz HLS build in tmp/p15_nnwindow_bias_bram. RESOURCE_COMPARISON.json records actual results after completion. LUTRAM binding may cost LUT logic; only actual reports decide whether to retain. This candidate does not establish wholeboard fit, routed timing, DDR safety or continuous10Hz.

## Measured result

BRAM18K234 ->216 (-18 exactly). LUT21735 ->21804 (+69); FF15227 ->15788 (+561); DSP85 unchanged. Cycle bounds and initiation interval are unchanged, estimatedclock9.733ns. The three bias arrays use0BRAM in the actual memory report.64BRAM18K remain before adding other system modules. This is not wholeboard fit or10Hz acceptance.
