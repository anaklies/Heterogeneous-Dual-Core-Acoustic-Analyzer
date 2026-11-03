# PL feature registry and assembly plans

`REGISTRY.json` lists exactly 51 rows from the RC1 recovery map, excluding
`srpdnn_main`. An entry describes producer, actual parameter defaults and coupled
validators, acquisition requirements, output schema and plan. A successful build
means assembly/static coverage, never board or acoustic acceptance.

The fixed P1 profile has named routes for unchanged defaults. Parameter changes
must use the assembler to produce a private P2 plan; the runtime must reject
uncompiled parameter values. `energy_change` and `band_tracking` use the small
PL assemblers in `producers.py`, because spectral flux and fixed octave bands do
not express those two functions accurately.

Each `plans/*.smp` is headerless records:

```
LE32 wordOffset, LE32 wordCount, LE32 words[wordCount]
...
LE32 0, LE32 0
```

The accompanying JSON has `privateClearRanges`, `patchRecords`, `patchFile`,
SHA256, service descriptor and producer metadata. There is no implicit clear.
Only table words `[525312,525376)` and private words starting at `1048576` may
be written. P0 and P1 are never part of a patch. All addresses are arena word
indices, not byte addresses. Disable and drain P1/P2 before uploading, rekey the
session/config/generation consistently, upload validated real input, and publish
only a matching DONE result. All plans initially carry identity1; runtime must
rekey descriptor words11,12,14 for each slot as a locked transaction.

Channel-sensitive producers include exact compiled `variants`: six channels for
single-channel programs, and30 ordered distinct pairs for pair programs. Match
all requested parameters against `completeParams`; `params` shows only the
channel/pair changes. Nondefault bands/thresholds/angles still require explicit
reassembly. Existing P1 default-route metadata never changes in these variants.
Paths in registry metadata use forward slashes for Linux.

Room decay/clarity and filtered spectral decay also have optional experimental
`*_prepare_impulse` plans. Capture exactly2*n real mono PCM24 samples at
output+32 after initializing the main private allocation once. Require an
explicit clap/impulse stimulus declaration. The preparation converts in PL,
finds firstn peak and first crossing at10%peak, then forward-copies exactlyn
samples from that onset to output+32. `compile_impulse_prepare` permits another
threshold fraction in(0,1] through explicit reassembly. Summary output[28] is
the raw uint32 onset index, [29] peakFS, [30]valid and [31]thresholdFS. Read it
and require valid1 before loading the main code/context without clearing input;
the main algorithm clears its summary header. This optional mode estimates an
impulsive room response and does not deconvolve/certify an RIR or accept speech.
Filtered spectral decay uses the same confirmed ir_offset32 layout, so its
input can use this preparation before the existing PL bandpass+decay program.

`relative_insulation_verified` is a separately compiled metadata-matched plan;
the PS must establish actual matching A/B captures before selecting it.
`noise_rating` integrates the pinned PSD into NR/NC standard-center octaves
and evaluates the existing curve entirely on PL. Select one of12 family/channel
variants, then require explicit caller `referenceConfirmed`, nonempty
`calibrationSource` and finite `referenceOffsetDb`. Serialize float32 confirmed1
at output+30 and the reference offset at output+31 after the initial clear.
The program preserves those two inputs and gates on confirmed exactly1.
No reference is inferred from zeros. Valid nominal estimates return estimated1,
without claiming calibrated SPL or certified NC/NR measurement.

The default `directed_das` plan is the existing manual DAS program using its
private angle-load mode. Serialize finite float32 azimuth[-360,360] degrees at
output+0 and elevation[-90,90] at output+1 before **each** invocation. PL computes
all trig/beam arithmetic and overwrites these inputs with the result only after
loading both angles. This managed mode uses the local array frame only, with
default first_bin1/count128 and unchanged source-rate/sound-speed constraints.
`runtimeInput` supplies absolute and relative input addresses; parameterPolicy
explicitly permits only the two angle parameters to vary without reassembly.

STIPA contains101 ordered stages. A stage patch resets only its scalar context
and16-word header; it must retain both captured traces and all intermediate
results. Fit weights are configuration coefficients reused across trace0/1.
`--stipa-weights` materializes42 unique720000-word coefficient files and adds
their paths to stage metadata. Apply each weight file at its stated wordOffset
after the prior stage finishes and before starting the fit. Final public result
is output[0:3]; ratio/validation details are at output+4*n. All stages are
assembled with confirmed=true, but the gateway must require an actual verified
reference/received capture before allowing the graph. Merely setting a Boolean
does not satisfy acquisition.

Build in an environment with NumPy/SciPy (no signal is processed):

```
python build_plans.py
python build_plans.py --stipa-weights
python build_plans.py --feature band_tracking --params '{"low":200,"high":3000}' --output customized
python check_plans.py
```

The default host Python here needs `PYTHONPATH` pointing at the existing
`deployment/work_platform_20261013/phase10_dsp_engine_20261019/.venv/Lib/site-packages`.
This avoids a currently broken inherited venv ctypes DLL lookup. No dependency
installation is needed.
