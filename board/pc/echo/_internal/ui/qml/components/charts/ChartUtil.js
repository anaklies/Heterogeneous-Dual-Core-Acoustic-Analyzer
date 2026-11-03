// ChartUtil.js - shared pure display helpers for the SixMic3D Qt Quick charts.
// No acoustic computation happens here: only ticks, formatting, coordinate
// mapping and colour-map lookup used by the Canvas painters.
//
// Design rules (frozen contract CHART_DATA_CONTRACT.md):
//  * 1/2/5 x 10^n tick generation everywhere ("nice" ticks).
//  * log axes must never evaluate <= 0 values (callers clip with isLogValid()).
//  * colours are handed in via a style object built from the QML Theme context
//    property; palettes below are data colour maps (viridis/cividis/diverging),
//    not theme colours.
.pragma library

// ---------------------------------------------------------------- numbers
function isNum(v) {
    return typeof v === "number" && isFinite(v);
}

function clamp(v, lo, hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

function isLogValid(v) {
    return isNum(v) && v > 0;
}

function log10(v) {
    return Math.log(v) / Math.LN10;
}

function pow10(e) {
    return Math.pow(10, e);
}

// ---------------------------------------------------------------- tick generation (1/2/5)
function niceStep(span, targetCount) {
    if (!isNum(span) || span <= 0) return 1;
    var count = isNum(targetCount) && targetCount >= 2 ? targetCount : 6;
    var raw = span / count;
    var mag = pow10(Math.floor(log10(raw)));
    var norm = raw / mag;
    var mult = norm <= 1 ? 1 : (norm <= 2 ? 2 : (norm <= 5 ? 5 : 10));
    return mult * mag;
}

function decimalsForStep(step) {
    if (!isNum(step) || step <= 0) return 0;
    if (step >= 1) return 0;
    var d = Math.ceil(-log10(step));
    return clamp(d, 0, 6);
}

// Linear 1/2/5 ticks covering [min,max]; the returned domain is snapped to the
// tick grid so the axis reads like an instrument scale.
function linearTicks(min, max, targetCount) {
    if (!isNum(min) || !isNum(max) || max <= min) {
        return { min: 0, max: 1, step: 1, ticks: [0, 1] };
    }
    var step = niceStep(max - min, targetCount);
    var lo = Math.floor(min / step) * step;
    var hi = Math.ceil(max / step) * step;
    var ticks = [];
    var guard = 0;
    for (var v = lo; v <= hi + step * 0.5 && guard < 512; v += step, guard++) {
        var t = Math.abs(v) < step * 1e-9 ? 0 : v;
        ticks.push(t);
    }
    return { min: lo, max: hi, step: step, ticks: ticks };
}

// Log ticks at 1/2/5 x 10^n inside [minPos,maxPos] (both must be > 0).
function logTicks(minPos, maxPos, targetCount) {
    if (!isLogValid(minPos) || !isLogValid(maxPos) || maxPos <= minPos) {
        return { min: 1, max: 10, step: 1, ticks: [1, 2, 5, 10], log: true };
    }
    var count = isNum(targetCount) && targetCount >= 2 ? targetCount : 6;
    var decades = log10(maxPos / minPos);
    var mults = decades > 8 ? [1] : (decades > 4 ? [1, 2] : [1, 2, 5]);
    var ticks = [];
    var e0 = Math.floor(log10(minPos));
    var e1 = Math.ceil(log10(maxPos));
    for (var e = e0; e <= e1; e++) {
        for (var m = 0; m < mults.length; m++) {
            var v = mults[m] * pow10(e);
            if (v >= minPos * (1 - 1e-9) && v <= maxPos * (1 + 1e-9)) ticks.push(v);
        }
    }
    if (ticks.length < 2) ticks = [minPos, maxPos];
    if (ticks.length > count + 6) {
        var keep = [];
        for (var i = 0; i < ticks.length; i++) {
            var exponent = log10(ticks[i]);
            if (i === 0 || i === ticks.length - 1 || Math.abs(exponent - Math.round(exponent)) < 1e-9)
                keep.push(ticks[i]);
        }
        ticks = keep.length >= 2 ? keep : [ticks[0], ticks[ticks.length - 1]];
    }
    return { min: minPos, max: maxPos, step: 0, ticks: ticks, log: true };
}

// Build the effective axis for a series of values. Handles autoscale, the
// log-axis <=0 guard (clip, do not fake) and returns the transform info.
// values: array of numbers (may contain NaN); config: {min,max,scale,...}
function prepareAxis(config, values, fallbackMin, fallbackMax) {
    var cfg = config && typeof config === "object" ? config : {};
    var scale = cfg.scale === "log" ? "log" : "linear";
    var min = isNum(cfg.min) ? cfg.min : NaN;
    var max = isNum(cfg.max) ? cfg.max : NaN;
    var auto = !isNum(min) || !isNum(max) || !(max > min);
    var clipped = 0;
    if (auto) {
        var lo = Infinity;
        var hi = -Infinity;
        var stride = 1;
        if (values && values.length > 4096) stride = Math.ceil(values.length / 4096);
        if (values && values.length) {
            for (var i = 0; i < values.length; i += stride) {
                var v = values[i];
                if (scale === "log" && !isLogValid(v)) { clipped++; continue; }
                if (!isNum(v)) continue;
                if (v < lo) lo = v;
                if (v > hi) hi = v;
            }
        }
        if (lo === Infinity || hi === -Infinity) {
            lo = isNum(fallbackMin) ? fallbackMin : 0;
            hi = isNum(fallbackMax) ? fallbackMax : 1;
        }
        if (lo === hi) { lo -= 1; hi += 1; }
        min = lo;
        max = hi;
        auto = true;
    }
    if (scale === "log") {
        if (!isLogValid(min)) min = isLogValid(max) ? max * 1e-3 : 1e-3;
        if (!isLogValid(max)) max = min * 1e3;
        if (max <= min) max = min * 10;
    }
    return {
        min: min,
        max: max,
        scale: scale,
        auto: auto,
        clipped: clipped,
        label: typeof cfg.label === "string" ? cfg.label : "",
        unit: typeof cfg.unit === "string" ? cfg.unit : ""
    };
}

// Snap an auto linear domain to the 1/2/5 grid.
function snapLinearDomain(axis, targetCount) {
    if (!axis || axis.scale !== "linear" || !axis.auto) return axis;
    var r = linearTicks(axis.min, axis.max, targetCount || 5);
    axis.min = r.min;
    axis.max = r.max;
    axis.step = r.step;
    return axis;
}

// ---------------------------------------------------------------- formatting
var SI_PREFIX = [[12, "T"], [9, "G"], [6, "M"], [3, "k"], [0, ""], [-3, "m"], [-6, "u"], [-9, "n"], [-12, "p"]];

function trimZeros(s) {
    return s.indexOf(".") >= 0 ? s.replace(/\.?0+$/, "") : s;
}

function fmtSI(v) {
    if (!isNum(v)) return "-";
    if (v === 0) return "0";
    var sign = v < 0 ? "-" : "";
    var av = Math.abs(v);
    var e = Math.floor(log10(av) / 3) * 3;
    e = clamp(e, -12, 12);
    var mant = av / pow10(e);
    var p = "";
    for (var i = 0; i < SI_PREFIX.length; i++) {
        if (SI_PREFIX[i][0] === e) { p = SI_PREFIX[i][1]; break; }
    }
    var digits = mant >= 100 ? 0 : (mant >= 10 ? 1 : 2);
    return sign + trimZeros(mant.toFixed(digits)) + p;
}

// Compact engineering label for a tick. step drives the decimal count so the
// whole axis shares one precision (tabular-number friendly).
function fmtTick(v, step) {
    if (!isNum(v)) return "-";
    if (v === 0) return "0";
    var av = Math.abs(v);
    if (av >= 1e5 || av < 1e-3) return fmtSI(v);
    if (isNum(step) && step > 0 && step < 1) return trimZeros(v.toFixed(decimalsForStep(step)));
    var d = av >= 100 ? 0 : (av >= 10 ? 1 : 2);
    if (isNum(step) && step >= 1) d = 0;
    return trimZeros(v.toFixed(d));
}

// printf-lite: supports "%.Nf" / "%.Ne" / "%d" / "%g"; anything else falls back
// to a compact engineering string (the page owns the format string).
function fmtValue(v, fmt) {
    if (!isNum(v)) return "-";
    if (typeof fmt === "string" && fmt.length > 1) {
        var m = /^%\.?(\d*)([fFeEgGd])$/.exec(fmt);
        if (m) {
            var digits = m[1] === "" ? 0 : parseInt(m[1], 10);
            digits = clamp(digits, 0, 8);
            var kind = m[2].toLowerCase();
            if (kind === "f") return v.toFixed(digits);
            if (kind === "e") return v.toExponential(digits);
            if (kind === "d") return String(Math.round(v));
            return String(v);
        }
    }
    return fmtSI(v);
}

// Seconds label for waveform/timeline axes (unit is appended by the caller).
function fmtSeconds(t) {
    if (!isNum(t)) return "-";
    var av = Math.abs(t);
    if (av >= 100) return trimZeros(t.toFixed(1));
    if (av >= 10) return trimZeros(t.toFixed(2));
    if (av >= 1) return trimZeros(t.toFixed(3));
    if (av >= 1e-3) return trimZeros((t * 1e3).toFixed(2)) + "m";
    if (av >= 1e-6) return trimZeros((t * 1e6).toFixed(1)) + "u";
    return trimZeros((t * 1e9).toFixed(1)) + "n";
}

function fmtDuration(sec) {
    if (!isNum(sec) || sec < 0) return "-";
    if (sec >= 3600) {
        var h = Math.floor(sec / 3600);
        var m = Math.floor((sec - h * 3600) / 60);
        return h + ":" + (m < 10 ? "0" : "") + m + ":" + (Math.floor(sec) % 60 < 10 ? "0" : "") + (Math.floor(sec) % 60);
    }
    if (sec >= 60) {
        var total = Math.round(sec);
        if (Math.abs(sec - total) < 1e-6) {
            var wm = Math.floor(total / 60);
            var ws = total - wm * 60;
            return wm + ":" + (ws < 10 ? "0" : "") + ws;
        }
        var mm = Math.floor(sec / 60);
        var ss = sec - mm * 60;
        return mm + ":" + (ss < 10 ? "0" : "") + ss.toFixed(1);
    }
    return fmtSeconds(sec);
}

// ---------------------------------------------------------------- colours
function parseColor(c) {
    var r = 0, g = 0, b = 0, a = 1;
    if (typeof c !== "string" || c.length === 0) return { r: 128, g: 128, b: 128, a: 1 };
    var s = c.trim();
    if (s.charAt(0) === "#") {
        s = s.substring(1);
        if (s.length === 3) {
            r = parseInt(s.charAt(0) + s.charAt(0), 16);
            g = parseInt(s.charAt(1) + s.charAt(1), 16);
            b = parseInt(s.charAt(2) + s.charAt(2), 16);
        } else if (s.length === 6) {
            r = parseInt(s.substring(0, 2), 16);
            g = parseInt(s.substring(2, 4), 16);
            b = parseInt(s.substring(4, 6), 16);
        } else if (s.length === 8) {
            a = parseInt(s.substring(0, 2), 16) / 255.0;
            r = parseInt(s.substring(2, 4), 16);
            g = parseInt(s.substring(4, 6), 16);
            b = parseInt(s.substring(6, 8), 16);
        }
    } else {
        var m = /rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)/.exec(s);
        if (m) {
            r = parseFloat(m[1]); g = parseFloat(m[2]); b = parseFloat(m[3]);
            a = m[4] === undefined ? 1 : parseFloat(m[4]);
        }
    }
    return { r: r, g: g, b: b, a: a };
}

function rgba(color, alpha) {
    var c = parseColor(color);
    return "rgba(" + Math.round(c.r) + "," + Math.round(c.g) + "," + Math.round(c.b) + "," + clamp(alpha, 0, 1) + ")";
}

// Data colour maps (sequential: viridis/cividis; diverging: cool-warm, zero
// centred). These are scientific colour maps, not UI theme colours.
// Perceptually uniform scientific colour maps (matplotlib viridis family) with
// enough stops to render smooth spectrogram / DAS heat maps without banding.
// Sequential maps for power/PSD; diverging map for signed A-B differences.
var PALETTES = {
    viridis: [
        [68, 1, 84], [72, 26, 108], [70, 50, 126], [65, 68, 135], [59, 82, 139],
        [53, 95, 141], [47, 108, 142], [42, 120, 142], [36, 132, 141], [31, 145, 139],
        [34, 158, 134], [47, 170, 124], [65, 182, 113], [86, 193, 101], [111, 205, 90],
        [140, 215, 74], [172, 222, 60], [201, 226, 49], [222, 226, 41], [240, 229, 38],
        [253, 231, 37]
    ],
    inferno: [
        [0, 0, 4], [12, 8, 38], [27, 12, 65], [49, 13, 91], [73, 13, 106],
        [96, 20, 116], [120, 28, 109], [142, 38, 99], [162, 47, 88], [181, 58, 76],
        [198, 74, 62], [214, 94, 48], [228, 116, 34], [240, 142, 20], [248, 170, 14],
        [251, 199, 24], [248, 227, 52], [240, 249, 106], [252, 255, 164]
    ],
    plasma: [
        [13, 8, 135], [36, 13, 148], [59, 12, 158], [82, 8, 164], [103, 6, 168],
        [124, 8, 168], [144, 16, 164], [162, 27, 157], [178, 41, 146], [193, 57, 132],
        [205, 73, 116], [216, 90, 100], [226, 108, 84], [235, 127, 69], [242, 147, 54],
        [248, 168, 40], [251, 191, 27], [252, 215, 18], [252, 240, 21], [240, 249, 33]
    ],
    magma: [
        [0, 0, 4], [11, 8, 34], [28, 16, 68], [50, 16, 93], [72, 18, 110],
        [94, 25, 118], [117, 33, 116], [139, 41, 108], [160, 49, 98], [180, 58, 86],
        [199, 69, 74], [216, 83, 62], [231, 101, 50], [242, 123, 42], [249, 147, 42],
        [253, 172, 57], [253, 198, 84], [252, 224, 122], [249, 245, 171], [252, 253, 191]
    ],
    cividis: [
        [0, 32, 76], [0, 39, 95], [0, 48, 112], [25, 60, 113], [45, 70, 111],
        [63, 79, 105], [79, 88, 99], [94, 97, 94], [109, 107, 89], [125, 116, 83],
        [141, 126, 76], [158, 136, 69], [175, 146, 62], [192, 157, 55], [209, 168, 48],
        [226, 179, 42], [244, 191, 37], [253, 205, 44], [253, 222, 82], [254, 239, 130]
    ],
    turbo: [
        [48, 18, 59], [57, 39, 121], [62, 60, 166], [58, 85, 200], [49, 108, 222],
        [36, 130, 231], [23, 150, 227], [14, 169, 213], [15, 185, 190], [30, 199, 160],
        [58, 210, 125], [95, 217, 89], [136, 219, 57], [177, 215, 38], [213, 205, 36],
        [240, 189, 44], [251, 166, 46], [250, 139, 33], [239, 109, 13], [219, 79, 2],
        [190, 49, 0], [158, 21, 0], [122, 4, 2]
    ],
    diverging: [
        [59, 76, 192], [68, 90, 204], [89, 124, 228], [130, 164, 240], [173, 199, 247],
        [221, 221, 221], [246, 183, 157], [230, 116, 90], [196, 34, 44], [170, 8, 32]
    ]
};

// 256-level LUTs generated from the standard scientific-cmap anchor tables
// (matplotlib viridis / inferno / magma / cividis).  Chordal interpolation is
// smooth enough that no banding is visible at 8-bit output, while the anchors
// are exactly the published colour points, so a mapped value always has the
// same colour regardless of the renderer (Canvas / colorbar / 3D mesh).
var LUT_SIZE = 256;
var LUT_CACHE = {};
function paletteStops(name) {
    return PALETTES[name] ? PALETTES[name] : PALETTES.viridis;
}

function buildLut(name) {
    if (LUT_CACHE[name]) return LUT_CACHE[name];
    var anchors = paletteStops(name);
    var lut = new Array(LUT_SIZE);
    var segs = anchors.length - 1;
    for (var i = 0; i < LUT_SIZE; i++) {
        var x = (i / (LUT_SIZE - 1)) * segs;
        var j = Math.floor(x);
        if (j >= segs) j = segs - 1;
        var f = x - j;
        var a = anchors[j], b = anchors[j + 1];
        lut[i] = "rgb(" + Math.round(a[0] + (b[0] - a[0]) * f) + ","
                        + Math.round(a[1] + (b[1] - a[1]) * f) + ","
                        + Math.round(a[2] + (b[2] - a[2]) * f) + ")";
    }
    LUT_CACHE[name] = lut;
    return lut;
}

function paletteStops256(name) {
    return buildLut(name);
}

function paletteColor(name, t) {
    var key = PALETTES[name] ? name : "viridis";
    var lut = buildLut(key);
    var idx = Math.round(clamp(isNum(t) ? t : 0, 0, 1) * (LUT_SIZE - 1));
    if (idx < 0) idx = 0;
    if (idx >= LUT_SIZE) idx = LUT_SIZE - 1;
    return lut[idx];
}

function legacyPaletteColor(name, t) {
    var stops = paletteStops(name);
    var x = clamp(isNum(t) ? t : 0, 0, 1) * (stops.length - 1);
    var i = Math.floor(x);
    if (i >= stops.length - 1) i = stops.length - 2;
    var f = x - i;
    var a = stops[i];
    var b = stops[i + 1];
    return "rgb(" + Math.round(a[0] + (b[0] - a[0]) * f) + "," +
        Math.round(a[1] + (b[1] - a[1]) * f) + "," +
        Math.round(a[2] + (b[2] - a[2]) * f) + ")";
}

// ---------------------------------------------------------------- fonts / text
function fontSpec(px, family, bold) {
    var fam = family && family.length ? "'" + String(family).replace(/'/g, "") + "'" : "sans-serif";
    return String(px) + "px " + fam;
}

function ellipsize(ctx, text, maxW) {
    var s = String(text);
    if (!isNum(maxW) || maxW <= 0) return "";
    if (ctx.measureText(s).width <= maxW) return s;
    var lo = 0;
    var hi = s.length;
    while (lo < hi) {
        var mid = Math.ceil((lo + hi) / 2);
        if (ctx.measureText(s.substring(0, mid) + "\u2026").width <= maxW) lo = mid;
        else hi = mid - 1;
    }
    return lo > 0 ? s.substring(0, lo) + "\u2026" : "";
}

// ---------------------------------------------------------------- drawing helpers
function drawFrame(ctx, st, x, y, w, h) {
    // The containing card owns its rounded border; axes need only an L-frame.
    if(x<1 && y<1)return;
    ctx.strokeStyle = rgba(st.grid,.85);
    ctx.lineWidth = 1;
    ctx.beginPath();ctx.moveTo(x+.5,y+.5);ctx.lineTo(x+.5,y+h-.5);ctx.lineTo(x+w-.5,y+h-.5);ctx.stroke();
}

function drawEmptyState(ctx, st, w, h, text, reason) {
    var main = typeof text === "string" && text.length ? text : "\u2014";
    var cy = h / 2 - (reason ? 8 : 0);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = st.dim;
    ctx.font = fontSpec(st.fs, st.font);
    var label = ellipsize(ctx, main, w - 32);
    ctx.fillText(label, w / 2, cy);
    if (typeof reason === "string" && reason.length) {
        ctx.font = fontSpec(st.fsSmall, st.font);
        ctx.fillStyle = rgba(st.dim, 0.85);
        ctx.fillText(ellipsize(ctx, reason, w - 32), w / 2, cy + 20);
    }
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
}

function drawBusyState(ctx, st, w, h, text) {
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = st.dim;
    ctx.font = fontSpec(st.fs, st.font);
    ctx.fillText(ellipsize(ctx, typeof text === "string" && text.length ? text : "\u2026", w - 32), w / 2, h / 2);
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
}

// Vertical colour bar with 1/2/5 labels, label + unit. cs: colorScale object.
function drawColorBar(ctx, st, cs, x, y, w, h, showLabel) {
    if (!cs || !isNum(cs.min) || !isNum(cs.max) || cs.max<cs.min) return;
    ctx.save();
    var min=cs.min,max=cs.max,constant=max===min,name=cs.palette||"viridis";
    var stops=cs.stops && cs.stops.length>1 ? cs.stops : null;
    function color(t){return stops?rampColor(stops,t):paletteColor(name,t);}
    ctx.font=fontSpec(st.fsSmall,st.font);ctx.fillStyle=st.dim;ctx.textAlign="left";ctx.textBaseline="alphabetic";
    var label=showLabel===false?"":String(cs.label||""),unit=showLabel===false?"":String(cs.unit||"");
    if(label)ctx.fillText(ellipsize(ctx,label,w-4),x,y+11);
    if(unit)ctx.fillText(ellipsize(ctx,unit,w-4),x,y+26);
    var top=y+34,bh=Math.max(8,h-34),bw=11;
    if(constant)ctx.fillStyle=color(.5);
    else {
        var grad=ctx.createLinearGradient(x,top+bh,x,top);
        for(var i=0;i<=20;i++)grad.addColorStop(i/20,color(i/20));
        ctx.fillStyle=grad;
    }
    ctx.fillRect(x,top,bw,bh);ctx.strokeStyle=st.grid;ctx.lineWidth=1;ctx.strokeRect(x+.5,top+.5,bw-1,bh-1);
    var ticks=constant?[min]:linearTicks(min,max,Math.max(2,Math.floor(bh/50))).ticks;
    if(!constant){ticks=ticks.concat([min,max]);ticks.sort(function(a,b){return b-a;});}
    var epsilon=constant?0:(max-min)*1e-9,lastY=-1e99,lastValue=NaN;
    ctx.font=fontSpec(st.fsSmall,st.mono);ctx.fillStyle=st.dim;ctx.textBaseline="middle";
    for(var t=0;t<ticks.length;t++){
        var v=ticks[t];if(v<min-epsilon || v>max+epsilon || (isNum(lastValue)&&Math.abs(v-lastValue)<=epsilon))continue;
        var yy=constant?top+bh/2:top+(1-(v-min)/(max-min))*bh;
        yy=clamp(yy,top+4,top+bh-4);
        if(yy-lastY<14)continue;
        ctx.fillText(ellipsize(ctx,fmtReadout(v,cs.valueFormat || ""),Math.max(22,w-bw-5)),x+bw+5,yy);
        lastY=yy;lastValue=v;
    }
    ctx.restore();
}

// ---------------------------------------------------------------- geometry / gaps
function sortedGaps(gaps) {
    var out = [];
    if (!gaps || !gaps.length) return out;
    var i;
    for (i = 0; i < gaps.length; i++) {
        var g = gaps[i];
        if (!g || !isNum(g.start) || !isNum(g.end)) continue;
        var s = Math.min(g.start, g.end);
        var e = Math.max(g.start, g.end);
        if (e < s) continue;
        out.push({ start: s, end: e });
    }
    out.sort(function (a, b) { return a.start - b.start; });
    var merged = [];
    for (i = 0; i < out.length; i++) {
        if (merged.length && out[i].start <= merged[merged.length - 1].end + 1e-9) {
            if (out[i].end > merged[merged.length - 1].end) merged[merged.length - 1].end = out[i].end;
        } else {
            merged.push({ start: out[i].start, end: out[i].end });
        }
    }
    return merged;
}

// ---------------------------------------------------------------- misc
function normIn(px, x0, w) {
    if (!(w > 0)) return 0;
    return clamp((px - x0) / w, 0, 1);
}

// Is the given index inside any merged gap? Caller keeps a moving pointer for
// O(N+G) waveform drawing.
function gapAt(gaps, index, ptr) {
    while (ptr < gaps.length && gaps[ptr].end < index) ptr++;
    if (ptr < gaps.length && index >= gaps[ptr].start && index <= gaps[ptr].end) return ptr;
    return -1;
}

// Equal-count sampling of a numeric array for bounded work.
function sampleStride(len, budget) {
    if (!isNum(len) || len <= 0) return 1;
    var b = isNum(budget) && budget > 32 ? budget : 4096;
    return Math.max(1, Math.ceil(len / b));
}

// ---------------------------------------------------------------- band ramps
// Explicit level ramp (e.g. the fixed octave-band palette purple-blue -> teal ->
// yellow-green). Stops are CSS colours ordered low -> high level; the same
// function drives bar fills, top caps and the shared colour bar so one level has
// one colour across every band.
function rampColor(stops, t) {
    if (!stops || !stops.length) return "#888888";
    if (stops.length === 1) return String(stops[0]);
    var x = clamp(isNum(t) ? t : 0, 0, 1) * (stops.length - 1);
    var i = Math.min(Math.floor(x), stops.length - 2);
    var f = x - i;
    var a = parseColor(stops[i]);
    var b = parseColor(stops[i + 1]);
    return "rgb(" + Math.round(a.r + (b.r - a.r) * f) + "," +
        Math.round(a.g + (b.g - a.g) * f) + "," +
        Math.round(a.b + (b.b - a.b) * f) + ")";
}

function isValidRamp(stops) {
    if (!stops || !stops.length) return false;
    for (var i = 0; i < stops.length; i++) {
        if (typeof stops[i] !== "string" || stops[i].length < 4) return false;
    }
    return true;
}

// ---------------------------------------------------------------- readouts
function withUnit(text, unit) {
    var u = typeof unit === "string" ? unit : "";
    var t = typeof text === "string" ? text : "";
    if (!u.length) return t;
    return t.length ? t + " " + u : u;
}

// ---------------------------------------------------------------- markers
// Peak/onset/event markers are pure coordinate annotations supplied by the
// page or the data source; the chart never derives them from the trace.
function markerGlyph(ctx, st, x, y, kind, color, size) {
    var s = isNum(size) && size > 2 ? size : 4;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1;
    if (kind === "onset" || kind === "event") {
        ctx.beginPath();
        ctx.moveTo(x, y - s);
        ctx.lineTo(x + s, y + s);
        ctx.lineTo(x - s, y + s);
        ctx.closePath();
        ctx.fill();
    } else if (kind === "cursor") {
        ctx.beginPath();
        ctx.arc(x, y, s, 0, Math.PI * 2);
        ctx.stroke();
    } else if (kind === "band") {
        ctx.beginPath();
        ctx.moveTo(x - s, y);
        ctx.lineTo(x + s, y);
        ctx.stroke();
    } else {
        // peak: diamond + inner dot reads at 1px lines on the black plot area
        ctx.beginPath();
        ctx.moveTo(x, y - s);
        ctx.lineTo(x + s, y);
        ctx.lineTo(x, y + s);
        ctx.lineTo(x - s, y);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = st.bg;
        ctx.beginPath();
        ctx.arc(x, y, 1.2, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.restore();
}

// Peak-envelope display extraction for long PCM/waveform traces. Each bucket
// keeps its min and max (in order), so transients are preserved; no averaging and
// no acoustic processing. Invalid samples emit null (gap), never a zero.
function peakEnvelope(values, budget) {
    var list = values || [];
    var b = isNum(budget) && budget > 64 ? Math.floor(budget) : 4096;
    if (list.length <= b) return list;
    var buckets = Math.max(1, Math.floor(b / 2));
    var stride = list.length / buckets;
    var out = [];
    for (var i = 0; i < buckets; i++) {
        var start = Math.floor(i * stride);
        var end = Math.min(list.length, Math.floor((i + 1) * stride));
        if (end <= start) continue;
        var lo = Infinity;
        var hi = -Infinity;
        var valid = false;
        for (var j = start; j < end; j++) {
            var v = list[j];
            if (!isNum(v)) continue;
            valid = true;
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }
        if (!valid) {
            out.push(null);
            out.push(null);
        } else {
            out.push(lo);
            out.push(hi);
        }
    }
    return out;
}

// Map a gap interval from the original sample domain into an envelope array
// produced by peakEnvelope() above (display mapping only).
function scaleGapsForEnvelope(gaps, originalLength, envelopeLength) {
    var out = [];
    var list = gaps || [];
    if (!isNum(originalLength) || originalLength <= 0 || !isNum(envelopeLength) || envelopeLength <= 0) return out;
    var factor = envelopeLength / originalLength;
    for (var i = 0; i < list.length; i++) {
        var g = list[i];
        if (!g || !isNum(g.start) || !isNum(g.end)) continue;
        var s = Math.floor(Math.min(g.start, g.end) * factor);
        var e = Math.ceil(Math.max(g.start, g.end) * factor);
        if (e < s) continue;
        out.push({ start: s, end: e });
    }
    return out;
}

function drawMarkers(ctx, st, markers, mapX, mapY, opts) {
    if (!markers || !markers.length) return 0;
    var o = opts && typeof opts === "object" ? opts : {};
    var hasProject = typeof o.project === "function";
    if (!hasProject && (typeof mapX !== "function" || typeof mapY !== "function")) return 0;
    var rc = o.rect || null;
    var lastRight = -1e9;
    var drawn = 0;
    ctx.font = fontSpec(st.fsSmall, st.mono);
    for (var i = 0; i < markers.length && i < 256; i++) {
        var m = markers[i];
        if (!m || !isNum(m.x) || !isNum(m.y)) continue;
        var x = NaN;
        var y = NaN;
        if (hasProject) {
            var projected = o.project(m);
            if (!projected || !isNum(projected.x) || !isNum(projected.y)) continue;
            x = projected.x;
            y = projected.y;
        } else {
            x = mapX(m.x);
            y = mapY(m.y);
        }
        if (!isFinite(x) || !isFinite(y)) continue;
        if (rc && (x < rc.x - 1 || x > rc.x + rc.w + 1 || y < rc.y - 1 || y > rc.y + rc.h + 1)) continue;
        var color = typeof m.color === "string" && m.color.length
            ? m.color : (typeof o.color === "string" && o.color.length ? o.color : st.cursorA);
        markerGlyph(ctx, st, x, y, String(m.kind || "peak"), color, isNum(m.size) ? m.size : 4);
        drawn++;
        var label = typeof m.label === "string" ? m.label : "";
        if (!label.length || o.labels === false) continue;
        var maxRight = rc ? rc.x + rc.w : x + 160;
        var tw = ctx.measureText(label).width;
        if (x + 8 + tw > maxRight + 1) {
            ctx.textAlign = "right";
            var lx = x - 8;
            if (lx - tw < lastRight + 6) continue;
            ctx.fillStyle = rgba(st.bg, 0.78);
            ctx.fillRect(lx - tw - 4, y - 15, tw + 7, 13);
            ctx.fillStyle = color;
            ctx.textBaseline = "middle";
            ctx.fillText(label, lx, y - 9);
            lastRight = lx;
        } else {
            ctx.textAlign = "left";
            ctx.fillStyle = rgba(st.bg, 0.78);
            ctx.fillRect(x + 6, y - 15, tw + 6, 13);
            ctx.fillStyle = color;
            ctx.textBaseline = "middle";
            ctx.fillText(label, x + 9, y - 9);
        }
    }
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    return drawn;
}

// Human-readable numbers without rounding small nonzero powers to zero.
function fmtReadout(value, format) {
    if (!isNum(value)) return "—";
    if (format && /^%\.?[0-9]*[fFeEd]$/.test(format)) return fmtValue(value,format);
    if (value===0 || (Math.floor(value)===value && Math.abs(value)<1e21))return String(value);
    return String(Number(value.toPrecision(6)));
}
