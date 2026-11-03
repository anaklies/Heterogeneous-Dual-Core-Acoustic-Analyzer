# Acquisition and semantic gaps that must remain explicit

- Native `stream_fft.cpp` already emits RMS/peak/peak-to-peak/mean/dBFS/crest/
  clip-count/nonzero-valid at each channel's words7171..7178. Expose these
  actual P0 fields. Silence dBFS is encoded0 with nonzero-valid0; do not display
  it as a valid0dBFS measurement. No replacement PL producer is needed.
- `energy_change` now has a PL mean-square temporal delta producer; the old
  mapped flux producer is kept only for `spectral_flux`. `band_tracking` now
  has a configurable FFT-band integration+delta producer. First delta is invalid.
- A/C/Z is spectral relative weighting. Captured FAST/SLOW is an independent
  exact **Z/unweighted** recurrence. There is no combined A/C time-filtered
  FAST/SLOW producer; do not report the two independent outputs as that result.
- Room functions normally consume an explicitly supplied onset-trimmed measured
  mono IR. Optional `*_prepare_impulse` plans now accept a **declared clap or
  impulse** capture of2*n mono samples, convert in PL, find the first10%-of-peak
  crossing within firstn, and shift exactlyn samples in PL. This is only an
  approximate impulsive room response, without excitation deconvolution or
  certified RIR extraction. Arbitrary speech remains rejected. Read summary
  words28..31 before the main program clears them and require valid1.
- Zoom and room producers consume normalized float32 FS. Auxiliary
  `*_prepare_PCM24.json/.smp` plans now perform PL-only in-place conversion of
  bit-preserving PCM24 captures. Load main constants before capture, convert,
  then reload main code/context without clearing captured workspace. The room
  plain PCM conversion does not detect an onset; the optional experimental
  impulse preparation is separately gated and described above.
- Relative insulation now has `relative_insulation_verified` with its PL
  metadata gate enabled. Select it only after two actual PL band-energy
  captures have matching gain/measurement-chain/source/grid metadata. The
  original metadata-false plan remains invalid; assembly does not acquire A/B.
- NC/NR now integrates actual pinned FFT PSD at the exact frozen standard
  octave centers directly in PL, then applies the unchanged NR/NC curve.
  This closes the default base2 octave-grid mismatch. Twelve family/channel
  variants are provided. An explicit nominal reference is accepted without
  implying physical calibration: PS requires referenceConfirmed=true,
  nonempty calibrationSource and finite explicit referenceOffsetDb. PL checks
  private output30==1 and reads offset from output31. Zero-initialized input
  remains invalid; valid nominal outputs have estimated1 and no SPL certificate.
- STIPA needs separately acquired reference and received active test traces,
  n>=720000 at nominal48kHz, capture validation and all101 stages. Code is
  precompiled, including42 unique weight pages, each with size and SHA256.
  No arbitrary-speech/live/certified STIPA claim is supported.
- Spectrum freeze/A/B needs explicit matching A and B PL power snapshots in
  the private input buffer. Copying/fetching is host orchestration, not CPU DSP.
- Spatial grid/peaks are manual DAS configuration/result views, not automatic
  source tracking. STFT is a series of actually retained pinned FFT frames;
  the gateway must label its retained cadence and dropped frames accurately.

These are input/meaning gates, not excuses to return a fabricated valid result.
No RTL, formal0A, frozen profile or historical release was modified here.
