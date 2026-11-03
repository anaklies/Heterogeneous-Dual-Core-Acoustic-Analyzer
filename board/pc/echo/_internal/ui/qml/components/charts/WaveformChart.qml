// WaveformChart - six (or N) channel time-domain waveform, Qt Quick Canvas.
// Implements docs/frontend/CHART_DATA_CONTRACT.md section 1.
//
// Display-only: values are already-extracted [-1,1] float arrays (<=4096 per
// channel); no smoothing and no acoustic processing happens here.
// Colours/fonts come from the Theme context property; channel colours are
// supplied by the page. Gaps in the index domain break the polyline (a gap is
// never bridged by a straight line).
//
// QML note / documented contract deviation: Qt QML reserves the property change
// signal name selectionChanged for the selection property, so the interaction
// signal with (start,end) arguments is exposed additively as selectionEdited().
// Pages can also connect the automatic selectionChanged() and read selection.
import QtQuick
import QtQuick.Window
import "ChartUtil.js" as U

Item {
    id: root

    // ---------------------------------------------------------- contract inputs
    property var channels: []          // [{name,color,visible,values:[float,...]}]
    property real sampleRate: 0        // real DTO sample rate, never hardcoded
    property string startSampleIndex: "" // u64 decimal string, display only
    property var gaps: []              // [{start:index,end:index}]
    property string xMode: "time"      // "time" | "samples"
    property var yRange: null          // {min,max} or null = auto
    property bool stacked: true
    property var cursorA: null         // 0..1 normalised x
    property var cursorB: null
    property var selection: null       // {start,end} normalised x
    property bool interactive: true
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""

    // -------------------------------------------------- additive (optional) API
    property int dataRevision: 0       // bump to force a repaint of same arrays
    property string busyText: ""
    property string yUnit: ""
    property string xUnit: ""
    property string cursorLabelA: "A"
    property string cursorLabelB: "B"
    property string selectionLabel: ""

    // ---------------------------------------------------------- contract signals
    signal seekRequested(real position01)
    signal cursorChanged(real a, real b)
    signal selectionEdited(real start, real end)
    signal viewResetRequested()

    // ---------------------------------------------------------- theme / style
    readonly property real dpr: Screen.devicePixelRatio
    readonly property var channelPalette: Theme.channelColors
    readonly property string monoFamily: {
        var fams = Qt.fontFamilies();
        return fams.indexOf(Theme.fontMono) >= 0 ? Theme.fontMono : Theme.fontFamily;
    }
    readonly property var st: ({
        bg: Theme.plotBg,
        grid: Theme.plotGrid,
        minor: Theme.plotGridMinor,
        text: Theme.plotText,
        dim: Theme.plotTextDim,
        cursorA: Theme.plotCursorA,
        cursorB: Theme.plotCursorB,
        accent: Theme.accent,
        selection: Theme.selection,
        error: Theme.error,
        warn: Theme.warn,
        ok: Theme.ok,
        info: Theme.info,
        font: Theme.fontFamily,
        mono: monoFamily,
        fs: Math.max(14, Math.round(15 * Theme.fontScale)),
        fsSmall: Math.max(13, Math.round(14 * Theme.fontScale))
    })

    // ---------------------------------------------------------- view / interaction
    property real viewStart: 0
    property real viewEnd: 1
    property string dragMode: ""        // "" | pan | cursorA | cursorB | select
    property bool dragMoved: false
    property real pressX: -1
    property real lastX: -1
    property real dragCursorA: -1
    property real dragCursorB: -1
    property var internalSelection: null
    property bool internalSelectionValid: false

    // ---------------------------------------------------------- layout constants
    readonly property real marginLeft: 54
    readonly property real marginRight: 12
    readonly property real headerHeight: 22
    readonly property real marginBottom: 34

    // ---------------------------------------------------------- repaint plumbing
    function requestPaint() {
        if (canvas && canvas.available && visible) canvas.requestPaint();
    }
    onChannelsChanged: requestPaint()
    onGapsChanged: requestPaint()
    onYRangeChanged: requestPaint()
    onStackedChanged: requestPaint()
    onCursorAChanged: requestPaint()
    onCursorBChanged: requestPaint()
    onSelectionChanged: requestPaint()
    onDataRevisionChanged: requestPaint()
    onSampleRateChanged: requestPaint()
    onXModeChanged: requestPaint()
    onStartSampleIndexChanged: requestPaint()
    onYUnitChanged: requestPaint()
    onXUnitChanged: requestPaint()
    onBusyChanged: requestPaint()
    onEmptyTextChanged: requestPaint()
    onEmptyReasonChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onDprChanged: requestPaint()
    onVisibleChanged: if (visible) requestPaint()
    Connections {
        target: Theme
        function onChanged() { root.requestPaint(); }
    }

    // ---------------------------------------------------------- data helpers
    function visibleChannels() {
        var out = [];
        var list = channels;
        if (!list || !list.length) return out;
        for (var i = 0; i < list.length; i++) {
            var ch = list[i];
            if (!ch) continue;
            if (ch.visible === false) continue;
            if (!ch.values || !ch.values.length) continue;
            out.push(ch);
        }
        return out;
    }

    function maxPoints(list) {
        var n = 0;
        for (var i = 0; i < list.length; i++) {
            if (list[i].values.length > n) n = list[i].values.length;
        }
        return n;
    }

    function plotRect() {
        var x = marginLeft;
        var y = headerHeight;
        var w = Math.max(0, width - marginLeft - marginRight);
        var h = Math.max(0, height - headerHeight - marginBottom);
        return { x: x, y: y, w: w, h: h };
    }

    function normFromX(px) {
        var pr = plotRect();
        return U.clamp(viewStart + U.normIn(px, pr.x, pr.w) * (viewEnd - viewStart), 0, 1);
    }

    function screenFromNorm(nd) {
        var pr = plotRect();
        var span = viewEnd - viewStart;
        if (!(span > 0)) return pr.x;
        return pr.x + ((nd - viewStart) / span) * pr.w;
    }

    function snapNorm(nd, count) {
        if (count < 2) return U.clamp(nd, 0, 1);
        return U.clamp(Math.round(nd * (count - 1)) / (count - 1), 0, 1);
    }

    function displayCursorA(count) {
        if (dragMode === "cursorA" && dragCursorA >= 0) return dragCursorA;
        if (U.isNum(cursorA)) return U.clamp(cursorA, 0, 1);
        return dragCursorA >= 0 ? dragCursorA : null;
    }

    function displayCursorB(count) {
        if (dragMode === "cursorB" && dragCursorB >= 0) return dragCursorB;
        if (U.isNum(cursorB)) return U.clamp(cursorB, 0, 1);
        return dragCursorB >= 0 ? dragCursorB : null;
    }

    function displaySelection() {
        if (selection && U.isNum(selection.start) && U.isNum(selection.end)) return selection;
        if (internalSelectionValid) return internalSelection;
        return null;
    }

    function cursorValueText(nd, count) {
        if (!U.isNum(nd)) return "-";
        if (xMode === "time" && sampleRate > 0) {
            var sec = nd * (count - 1) / sampleRate;
            if (Math.abs(sec) >= 0.1) return U.fmtTick(sec, 0.001) + " s";
            return U.fmtTick(sec * 1e3, 0.01) + " ms";
        }
        return "#" + Math.round(nd * (count - 1));
    }

    function hitCursor(px) {
        var pr = plotRect();
        var best = "";
        var bestDist = 8;
        var count = maxPoints(visibleChannels());
        if (count < 2) return "";
        var a = displayCursorA(count);
        if (a !== null) {
            var d = Math.abs(screenFromNorm(a) - px);
            if (d < bestDist) { bestDist = d; best = "cursorA"; }
        }
        var b = displayCursorB(count);
        if (b !== null) {
            var d2 = Math.abs(screenFromNorm(b) - px);
            if (d2 < bestDist) { bestDist = d2; best = "cursorB"; }
        }
        return best;
    }

    function minViewSpan(count) {
        return U.clamp(8 / Math.max(8, count - 1), 1e-6, 1);
    }

    function zoomAt(px, factor) {
        var count = maxPoints(visibleChannels());
        var span = viewEnd - viewStart;
        if (!(span > 0)) { viewStart = 0; viewEnd = 1; return; }
        var anchor = normFromX(px);
        var newSpan = U.clamp(span * factor, minViewSpan(count), 1);
        viewStart = anchor - (anchor - viewStart) * (newSpan / span);
        viewEnd = viewStart + newSpan;
        if (viewStart < 0) { viewEnd -= viewStart; viewStart = 0; }
        if (viewEnd > 1) { viewStart -= (viewEnd - 1); viewEnd = 1; }
        if (viewStart < 0) viewStart = 0;
        requestPaint();
    }

    function applyPan(dx) {
        var pr = plotRect();
        var span = viewEnd - viewStart;
        if (!(span > 0) || !(pr.w > 0)) return;
        var shift = -dx / pr.w * span;
        viewStart += shift;
        viewEnd += shift;
        if (viewStart < 0) { viewEnd -= viewStart; viewStart = 0; }
        if (viewEnd > 1) { viewStart -= (viewEnd - 1); viewEnd = 1; }
        if (viewStart < 0) viewStart = 0;
        requestPaint();
    }

    function autoYRange(list) {
        var lo = Infinity;
        var hi = -Infinity;
        for (var c = 0; c < list.length; c++) {
            var vals = list[c].values;
            var stride = U.sampleStride(vals.length, 4096);
            for (var i = 0; i < vals.length; i += stride) {
                var v = vals[i];
                if (!U.isNum(v)) continue;
                if (v < lo) lo = v;
                if (v > hi) hi = v;
            }
        }
        if (lo === Infinity || hi === -Infinity) { lo = -1; hi = 1; }
        if (!(hi > lo)) { lo -= 0.5; hi += 0.5; }
        var pad = (hi - lo) * 0.06;
        return { min: lo - pad, max: hi + pad };
    }

    function effectiveYRange(list) {
        if (yRange && U.isNum(yRange.min) && U.isNum(yRange.max) && yRange.max > yRange.min) {
            return { min: yRange.min, max: yRange.max, fixed: true };
        }
        var r = autoYRange(list);
        var nice = U.linearTicks(r.min, r.max, 4);
        return { min: nice.min, max: nice.max, fixed: false };
    }

    // ---------------------------------------------------------- painting
    function paintChart(ctx) {
        if (!ctx) return;
        ctx.save();
        
        ctx.fillStyle = st.bg;
        ctx.fillRect(0, 0, width, height);

        if (width < 4 || height < 4) { ctx.restore(); return; }
        U.drawFrame(ctx, st, 0, 0, width, height);

        if (busy) {
            U.drawBusyState(ctx, st, width, height, busyText);
            ctx.restore();
            return;
        }

        var list = visibleChannels();
        var count = maxPoints(list);
        if (count < 2) {
            U.drawEmptyState(ctx, st, width, height, emptyText, emptyReason);
            ctx.restore();
            return;
        }

        var pr = plotRect();
        if (pr.w < 8 || pr.h < 8) { ctx.restore(); return; }
        var yr = effectiveYRange(list);
        var ymin = yr.min;
        var ymax = yr.max;
        var yspan = ymax - ymin;
        var mergedGaps = U.sortedGaps(gaps);
        var channelCount = list.length;

        // horizontal scale value <-> seconds for the current view
        var duration = sampleRate > 0 ? (count - 1) / sampleRate : 0;
        var timeUnit = "s";
        var timeMult = 1;
        if (xMode === "time" && duration > 0) {
            if (duration < 0.002) { timeUnit = "us"; timeMult = 1e6; }
            else if (duration < 1) { timeUnit = "ms"; timeMult = 1e3; }
        }

        var xScale = (xMode === "time" && sampleRate > 0 && duration > 0)
            ? duration * timeMult : (count - 1);
        // ---- x ticks (1/2/5 over the visible normalised window)
        var xTickTarget = Math.max(2, Math.floor(pr.w / 95));
        var xr = U.linearTicks(viewStart, viewEnd, xTickTarget);
        function xLabelFor(nd) {
            return U.fmtTick(nd * xScale, xr.step * xScale);
        }
        var xTicks = [];
        for (var xt = 0; xt < xr.ticks.length; xt++) {
            var tv = xr.ticks[xt];
            if (tv >= viewStart - 1e-9 && tv <= viewEnd + 1e-9) xTicks.push(tv);
        }
        if (xTicks.length < 2) xTicks = [viewStart, viewEnd];
        var xStep = xr.step;

        // ---- vertical grid: minor 1/5 subdivisions, then major lines
        ctx.strokeStyle = st.minor;
        ctx.lineWidth = 1;
        for (var gx = 0; gx < xTicks.length; gx++) {
            var x0 = screenFromNorm(xTicks[gx]);
            if (gx + 1 < xTicks.length && xStep > 0) {
                for (var sub = 1; sub < 5; sub++) {
                    var sx = screenFromNorm(xTicks[gx] + xStep * sub / 5);
                    if (sx < pr.x - 0.5 || sx > pr.x + pr.w + 0.5) continue;
                    ctx.beginPath();
                    ctx.moveTo(sx + 0.5, pr.y);
                    ctx.lineTo(sx + 0.5, pr.y + pr.h);
                    ctx.stroke();
                }
            }
            if (x0 < pr.x - 0.5 || x0 > pr.x + pr.w + 0.5) continue;
        }
        ctx.strokeStyle = st.grid;
        for (var gx2 = 0; gx2 < xTicks.length; gx2++) {
            var px = screenFromNorm(xTicks[gx2]);
            if (px < pr.x - 0.5 || px > pr.x + pr.w + 0.5) continue;
            ctx.beginPath();
            ctx.moveTo(px + 0.5, pr.y);
            ctx.lineTo(px + 0.5, pr.y + pr.h);
            ctx.stroke();
        }

        // ---- horizontal grid
        var laneH = pr.h / channelCount;
        ctx.strokeStyle = st.grid;
        if (stacked) {
            for (var lane = 1; lane < channelCount; lane++) {
                var ly = pr.y + laneH * lane;
                ctx.beginPath();
                ctx.moveTo(pr.x, ly + 0.5);
                ctx.lineTo(pr.x + pr.w, ly + 0.5);
                ctx.stroke();
            }
        } else {
            var yTicks = U.linearTicks(ymin, ymax, Math.max(2, Math.floor(pr.h / 46))).ticks;
            for (var yt = 0; yt < yTicks.length; yt++) {
                var yv = yTicks[yt];
                if (yv < ymin - 1e-9 || yv > ymax + 1e-9) continue;
                var yy = pr.y + (1 - (yv - ymin) / yspan) * pr.h;
                ctx.beginPath();
                ctx.moveTo(pr.x, yy + 0.5);
                ctx.lineTo(pr.x + pr.w, yy + 0.5);
                ctx.stroke();
                ctx.fillStyle = st.dim;
                ctx.font = U.fontSpec(st.fsSmall, st.mono);
                ctx.textAlign = "right";
                ctx.textBaseline = "middle";
                ctx.fillText(U.fmtTick(yv, (ymax - ymin) / 5), pr.x - 6, yy);
            }
        }

        // ---- gaps (shaded, broken line is drawn per channel below)
        for (var gi = 0; gi < mergedGaps.length; gi++) {
            var gxa = screenFromNorm(U.clamp(mergedGaps[gi].start / (count - 1), 0, 1));
            var gxb = screenFromNorm(U.clamp(mergedGaps[gi].end / (count - 1), 0, 1));
            var gLeft = Math.max(pr.x, Math.min(gxa, gxb));
            var gRight = Math.min(pr.x + pr.w, Math.max(gxa, gxb));
            if (gRight <= gLeft) {
                gLeft = Math.max(pr.x, Math.min(gLeft, pr.x + pr.w));
                gRight = gLeft + 1;
            }
            ctx.fillStyle = U.rgba(st.error, 0.10);
            ctx.fillRect(gLeft, pr.y, Math.max(1, gRight - gLeft), pr.h);
            ctx.save();
            ctx.strokeStyle = U.rgba(st.error, 0.45);
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.moveTo(gLeft + 0.5, pr.y);
            ctx.lineTo(gLeft + 0.5, pr.y + pr.h);
            ctx.moveTo(gRight + 0.5, pr.y);
            ctx.lineTo(gRight + 0.5, pr.y + pr.h);
            ctx.stroke();
            ctx.restore();
        }

        // ---- selection band
        var sel = displaySelection();
        if (sel) {
            var sa = U.clamp(Math.min(sel.start, sel.end), 0, 1);
            var sb = U.clamp(Math.max(sel.start, sel.end), 0, 1);
            var sx0 = screenFromNorm(sa);
            var sx1 = screenFromNorm(sb);
            var sLeft = Math.max(pr.x, Math.min(sx0, sx1));
            var sRight = Math.min(pr.x + pr.w, Math.max(sx0, sx1));
            if (sRight > sLeft) {
                ctx.fillStyle = U.rgba(st.accent, 0.16);
                ctx.fillRect(sLeft, pr.y, sRight - sLeft, pr.h);
                ctx.fillStyle = U.rgba(st.accent, 0.7);
                ctx.fillRect(sLeft, pr.y, 1, pr.h);
                ctx.fillRect(sRight - 1, pr.y, 1, pr.h);
            }
        }

        // ---- stacked lane separators (1 px low-saturation structure lines)
        if (stacked) {
            ctx.strokeStyle = U.rgba(st.grid, 0.55);
            ctx.lineWidth = 1;
            for (var lane = 1; lane < channelCount; lane++) {
                var ly = pr.y + laneH * lane;
                ctx.beginPath();
                ctx.moveTo(pr.x, ly + 0.5);
                ctx.lineTo(pr.x + pr.w, ly + 0.5);
                ctx.stroke();
            }
        }

        // ---- waveforms
        for (var c = 0; c < channelCount; c++) {
            var ch = list[c];
            var vals = ch.values;
            var n = vals.length;
            if (!(n > 1)) continue;
            var laneTop = stacked ? pr.y + laneH * c : pr.y;
            var laneBottom = stacked ? laneTop + laneH : pr.y + pr.h;
            var pad = stacked ? Math.min(6, Math.max(2, laneH * 0.12)) : 2;
            var yTop = laneTop + pad;
            var yBot = laneBottom - pad;
            var zeroY = yBot - ((0 - ymin) / yspan) * (yBot - yTop);
            if (stacked && zeroY > yTop && zeroY < yBot) {
                ctx.strokeStyle = U.rgba(st.text, 0.26);
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(pr.x, zeroY + 0.5);
                ctx.lineTo(pr.x + pr.w, zeroY + 0.5);
                ctx.stroke();
            }
            var color = typeof ch.color === "string" && ch.color.length ? ch.color
                : channelPalette[c % channelPalette.length];
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.3;
            ctx.lineJoin = "round";
            ctx.beginPath();
            var i0 = Math.max(0, Math.floor(viewStart * (n - 1)) - 1);
            var i1 = Math.min(n - 1, Math.ceil(viewEnd * (n - 1)) + 1);
            var stride = U.sampleStride(i1 - i0 + 1, Math.max(512, Math.floor(pr.w * 2)));
            var penDown = false;
            var gapPtr = 0;
            for (var i = i0; i <= i1; i += stride) {
                var v = vals[i];
                if (!U.isNum(v)) { penDown = false; continue; }
                while (gapPtr < mergedGaps.length && mergedGaps[gapPtr].end < i) gapPtr++;
                var inGap = gapPtr < mergedGaps.length && i >= mergedGaps[gapPtr].start && i <= mergedGaps[gapPtr].end;
                if (inGap) { penDown = false; continue; }
                var nx = i / (n - 1);
                if (nx < viewStart - 1e-9 || nx > viewEnd + 1e-9) { penDown = false; continue; }
                var px2 = screenFromNorm(nx);
                var py = yBot - ((v - ymin) / yspan) * (yBot - yTop);
                if (!penDown) { ctx.moveTo(px2, py); penDown = true; }
                else ctx.lineTo(px2, py);
            }
            ctx.stroke();

            // per-lane channel tag + y range labels
            if (stacked) {
                var tagX = pr.x + 6;
                var tagY = laneTop + 11;
                ctx.fillStyle = color;
                ctx.fillRect(tagX, tagY - 7, 6, 6);
                ctx.fillStyle = st.dim;
                ctx.font = U.fontSpec(st.fsSmall, st.font);
                ctx.textAlign = "left";
                ctx.textBaseline = "alphabetic";
                ctx.fillText(U.ellipsize(ctx, String(ch.name === undefined ? "" : ch.name), pr.w * 0.5), tagX + 10, tagY);
                if (laneH > 30) {
                    ctx.fillStyle = st.dim;
                    ctx.font = U.fontSpec(st.fsSmall, st.mono);
                    ctx.textAlign = "right";
                    ctx.textBaseline = "middle";
                    ctx.fillText(U.fmtTick(ymax, (ymax - ymin) / 4), pr.x - 6, yTop + 2);
                    ctx.fillText(U.fmtTick(ymin, (ymax - ymin) / 4), pr.x - 6, yBot - 2);
                }
            }
        }

        // ---- frame
        U.drawFrame(ctx, st, pr.x, pr.y, pr.w, pr.h);

        // ---- x tick labels
        ctx.font = U.fontSpec(st.fs, st.mono);
        ctx.fillStyle = st.dim;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        var lastRight = -1e9;
        for (var lt = 0; lt < xTicks.length; lt++) {
            var tval = xTicks[lt];
            var lx = screenFromNorm(tval);
            if (lx < pr.x - 1 || lx > pr.x + pr.w + 1) continue;
            var label = xLabelFor(tval);
            var lw = ctx.measureText(label).width;
            if (lx - lw / 2 < lastRight + 8) continue;
            ctx.fillText(label, lx, pr.y + pr.h + 6);
            lastRight = lx + lw / 2;
        }

        // ---- bottom annotations: y unit (left) and x unit / sample origin (right)
        ctx.font = U.fontSpec(st.fsSmall, st.mono);
        ctx.fillStyle = st.dim;
        ctx.textAlign = "left";
        ctx.textBaseline = "alphabetic";
        if (yUnit.length) ctx.fillText(U.ellipsize(ctx, yUnit, pr.w * 0.3), pr.x, pr.y + pr.h + marginBottom - 4);
        var rightText = "";
        if (xMode === "time" && sampleRate > 0) rightText = xUnit.length ? xUnit : timeUnit;
        else if (xMode === "samples" && startSampleIndex.length) rightText = "#" + startSampleIndex;
        if (rightText.length) {
            ctx.textAlign = "right";
            ctx.fillText(U.ellipsize(ctx, rightText, pr.w * 0.55), pr.x + pr.w, pr.y + pr.h + marginBottom - 4);
        }

        // ---- header: legend (overlay) or y unit, then cursor read-out
        ctx.textBaseline = "middle";
        var headerY = headerHeight / 2;
        var legendMaxRight = pr.x + pr.w * 0.55;
        if (!stacked) {
            var lx2 = pr.x;
            ctx.font = U.fontSpec(st.fsSmall, st.font);
            for (var lc = 0; lc < channelCount; lc++) {
                var lch = list[lc];
                var name = String(lch.name === undefined ? "" : lch.name);
                var nw = ctx.measureText(name).width;
                if (lx2 + 18 + nw > legendMaxRight) break;
                var lcolor = typeof lch.color === "string" && lch.color.length ? lch.color
                    : channelPalette[lc % channelPalette.length];
                ctx.fillStyle = lcolor;
                ctx.fillRect(lx2, headerY - 4, 8, 8);
                ctx.fillStyle = st.dim;
                ctx.textAlign = "left";
                ctx.fillText(name, lx2 + 12, headerY);
                lx2 += 18 + nw;
            }
        } else if (yUnit.length) {
            ctx.font = U.fontSpec(st.fsSmall, st.mono);
            ctx.fillStyle = st.dim;
            ctx.textAlign = "left";
            ctx.fillText(U.ellipsize(ctx, yUnit, pr.w * 0.3), pr.x, headerY);
        }

        var ca = displayCursorA(count);
        var cb = displayCursorB(count);
        if (ca !== null || cb !== null) {
            var parts = [];
            var totalW = 0;
            ctx.font = U.fontSpec(st.fsSmall, st.mono);
            if (ca !== null) {
                parts.push({ text: cursorLabelA + " " + cursorValueText(ca, count), color: st.cursorA });
            }
            if (cb !== null) {
                parts.push({ text: cursorLabelB + " " + cursorValueText(cb, count), color: st.cursorB });
            }
            if (ca !== null && cb !== null && xMode === "time" && sampleRate > 0) {
                var dsec = Math.abs(cb - ca) * (count - 1) / sampleRate;
                var dlabel = Math.abs(dsec) >= 0.1 ? U.fmtTick(dsec, 0.001) + " s" : U.fmtTick(dsec * 1e3, 0.01) + " ms";
                parts.push({ text: "\u0394 " + dlabel, color: st.dim });
            }
            for (var p = 0; p < parts.length; p++) totalW += ctx.measureText(parts[p].text).width + 14;
            var rx = pr.x + pr.w;
            if (rx - totalW < legendMaxRight) {
                // not enough room: fall back to compact A/B only
                parts = parts.slice(0, 2);
                totalW = 0;
                for (var p2 = 0; p2 < parts.length; p2++) totalW += ctx.measureText(parts[p2].text).width + 14;
            }
            for (var p3 = 0; p3 < parts.length; p3++) {
                var tw = ctx.measureText(parts[p3].text).width;
                ctx.fillStyle = parts[p3].color;
                ctx.textAlign = "right";
                ctx.fillText(parts[p3].text, rx, headerY);
                rx -= tw + 14;
            }
        }

        // ---- cursors
        drawCursorLine(ctx, pr, count, ca, st.cursorA, cursorLabelA, 0);
        drawCursorLine(ctx, pr, count, cb, st.cursorB, cursorLabelB, 1);

        // ---- selection label
        if (sel && selectionLabel.length) {
            ctx.font = U.fontSpec(st.fsSmall, st.font);
            ctx.fillStyle = st.accent;
            ctx.textAlign = "left";
            ctx.textBaseline = "top";
            ctx.fillText(U.ellipsize(ctx, selectionLabel, pr.w * 0.5), pr.x + 4, pr.y + 4);
        }

        ctx.restore();
    }

    function drawCursorLine(ctx, pr, count, nd, color, label, slot) {
        if (nd === null || nd === undefined) return;
        var x = screenFromNorm(nd);
        if (x < pr.x - 1 || x > pr.x + pr.w + 1) return;
        ctx.save();
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(x + 0.5, pr.y);
        ctx.lineTo(x + 0.5, pr.y + pr.h);
        ctx.stroke();
        ctx.setLineDash([]);
        var text = label + " " + cursorValueText(nd, count);
        ctx.font = U.fontSpec(st.fsSmall, st.mono);
        var tw = ctx.measureText(text).width;
        var bx = Math.min(Math.max(pr.x + 2, x + 4), pr.x + pr.w - tw - 10);
        var by = pr.y + 4 + slot * 18;
        ctx.fillStyle = U.rgba(st.bg, 0.82);
        ctx.fillRect(bx - 2, by, tw + 8, 16);
        ctx.fillStyle = color;
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText(text, bx + 2, by + 8);
        ctx.restore();
    }

    Canvas {
        id: canvas
        smooth:false
        anchors.fill: parent
        onPaint: root.paintChart(getContext("2d"))
        onAvailableChanged: if (available) root.requestPaint()
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        hoverEnabled: true
        cursorShape: Qt.ArrowCursor

        onPressed: function (ev) {
            if (!root.interactive || root.busy) return;
            var pr = root.plotRect();
            if (ev.x < pr.x || ev.x > pr.x + pr.w || ev.y < pr.y || ev.y > pr.y + pr.h) return;
            ev.accepted = true;
            root.pressX = ev.x;
            root.lastX = ev.x;
            root.dragMoved = false;
            var hit = root.hitCursor(ev.x);
            if (hit !== "") {
                root.dragMode = hit;
            } else if (ev.modifiers & Qt.ShiftModifier) {
                root.dragMode = "select";
                var n0 = root.snapNorm(root.normFromX(ev.x), root.maxPoints(root.visibleChannels()));
                root.internalSelection = { start: n0, end: n0 };
                root.internalSelectionValid = true;
            } else {
                root.dragMode = "pan";
            }
            root.requestPaint();
        }

        onPositionChanged: function (ev) {
            if (!root.interactive) return;
            if (!pressed) {
                cursorShape = root.hitCursor(ev.x) !== "" ? Qt.SizeHorCursor : Qt.ArrowCursor;
                return;
            }
            if (root.dragMode === "") return;
            var count = root.maxPoints(root.visibleChannels());
            if (Math.abs(ev.x - root.pressX) > 3) root.dragMoved = true;
            if (root.dragMode === "pan") {
                root.applyPan(ev.x - root.lastX);
                root.lastX = ev.x;
            } else if (root.dragMode === "cursorA" || root.dragMode === "cursorB") {
                var nd = root.snapNorm(root.normFromX(ev.x), count);
                if (root.dragMode === "cursorA") root.dragCursorA = nd;
                else root.dragCursorB = nd;
                root.requestPaint();
            } else if (root.dragMode === "select") {
                var n1 = root.snapNorm(root.normFromX(ev.x), count);
                root.internalSelection = {
                    start: root.internalSelection ? root.internalSelection.start : n1,
                    end: n1
                };
                root.internalSelectionValid = true;
                root.requestPaint();
            }
        }

        onReleased: function (ev) {
            if (root.dragMode === "") return;
            var count = root.maxPoints(root.visibleChannels());
            var mode = root.dragMode;
            root.dragMode = "";
            if (mode === "pan" && !root.dragMoved) {
                root.seekRequested(root.normFromX(ev.x));
            } else if (mode === "cursorA" || mode === "cursorB") {
                var a = root.displayCursorA(count);
                var b = root.displayCursorB(count);
                if (a === null) a = -1;
                if (b === null) b = -1;
                root.cursorChanged(a, b);
            } else if (mode === "select" && root.internalSelection) {
                var s0 = Math.min(root.internalSelection.start, root.internalSelection.end);
                var s1 = Math.max(root.internalSelection.start, root.internalSelection.end);
                if (s1 - s0 < 1e-9) {
                    root.internalSelectionValid = false;
                    root.internalSelection = null;
                } else {
                    root.selectionEdited(s0, s1);
                }
            }
            root.requestPaint();
        }

        onDoubleClicked: function (ev) {
            if (!root.interactive) return;
            var pr = root.plotRect();
            if (ev.x < pr.x || ev.x > pr.x + pr.w || ev.y < pr.y || ev.y > pr.y + pr.h) return;
            root.viewStart = 0;
            root.viewEnd = 1;
            root.viewResetRequested();
            root.requestPaint();
        }

        onWheel: function (wheel) {
            if (!root.interactive || root.busy) return;
            var pr = root.plotRect();
            if (wheel.x < pr.x || wheel.x > pr.x + pr.w) return;
            var delta = wheel.angleDelta.y !== 0 ? wheel.angleDelta.y : wheel.pixelDelta.y;
            if (delta === 0) return;
            wheel.accepted = true;
            root.zoomAt(wheel.x, delta > 0 ? 0.8 : 1.25);
        }
    }
}
