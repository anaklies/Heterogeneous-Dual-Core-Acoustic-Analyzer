// FeaturePayload.js - pure display-side normalisation of App.featureWorkspace.chart
// payloads for FeatureChart.qml. No acoustic calculation happens in this file:
// it only validates payload shapes, maps display values and chooses a chart
// component. Every function is pure so it can be unit-tested with QJSEngine.
.pragma library
.import "ChartUtil.js" as U

// Chart kinds still emitted by the 45-feature device view spec. The six spatial
// features and their former capability/beam-spectrum/das-map charts were removed;
// unknown kinds route to the empty state. "scalar-trend" is a runtime-history kind
// without a static spec entry.
var KIND_TOKENS = {
    "spectrum": "line",
    "zoom-spectrum": "line",
    "spectral-decay": "readout-line",
    "lag-series": "readout-line",
    "bands": "bars-readout",
    "insulation-bars": "bars-readout",
    "harmonic-bars": "bars-readout",
    "stft": "stft",
    "pair-spectra": "panel",
    "coherence-phase": "panel",
    "weighting": "panel",
    "room-decay": "readout-line",
    "room-clarity": "readout-line",
    "statistics": "readout-line",
    "ab-spectrum": "ab",
    "stipa": "stipa",
    "waveform": "waveform",
    "level-bars": "level",
    "scalars": "scalars",
    "scalar-trend": "readout-line",
    "events": "events",
    "noise-rating": "noise"
}

function isNum(v) {
    return typeof v === "number" && isFinite(v);
}

function asList(v) {
    if (v === null || v === undefined) return [];
    if (typeof v === "string") return [];
    if (v.length === undefined) return [];
    var out = [];
    for (var i = 0; i < v.length; i++) out.push(v[i]);
    return out;
}

function hasItems(v) {
    return asList(v).length > 0;
}

function routeToken(kind) {
    var k = String(kind === undefined || kind === null ? "" : kind);
    if (k === "bars-readout") return "bars-readout";
    return KIND_TOKENS[k] !== undefined ? KIND_TOKENS[k] : "empty";
}

function normalizePoints(points) {
    var src = asList(points);
    var out = [];
    for (var i = 0; i < src.length && i < 262144; i++) {
        var p = src[i];
        if (!p || p.length === undefined || p.length < 2) continue;
        var x = Number(p[0]);
        if (!isFinite(x)) continue;
        var y = p[1];
        if (y === null || y === undefined) {
            out.push([x, null]);
            continue;
        }
        var yn = Number(y);
        out.push([x, isFinite(yn) ? yn : null]);
    }
    return out;
}

// The device/runtime may still carry the pre-refactor channel hex strings; map
// them to the frozen Midnight-Scientific CH1..CH6 palette so one channel has
// exactly one colour in PCM / FFT / PSD / correlation / trend charts.
var LEGACY_CHANNEL_COLORS = {
    "#38D9D1":"#B9E7ED", "#6DA5FF":"#E2E649", "#B29AFF":"#C74BDA",
    "#F3B86A":"#72D6C9", "#F18AB9":"#93D272", "#96D885":"#B2C4F0"
};
function normalizeSeries(list) {
    var src = asList(list);
    var out = [];
    for (var i = 0; i < src.length && i < 64; i++) {
        var s = src[i];
        if (!s || typeof s !== "object") continue;
        var points = normalizePoints(s.points);
        if (!points.length) continue;
        var rawColor = s.color === undefined || s.color === null ? "" : String(s.color);
        if (LEGACY_CHANNEL_COLORS[rawColor.toUpperCase()]) {
            rawColor = LEGACY_CHANNEL_COLORS[rawColor.toUpperCase()];
        }
        out.push({
            name: s.name === undefined ? "" : String(s.name),
            color: rawColor,
            points: points,
            width: s.width,
            dashed: s.dashed,
            fill: s.fill,
            fillColor: s.fillColor,
            visible: s.visible === undefined ? true : s.visible,
            unit: s.unit,
            role: s.role,
            panel: s.panel,
            kind: s.kind
        });
    }
    return out;
}

function normalizeMarkers(list) {
    var src = asList(list);
    var out = [];
    for (var i = 0; i < src.length && i < 256; i++) {
        var m = src[i];
        if (!m || typeof m !== "object") continue;
        if (!isNum(m.x) || !isNum(m.y)) continue;
        out.push({
            x: Number(m.x),
            y: Number(m.y),
            label: m.label === undefined ? "" : String(m.label),
            kind: m.kind,
            color: m.color,
            size: m.size
        });
    }
    return out;
}

function normalizeReferenceLines(list) {
    var src = asList(list);
    var out = [];
    for (var i = 0; i < src.length && i < 32; i++) {
        var r = src[i];
        if (!r || typeof r !== "object" || !isNum(r.y)) continue;
        out.push({ y: Number(r.y), label: r.label === undefined ? "" : String(r.label),
                   color: r.color, dashed: r.dashed, kind: r.kind });
    }
    return out;
}

function normalizeReferenceBands(list) {
    var src = asList(list);
    var out = [];
    for (var i = 0; i < src.length && i < 32; i++) {
        var b = src[i];
        if (!b || typeof b !== "object" || !isNum(b.y0) || !isNum(b.y1)) continue;
        out.push({ y0: Number(b.y0), y1: Number(b.y1),
                   label: b.label === undefined ? "" : String(b.label),
                   color: b.color, opacity: b.opacity });
    }
    return out;
}

function normalizeCategories(list) {
    var src = asList(list);
    var out = [];
    for (var i = 0; i < src.length && i < 256; i++) {
        var c = src[i];
        if (!c || typeof c !== "object") continue;
        var value = c.value;
        if (value !== null && value !== undefined && !isNum(value)) value = Number(value);
        var cat = {
            label: c.label === undefined ? "" : String(c.label),
            value: isNum(value) ? Number(value) : null,
            unit: c.unit,
            valid: c.valid === undefined ? true : c.valid,
            color: c.color,
            peak: isNum(c.peak) ? Number(c.peak) : null,
            clip: c.clip === true,
            centerFrequency: isNum(c.centerFrequency) ? Number(c.centerFrequency) : undefined,
            tone: c.tone
        };
        out.push(cat);
    }
    return out;
}

function normalizeScalarRows(list) {
    var src = asList(list);
    var out = [];
    for (var i = 0; i < src.length && i < 128; i++) {
        var r = src[i];
        if (!r || typeof r !== "object") continue;
        out.push({
            label: r.label === undefined ? "" : String(r.label),
            displayLabel: r.displayLabel === undefined ? "" : String(r.displayLabel),
            value: r.value,
            unit: r.unit,
            valid: r.valid === undefined ? true : r.valid,
            tone: r.tone
        });
    }
    return out;
}

function normalizePanels(list) {
    var src = asList(list);
    var out = [];
    for (var i = 0; i < src.length && i < 3; i++) {
        var p = src[i];
        if (!p || typeof p !== "object") continue;
        out.push({
            render: p.render === "bars" ? "bars" : "line",
            title: p.title === undefined ? "" : String(p.title),
            subtitle: p.subtitle === undefined ? "" : String(p.subtitle),
            series: normalizeSeries(p.series),
            categories: normalizeCategories(p.categories),
            xAxis: p.xAxis,
            yAxis: p.yAxis,
            markers: normalizeMarkers(p.markers),
            referenceLines: normalizeReferenceLines(p.referenceLines),
            referenceBands: normalizeReferenceBands(p.referenceBands),
            limitLine: p.limitLine,
            referenceValues: asList(p.referenceValues),
            showLegend: p.showLegend,
            emptyText: p.emptyText,
            emptyReason: p.emptyReason,
            bandRamp: asList(p.bandRamp),
            colorScale: p.colorScale,
            valueFormat: p.valueFormat,
            xMode: p.xMode,
            xLabel: p.xLabel,
            xUnit: p.xUnit
        });
    }
    return out;
}

// Group series by their optional panel index; returns [] when the payload has no
// explicit panel grouping (callers then fall back to a single chart).
function seriesPanels(series) {
    var list = series || [];
    var groups = {};
    var keys = [];
    for (var i = 0; i < list.length; i++) {
        var s = list[i];
        if (!s) continue;
        var idx = isNum(s.panel) ? Math.round(s.panel) : 0;
        if (groups[idx] === undefined) { groups[idx] = []; keys.push(idx); }
        groups[idx].push(s);
    }
    if (keys.length < 2) return [];
    keys.sort(function (a, b) { return a - b; });
    var out = [];
    for (var k = 0; k < keys.length; k++) {
        out.push({ render: "line", title: "", subtitle: "", series: groups[keys[k]],
                   categories: [], markers: [], referenceLines: [], referenceBands: [],
                   referenceValues: [], bandRamp: [], showLegend: true });
    }
    return out;
}

function panelGroups(series) {
    return seriesPanels(series);
}

// Dual/coherence panel derivation when the facade does not supply chart.panels:
// coherence stays 0..1 and phases (rad/degree series) get their own panel.
function coherencePanels(series, yAxis) {
    var explicit = seriesPanels(series);
    if (explicit.length) return explicit;
    var phase = [];
    var coherence = [];
    var list = series || [];
    for (var i = 0; i < list.length; i++) {
        var s = list[i];
        if (!s) continue;
        var unit = String(s.unit === undefined ? "" : s.unit).toLowerCase();
        var isPhase = unit.indexOf("rad") >= 0 || unit.indexOf("deg") >= 0 || unit.indexOf("°") >= 0;
        if (isPhase) phase.push(s); else coherence.push(s);
    }
    if (!phase.length || !coherence.length) return [];
    var cohAxis = yAxis;
    if (!cohAxis || !isNum(cohAxis.min) || !isNum(cohAxis.max)) {
        cohAxis = { min: 0, max: 1, scale: "linear", label: "", unit: "" };
    }
    return [
        { render: "line", title: "", subtitle: "", series: coherence, categories: [],
          markers: [], referenceLines: [], referenceBands: [], referenceValues: [],
          bandRamp: [], showLegend: true, yAxis: cohAxis },
        { render: "line", title: "", subtitle: "", series: phase, categories: [],
          markers: [], referenceLines: [], referenceBands: [], referenceValues: [],
          bandRamp: [], showLegend: true }
    ];
}

// Weighting: two independent runs must stay in two visually separate panels.
function weightingPanels(series, panels) {
    var p = normalizePanels(panels);
    if (p.length) return p;
    var groups = seriesPanels(series);
    if (groups.length) return groups;
    return [];
}

// Statistics: distribution panel plus an optional trend panel. The trend panel is
// selected by series.role === "trend" (payload-driven, no derivation).
function statisticsPanels(series) {
    var list = series || [];
    var trend = [];
    var distribution = [];
    for (var i = 0; i < list.length; i++) {
        var s = list[i];
        if (!s) continue;
        var role = String(s.role === undefined ? "" : s.role).toLowerCase();
        if (role === "trend" || s.panel === 1) trend.push(s); else distribution.push(s);
    }
    if (!trend.length) return [];
    return [
        { render: "line", title: "", subtitle: "", series: distribution, categories: [],
          markers: [], referenceLines: [], referenceBands: [], referenceValues: [],
          bandRamp: [], showLegend: distribution.length > 1 },
        { render: "line", title: "", subtitle: "", series: trend, categories: [],
          markers: [], referenceLines: [], referenceBands: [], referenceValues: [],
          bandRamp: [], showLegend: false }
    ];
}

// A/B + delta split; the delta trace never shares the top panel's scale.
function abSplit(series) {
    var top = [];
    var delta = [];
    var list = series || [];
    var topCount = 0;
    for (var i = 0; i < list.length; i++) {
        var s = list[i];
        if (!s) continue;
        var role = String(s.role === undefined ? "" : s.role).toLowerCase();
        if (role === "delta" || role === "difference" || role === "diff" || s.panel === 1) {
            delta.push(s);
        } else {
            top.push(s);
            topCount++;
        }
    }
    return { top: top, delta: delta };
}

function waveformChannels(chart, series) {
    var ch = asList(chart.channels);
    if (ch.length) {
        var out = [];
        for (var i = 0; i < ch.length && i < 16; i++) {
            var c = ch[i];
            if (!c || typeof c !== "object") continue;
            out.push({
                name: c.name === undefined ? "" : String(c.name),
                color: c.color,
                visible: c.visible === undefined ? true : c.visible,
                values: asList(c.values)
            });
        }
        return out;
    }
    var src = series || [];
    var fallback = [];
    for (var j = 0; j < src.length && j < 16; j++) {
        var s = src[j];
        if (!s) continue;
        var values = [];
        for (var k = 0; k < s.points.length; k++) {
            var p = s.points[k];
            values.push(p && p.length >= 2 ? p[1] : null);
        }
        fallback.push({ name: s.name, color: s.color,
                        visible: s.visible === undefined ? true : s.visible, values: values });
    }
    return fallback;
}

// Bounded display extraction: > budget samples per channel are reduced with the
// peak envelope so transients survive; gaps are remapped to the envelope domain.
function waveformDisplay(chart, series, budget) {
    var limit = isNum(budget) && budget > 64 ? Math.floor(budget) : 4096;
    var channels = waveformChannels(chart, series);
    var maxLen = 0;
    for (var i = 0; i < channels.length; i++) {
        if (channels[i].values.length > maxLen) maxLen = channels[i].values.length;
    }
    var gaps = asList(chart.gaps);
    var extracted = false;
    if (maxLen > limit) {
        var firstLen = 0;
        for (var c = 0; c < channels.length; c++) {
            channels[c].values = U.peakEnvelope(channels[c].values, limit);
            if (c === 0) firstLen = channels[c].values.length;
        }
        gaps = U.scaleGapsForEnvelope(gaps, maxLen, firstLen);
        extracted = true;
    }
    var rate = isNum(chart.sampleRate) ? Number(chart.sampleRate)
             : (isNum(chart.sampleRateHz) ? Number(chart.sampleRateHz) : 0);
    return {
        channels: channels,
        gaps: gaps,
        extracted: extracted,
        originalLength: maxLen,
        sampleRate: rate,
        startSampleIndex: chart.startSampleIndex === undefined ? "" : String(chart.startSampleIndex)
    };
}

function levelMeters(chart, categories) {
    var meters = asList(chart.meters);
    if (meters.length) {
        var out = [];
        for (var i = 0; i < meters.length && i < 16; i++) {
            var m = meters[i];
            if (!m || typeof m !== "object") continue;
            out.push({
                label: m.label === undefined ? "" : String(m.label),
                color: m.color,
                value: isNum(m.value) ? Number(m.value) : null,
                peak: isNum(m.peak) ? Number(m.peak) : null,
                valid: m.valid === undefined ? true : m.valid,
                clip: m.clip === true
            });
        }
        return out;
    }
    var cats = categories || [];
    var fallback = [];
    for (var j = 0; j < cats.length; j++) {
        var c = cats[j];
        fallback.push({
            label: c.label, color: c.color,
            value: isNum(c.value) ? c.value : null,
            peak: isNum(c.peak) ? c.peak : null,
            valid: c.valid === undefined ? true : c.valid,
            clip: c.clip === true
        });
    }
    return fallback;
}

function bandRamp(chart, fallbackRamp) {
    var explicit = asList(chart.bandRamp);
    if (explicit.length >= 2) return explicit;
    return fallbackRamp || [];
}

function bandColorScale(chart, categories, yAxis, ramp) {
    var cs = chart.colorScale;
    if (cs && isNum(cs.min) && isNum(cs.max) && cs.max > cs.min) {
        var stops = asList(cs.stops);
        return { min: Number(cs.min), max: Number(cs.max),
                 palette: cs.palette, label: cs.label === undefined ? "" : String(cs.label),
                 unit: cs.unit === undefined ? "" : String(cs.unit),
                 stops: stops.length >= 2 ? stops : ramp, locked: true };
    }
    var lo = Infinity;
    var hi = -Infinity;
    var cats = categories || [];
    for (var i = 0; i < cats.length; i++) {
        var c = cats[i];
        if (!c || c.valid === false || !isNum(c.value)) continue;
        if (c.value < lo) lo = c.value;
        if (c.value > hi) hi = c.value;
    }
    var axis = yAxis || {};
    if (isNum(axis.min) && isNum(axis.max) && axis.max > axis.min) {
        lo = axis.min;
        hi = axis.max;
    }
    if (lo === Infinity || hi === -Infinity) return null;
    if (lo === hi) { lo -= 1; hi += 1; }
    return { min: lo, max: hi,
             label: axis.label === undefined ? "" : String(axis.label),
             unit: axis.unit === undefined ? (chart.units === undefined ? "" : String(chart.units)) : String(axis.unit),
             stops: ramp, locked: true };
}

// Normalize the two existing display contracts without changing producer data.
function stftDisplay(chart) {
    var r=chart.raster || {}, m=r.matrix || [];
    var cs=chart.colorScale;
    if (!cs || !isNum(cs.min) || !isNum(cs.max)) cs={min:isNum(r.min)?r.min:0,max:isNum(r.max)?r.max:1,palette:r.palette||"inferno",label:"PSD",unit:(chart.yAxis||{}).unit||chart.units||""};
    if (r.yUnit !== "frame" || !m.length || !m[0].length)
        return {raster:r,xAxis:chart.xAxis,yAxis:chart.yAxis,colorScale:cs};
    // Decoder contract: rows are retained frames in reverse order, columns are
    // uniform FFT bins. Display frequency vertically and snapshots horizontally.
    var n=Math.min(m.length,16), bins=m[0].length, out=[];
    for(var f=0;f<bins;f++) {
        var row=[];for(var t=0;t<n;t++) row.push((m[n-1-t]||[])[f]);out.push(row);
    }
    var fx=chart.xAxis || {}, lo=isNum(fx.min)?fx.min:0,hi=isNum(fx.max)?fx.max:1;
    var sourceBins=isNum(r.sourceBins)?r.sourceBins:bins;
    var positive=lo>0?lo:(hi-lo)/Math.max(1,sourceBins-1);
    var frequencyAxis=chart.frequencyAxis || {min:positive,max:hi,scale:hi/positive>20?"log":"linear",label:fx.label||"Frequency",unit:fx.unit||"Hz"};
    return {raster:{matrix:out,min:r.min,max:r.max,palette:r.palette,
                    xDomain:{min:0,max:Math.max(1,n-1)},yDomain:{min:lo,max:hi},rowTimes:r.rowTimes},
            xAxis:{min:0,max:Math.max(1,n-1),scale:"linear",label:"frames",unit:""},
            yAxis:frequencyAxis,colorScale:cs};
}
function frames(chart) {
    var src=asList(chart.frames), r=chart.raster||{}, m=r.matrix||[];
    if(!src.length)return {frames:[],supported:false,hadPayload:false};
    if(src.length>48)return {frames:[],supported:false,hadPayload:true};
    var out=[], base=isNum(src[0].time)?src[0].time:NaN;
    for(var i=0;i<src.length;i++) {
        var fr=src[i];if(!fr || !isNum(fr.time))return {frames:[],supported:false,hadPayload:true};
        var pts=normalizePoints(fr.points);
        if(r.yUnit === "frame" && m.length===src.length && m[0] && m[0].length>1 && chart.xAxis) {
            var raw=m[m.length-1-i], count=raw.length, fx=chart.xAxis;
            pts=[];for(var k=0;k<count;k++)pts.push([fx.min+(fx.max-fx.min)*k/(count-1),isNum(raw[k])?raw[k]:null]);
        }
        var relative=isNum(fr.displayTimeSeconds)?fr.displayTimeSeconds:fr.time-base;
        out.push({time:chart.timeAxis?fr.time:relative,points:pts});
    }
    return {frames:out,supported:out.length>1,hadPayload:true};
}

function frequencyAxisFor(chart, framesList, fallbackYAxis) {
    if (chart.frequencyAxis) return chart.frequencyAxis;
    var rows = framesList || [];
    if (!rows.length) return null;
    var first = rows[0].points;
    var last = rows[rows.length - 1].points;
    if (!first.length || !last.length) return null;
    var lo = first[0][0];
    var hi = last[last.length - 1][0];
    if (!isNum(lo) || !isNum(hi) || !(hi > lo)) return null;
    var y = chart.xAxis && chart.xAxis.unit === "Hz" ? chart.xAxis : fallbackYAxis || {};
    if (!(lo > 0)) { for(var i=0;i<first.length;i++)if(first[i][0]>0){lo=first[i][0];break;} }
    return {
        min: lo, max: hi,
        scale: (lo > 0 && hi / lo > 20) ? "log" : "linear",
        label: y.label === undefined ? "" : String(y.label),
        unit: y.unit === undefined ? "" : String(y.unit)
    };
}

function timeAxisFor(chart, framesList, fallbackXAxis) {
    if (chart.timeAxis) return chart.timeAxis;
    var rows = framesList || [];
    if (!rows.length) return null;
    var t0 = rows[0].time;
    var t1 = rows[rows.length - 1].time;
    if (!isNum(t0) || !isNum(t1) || !(t1 > t0)) return null;
    return {
        min: t0, max: t1, scale: "linear",
        label: "Relative time",
        unit: "s"
    };
}

function stipaIndex(chart, scalarRows) {
    if(chart.indexValid === false)return {value:NaN,valid:false,label:chart.indexLabel||"",unit:""};
    if (isNum(chart.indexValue)) {
        return {
            value: Number(chart.indexValue),
            valid: chart.indexValid === undefined ? true : chart.indexValid !== false,
            label: chart.indexLabel === undefined ? "" : String(chart.indexLabel),
            unit: chart.indexUnit === undefined ? "" : String(chart.indexUnit)
        };
    }
    // The index row may arrive as the first numeric scalar row when the facade
    // does not extract it; its label/unit still come from the payload.
    var rows = scalarRows || [];
    for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        if (r && r.unit !== "bool" && r.label !== "valid" && r.label !== "certified_zero" && isNum(r.value) && r.value >= 0 && r.value <= 1) {
            return { value: Number(r.value), valid: r.valid !== false,
                     label: r.label === undefined ? "" : String(r.label),
                     unit: r.unit === undefined ? "" : String(r.unit) };
        }
    }
    return { value: NaN, valid: false, label: "", unit: "" };
}

function eventsFor(chart) {
    var src = asList(chart.events);
    var out = [];
    for (var i = 0; i < src.length && i < 512; i++) {
        var e = src[i];
        if (!e || typeof e !== "object") continue;
        out.push({
            position01: isNum(e.position01) ? Number(e.position01) : (isNum(e.position) ? Number(e.position) : null),
            label: e.label,
            kind: e.kind,
            downloadState: e.downloadState,
            detail: e.detail
        });
    }
    return out;
}

// Single source of truth for the per-kind chart-kind coverage (tests assert the
// 24 chart kinds from feature_view_spec.json all route somewhere).
function kindList() {
    var out = [];
    for (var k in KIND_TOKENS) {
        if (KIND_TOKENS.hasOwnProperty(k)) out.push(k);
    }
    out.sort();
    return out;
}
