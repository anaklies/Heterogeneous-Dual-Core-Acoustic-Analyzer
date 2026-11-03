# SixMic3D Qt Quick chart components (frontend-charts v1)

Frozen contract: `apps/sixmic-desktop/docs/frontend/CHART_DATA_CONTRACT.md`

All drawing is Qt Quick **Canvas** (vector). Rasters for HeatmapChart /
PolarChart come from the Python `QQuickImageProvider` URL supplied by the page
(`image://plots/<kind>/<revision>`). Colours and fonts come from the `Theme` context
property (`ui/viewmodels/theme_source.py`); the components hardcode **no** theme colours
and no localisable UI strings - the page passes `emptyText`, `emptyReason`,
`busyText`, axis labels/units, legends and captions. Channel/category/meter
colours are passed by the page (`Theme.channelColors` is only a display fallback when
a per-item colour is omitted).

Integration: `import "../components/charts"` from pages, then use the file names as
types: `WaveformChart {}`, `LineChart {}`, `BarChart {}`, `HeatmapChart {}`,
`PolarChart {}`, `LevelMeter {}`, `TimelineChart {}`. No qmldir is required.
The page's `main.qml` must expose the `Theme` context property before loading.

## Files

| file | contract section |
|---|---|
| `WaveformChart.qml` | 1 - six-channel waveform, stacked/overlay, gap breaks, cursors, selection, zoom/pan |
| `LineChart.qml` | 2 - generic series chart, linear/log axes, A/B cursors, reference lines/bands |
| `BarChart.qml` | 3 - band bars, true center-frequency log layout, limit/reference overlays |
| `HeatmapChart.qml` | 4 - STFT/waterfall raster + axes + colour bar + click |
| `PolarChart.qml` | 5 - directional power polar/rect raster + colour bar + caption |
| `LevelMeter.qml` | 6 - vertical/horizontal level bars, invalid = dash, clip shape |
| `TimelineChart.qml` | 7 - transport timeline, events, gaps, selection, seek/scrub |
| `ChartUtil.js` | 1/2/5 ticks, number formatting, axis mapping, colour maps, empty/busy painters |
| `ChartGallery.qml` | QA-only page (deterministic synthetic data) for screenshots |

## Professional presentation additions (2026-10-25)

The dark palette follows the user's final request: pure black shell and plot backgrounds,
light cyan/yellow/magenta/teal channel traces and subdued major/minor grids.
BarChart supports `displayMode: "bars" | "steps"`, `uniformColor`, `traceColor`
and `levelGradient` (default true). Bars have a one-pixel gap and one shared
bottom-to-top viridis amplitude ramp, calibrated to the visible y-axis, rather
than restarting a decorative gradient at each bar top. Explicit dB domains are
preserved. BandsPage lets the user switch bars/steps; steps use the selected
channel's fixed color. Source colors and scientific scalar colors have different
roles.

`WaterfallChart.qml` is an additive display component, not an acoustic analysis
algorithm. It accepts `frames: [{time, points: [[frequencyHz, levelDb], ...]}]`,
`frequencyAxis`, `timeAxis`, and `colorScale`. The source must provide at most
48 ordered frames with at most 128 common frequency bins each, already extracted
for display. Oversized, absent or unusable data draws the supplied empty state.
Only adjacent, finite, aligned bins form mesh cells; gaps never become a fake
zero or an interpolated ridge. Frequency and time retain their supplied domains;
level is clipped to the color/height range. Drag adjusts projection; double-click
restores it. The mesh is cached between data/axis changes and perspective redraws.
SpectrumPage reads optional `stft.frames`; an image-only STFT cannot be converted
into numeric surface measurements. Production never uses the QA synthetic frames.

Run `tests/frontend/test_chart_presentation.py` for gap, bin-alignment, work-budget,
endpoint, dB zoom and constrained-title/action-layout checks. The gallery load
check also exports independent `waterfall_light.png` / `waterfall_dark.png` views.

The production workbench is PL-only. It accepts source-labelled data for known
PL families (FFT/PSD, octave, STFT, waterfall, coherence/phase/CSD, cepstrum,
manual DAS direction maps). Missing service metadata or absent actual data does
not create a chart card. No XY/matrix tools without a PL counterpart, audio-file
import, replay controls or PC offline analysis are exposed. Header FFT parameters
are read-only PL values; display-axis switching does not pretend to configure PL.

Interface limitations and acceptance evidence:
`apps/sixmic-desktop/docs/frontend/ACOUSTIC_UI_PL_INTERFACE_20261025.md`.

### Existing shared behaviour

* `interactive`, `busy`, `emptyText`, `emptyReason` as in the contract. An empty/busy
  state never draws fake data; a busy state never draws data.
* HiDPI: Qt6.12 Canvas uses native logical coordinates and default canvasSize.
  Do not multiply canvasSize and manually scale the painter by DPR: that caused
  repeated zoom/cropping. Pixel-bound probes pass at 100/125/150/200%. PNG export
  uses the window DPR for its output size. See verify_chart_dpi.py.
* Repaint policy: no timers and no scan animations. Repaint happens only when a
  data/axis property changes, on `dataRevision` bumps, on Theme changes, on resize/DPI
  changes and during user interaction. Hidden items (`visible === false`) and unavailable
  canvases never request a repaint.
* Bounded work: waveform values are display-extracted by the page (<= 4096 / channel,
  contract). Series auto-range scans are sampled to at most 4096 points / series;
  waveform/line drawing skips points according to plot width. Gaps break polylines
  (never bridged).
* Log axes: values <= 0 are clipped (not drawn) and a dim `<= 0 x N` badge reports how
  many samples were clamped; 0 Hz never enters a log axis. For LineChart the page can
  pass `logClipText` to localise that badge.
* `grabToImage` on any chart root works (see the offscreen check); a `savePng` helper is
  not provided (optional in the contract - saving is the page's call).

## Additive (optional) properties - no contract behaviour removed

All components: `dataRevision: int` (bump to force a repaint when the page mutates the
same JS arrays), `busyText: string`.

* WaveformChart: `yUnit`, `xUnit`, `cursorLabelA/B`, `selectionLabel`.
* LineChart: `logClipText`, `cursorLabelA/B`.
* BarChart: `xLabel`, `xUnit`.
* LevelMeter: `clipText` (localised "CLIP" text next to the shape), `valueFormat`
  (default `%.1f`).
* TimelineChart: `eventLabelsVisible: bool`.
* BarChart categories accept an optional `centerFrequency: real` field. It is required
  for `xMode: "centerFrequency"` to place bars on a true log-frequency axis; without it
  the chart falls back to equal category spacing rather than inventing frequencies.

## Documented contract deviations / conventions

1. **selectionChanged(start,end) is a QML-impossible signal name next to a `selection`
   property** (QML auto-generates `selectionChanged()` for the property; declaring the
   signal is a compile error - verified). WaveformChart and TimelineChart therefore emit
   the interaction signal **`selectionEdited(start, end)`** and keep the contract
   `selection` input property (automatic `selectionChanged()` still fires when the page
   updates it). Pages must connect `onSelectionEdited` (or read `chart.selection`).
2. **Normalised positions**: timeline `position`, `selection`, `gaps` and
   `events[].position` are all 0..1 of `durationSeconds` (the contract only spelled this
   out for position). Waveform `gaps` stay in the channel-array index domain as frozen
   in the contract.
3. **HeatmapChart raster mapping**: the provider image is stretched exactly onto the axis
   rectangle; the component overlays the 1/2/5 grid using the axis transform (linear or
   log). For a log frequency axis the provider must render rows in that same log
   geometry - the component does not resample the image.
4. **PolarChart raster mapping**: for `projection: "polar"` the provider must deliver a
   square raster rendered in polar space (azimuth 0 at the top, clockwise;
   `elevationRange.min` at the centre, `.max` at the outer edge). The component draws the
   matching ring/spoke frame. For `projection: "rect"` the raster maps linearly onto
   azimuth (x) / elevation (y).
5. **No image => explicit empty state**: HeatmapChart/PolarChart evaluate the page-supplied
   `emptyText`/`emptyReason`; a failed image load is also an empty state.
6. Sequential colour maps are viridis/cividis and the difference map is a zero-centred
   diverging map (`ChartUtil.js`). The Python provider must use the same map for the raster
   so the Canvas colour bar matches the image.

## Offscreen verification (no QML warnings/errors)

From `apps/sixmic-desktop`:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python.exe ui/qml/components/charts/_selftest/qml_load_check.py
```

The check loads `ChartGallery.qml` in a real (offscreen) window with the production
`ThemeSource`, instantiates all seven components, asserts zero QML warnings/errors, sends
click events to verify `seekRequested`/`pointClicked`, switches light->dark live, repeats the
load with `image://plots/...` URLs from a Python image provider and writes PNG screenshots
to `_selftest/out/`. Run it once with `QT_SCALE_FACTOR=2` to verify the 200% DPI path
(screenshots become 2x).

`_selftest/make_demo_rasters.py` regenerates the two demo rasters used only by
ChartGallery (`demo/heatmap_demo.png`, `demo/polar_demo.png`).


## FeatureChart (feature-workspace chart router, 2026-10-26)

`ui/qml/components/FeatureChart.qml` routes `App.featureWorkspace.chart` to the
professional chart for its `kind`. New code only **extends** the frozen components
above: no uPlot/ECharts/WebView/React, no new dependency, Canvas rendering only.

### Stable page API (ui-dev hosts this inside FeatureWorkspace)

```qml
FeatureChart {
    Layout.fillWidth: true
    Layout.fillHeight: true
    // optional overrides (all have App.featureWorkspace fallbacks):
    chart: App.featureWorkspace.chart     // default: read from App.featureWorkspace
    iconSource: App.iconSource(App.featureWorkspace.icon, Theme.textPrimary)
    titleOverride: ""; subtitleOverride: ""
    emptyText: ""                        // localised no-data text from the page
    framesUnavailableText: ""            // localised "producer frames unavailable" text
    sourceKindOverride: ""; sourceLabelOverride: ""   // e.g. localised test-fixture label
    validityOverride: ""; notesOverride: []
    showSourceBanner: true
    // optional localised tooltips for the compact toolbar (icon-only otherwise):
    fitTooltip; logTooltip; cursorTooltip; legendTooltip; threeDTooltip; saveTooltip
}
```

Read-only state for hosting pages/tests: `payload`, `kind`, `routeToken`,
`contentItem`, `featureId`, `chartBusy`, `emptyReasonText`, `sourceKind`,
`sourceLabel`, `validityText`, `hasSource`, `showFit/Log/Cursor/Legend/3DButton`,
`panelsResolved`. Signals: `imageCaptured(string path)`,
`saveFailed(string reason)`, `eventActivated(int index)`.

Save-image flow (view-only, never a PL task): the toolbar save button calls
`App.saveFeatureChart(featureId)` to obtain the target PNG path, then
`contentItem.grabToImage(...)` -> `result.saveToFile(path)` ->
`App.notifyFeatureSaved(path)`. If no path is returned the grabbed temporary URL
is emitted via `imageCaptured`. View toggles persist display preferences through
`App.setFeatureViewOption(featureId, key, value)` (keys `logX` / `cursor` /
`legend` / `2D3D`); no measurement slot is ever called.

### Payload conventions (facade -> FeatureChart, additive to CHART_DATA_CONTRACT)

Top level: `kind, chartRevision, title, subtitle, units, xAxis, yAxis,
series[], categories[], colorScale, imageUrl, markers[], referenceLines[],
referenceBands[], frames[], scalarRows[], text, emptyReason, notes, caption,
valueFormat, limitLine, referenceValues`.

* `panels[]` (dual kinds pair-spectra / coherence-phase / weighting / statistics):
  `[{render:"line"|"bars", title, subtitle, series, categories, xAxis, yAxis,
  markers, referenceLines, referenceBands, limitLine, referenceValues,
  showLegend, emptyText, emptyReason}]`. Fallbacks: `series[].panel` index
  grouping, then series units `rad`/`deg` split phase from coherence for
  `coherence-phase`; coherence panel is clamped to 0..1 when no y-axis is given.
* `series[]`: `{name,color,points:[[x,y],...],width,dashed,fill,visible,unit,
  role,panel}`; `role` drives ab-spectrum partitioning (`a`/`b`/`delta`).
  `points` may contain `null` y values; such gaps are never bridged.
* `bands`/`harmonic-bars`/`insulation-bars`: `categories[]` with
  `centerFrequency` for true log placement; `valid:false` renders the dash
  placeholder. `bands` uses the fixed octave ramp
  `#6A5ACD #4E6BD6 #3E8FC9 #37AFAF #72D6C9 #A9D96C #E2E649` (overridable via
  `bandRampFallback`/`chart.bandRamp` or `chart.colorScale.stops`) and a shared
  level colour bar; `bandRamp` is display-only.
* `stft`: `imageUrl` is the 2-D Viridis raster (built by the facade from
  `plot_images.heatmap_image`); `frames` must be
  `[{time: seconds, points: [[frequencyHz, level], ...]}]` (<=48 frames, <=128
  aligned bins) for the 3-D waterfall toggle. A raw matrix / unsupported shape,
  or a missing numeric frame grid, renders the explicit `framesUnavailableText`
  empty state - no time axis is invented. 2-D heatmap click sets a crosshair
  with the actual x/y readout.
* `das-map`: `imageUrl` polar/rect raster + `markers[]` auxiliary peaks in
  degrees `{x: azimuthDeg, y: elevationDeg, label, kind}`. The 2D/3D toolbar
  button toggles polar <-> rect projection. Caption text is page-supplied and
  must say this is relative directional power (not automatic DOA).
* `waveform`: `channels[{name,color,values,visible}]`, `gaps[{start,end}]`,
  `sampleRate`, `startSampleIndex`; >4096 samples/channel are display-extracted
  with the peak envelope (min/max per bucket, never averaged) and gaps remapped.
  No fake smoothing and no interpolation across gaps.
* `level-bars`: `meters[{label,color,value,peak,valid,clip}]` + `scale`;
  invalid shows the dash, never 0 dBFS.
* `scalars`: `scalarRows[{label,value,unit,valid,tone}]` instrument readout.
* `events`: `events[{position01,label,kind,downloadState,detail}]` +
  `timeAxis{min,max,label,unit}`; marker shape shows the download state
  (`downloaded` filled / `pending` hollow / `failed` cross); click emits
  `eventActivated(index)`. State labels come from `downloadLabels`.
* `stipa`: `stage{index,total,label}` (101 ticks), `indexValue/indexLabel/
  indexUnit/indexValid`, `scalarRows` (index/validity/certified). "certified"
  stays 0 - the component never claims certification.
* `noise-rating`: measured `series` + optional payload-supplied
  `referenceFamilies[{name,points,color,dashed}]` (the PC does not generate
  NC/NR reference tables or compute the rating), `scalarRows` estimate readouts
  and `note` reference statement.
* `capability`: `text` + optional `scalarRows`/`caption`; no measurements.
* Marker kinds: `peak` (diamond), `onset`/`event` (triangle), `band` (tick),
  `cursor` (circle). Markers are coordinate annotations only.

### New components (all under `charts/`)

| file | role |
|---|---|
| `ChartToolbar.qml` | title-left (page icon + short title) / compact ops right (fit, log-linear, A/B cursor, legend, 2D/3D, save). 32x32 targets, 20 px vector glyphs, no icon-theme dependency, no hardcoded text. |
| `SourceBanner.qml` | always-visible source token + validity + notes strip; `test-fixture` is highlighted and never presented as `pl-live`. |
| `ChartEmptyState.qml` | chart-internal explicit empty/busy state (named `Chart*` so it cannot shadow the shared `components/EmptyState.qml`). |
| `ScalarReadout.qml` | instrument-style scalar readout table; invalid rows show a dash. |
| `ReadoutStrip.qml` | compact horizontal readout chips above a chart. |
| `PanelChart.qml` | one/two stacked line or bar panels for dual-panel payloads. |
| `ReadoutChart.qml` | readout strip + line/bar chart or PanelChart (room decay/clarity, statistics, harmonic/insulation bars). |
| `AbSpectrumChart.qml` | A/B overlay + threshold top panel, delta trace bottom panel (distinct colours/dashes from payload roles). |
| `StipaChart.qml` | 101-stage real progress bar + result readouts + caption. |
| `EventTimeline.qml` | real event timeline, kind colours, download-state markers, click signal. |
| `NoiseRatingChart.qml` | measured spectrum + payload reference families + estimate readouts + reference note. |
| `CapabilityPanel.qml` | capability/limitation text panel. |
| `FeaturePayload.js` | pure payload normalisation / routing (QJSEngine-testable, no acoustic computation). |

The chart layer hardcodes no Chinese/English UI text: titles, units, validity,
empty states, captions, tooltips and download labels are payload/page supplied.
Pure black plot background (`Theme.plotBg = #000000`), 1-1.5 px traces, layered
major/minor grid darker than data, 12-14 px labels, no glow/gradient decoration/
auto-rotate, no animation on measurement data.

### Python display-raster provider (`ui/viewmodels/plot_images.py`)

Additive API (no acoustic computation): `heatmap_image(matrix, ...,
locked_range=..., invalid_color=BLACK)` keeps missing cells pure black and a
locked/facade range; `stft_image(frames, frequency_axis, time_axis,
color_scale)` renders retained frames only in axis (log) geometry - missing
frames/bins stay black, no interpolation; `das_image(points, ...,
projection="rect"|"polar")` renders supplied directional-power points;
`peak_envelope(values, budget)` is the bounded display extraction that
preserves transient peaks and gaps; `FeatureRasterCache` is a bounded LRU cache
with per-key revisions (`image://plots/<key>/<revision>`);
`PlotImageProvider` keeps the frozen facade API
(`set_image`/`revision`/`requestImage`).

### Presentation tests + visual evidence

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python.exe -m pytest tests/frontend/test_chart_presentation.py -q
.venv\Scripts\python.exe ui/qml/components/charts/_selftest/qml_load_check.py
```

`tests/frontend/test_chart_presentation.py` covers: every feature-spec chart kind
has a payload fixture and routes with zero QML warnings; empty/invalid/unavailable
states never draw fake data; toolbar 32x32 targets/20 px icons and view-only
operations (fit/log/legend/2D3D) persist through `App.setFeatureViewOption`
without calling PL slots; `grabToImage` save calls `App.notifyFeatureSaved`;
log axis excludes <=0; band ramp/invalid categories; dual panels; A/B/delta
distinctness; STIPA 101 stage progress; event timeline click; waveform
sample-rate/gaps; scalars/capability; plot_images peak-envelope/raster/cache
integrity; no hardcoded CJK UI text in the chart layer.

Offscreen PNG evidence per chart kind is written to
`tests/frontend/fixtures/charts/` (`<kind>.png`, `stft-3d.png`,
`das-map-rect.png`, `empty-spectrum.png`, `stft-invalid-3d.png`,
`spectrum-toolbar-save.png`) by the extended `qml_load_check.py` (phase 3);
the script also verifies pure-black background ratio, toolbar wiring and zero QML
warnings for the feature charts.

Known limitations: NC/NR reference families and 3-D waterfall frames are only
drawn when the payload supplies them (the PC never fabricates reference data or
time axes); optional axis/range metadata falls back to component defaults; the
fixtures are `test-fixture` and are never presented as hardware measurements.


Current frontend layout/render/export handoff: `docs/frontend/HANDOFF_UI_STUDIO_REDESIGN_20261026.md`.
