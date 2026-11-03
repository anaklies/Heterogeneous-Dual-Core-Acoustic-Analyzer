// BarChart - octave-band / band-level bar chart. Implements
// CHART_DATA_CONTRACT.md section 3.
//
// Bars are drawn from a labelled baseline (0 for linear axes, the axis bottom
// for log axes). invalid categories never render a value of 0: they show the
// dash placeholder instead. xMode "centerFrequency" lays bars out on a true
// logarithmic frequency axis when the page supplies each category's real
// center frequency (additive optional field centerFrequency); otherwise it
// falls back to equal category spacing rather than inventing frequencies.
import QtQuick
import QtQuick.Window
import "ChartUtil.js" as U

Item {
    id: root
    property bool inspectionEnabled: false
    property bool showValueLabels: true
    property real heldMin:NaN
    property real heldMax:NaN
    property string heldUnit:""
    function resetScale(){heldMin=NaN;heldMax=NaN;requestPaint();}

    // ---------------------------------------------------------- contract inputs
    property var categories: []       // [{label,value,color?,valid,centerFrequency?}]
    property string displayMode: "bars" // "bars" or "steps"
    property color traceColor: Theme.channelColors[0]
    property bool uniformColor: false
    property bool levelGradient: false
    property string xMode: "category" // "category" | "centerFrequency"
    property var yAxis: null          // {min,max,label,unit,scale}
    property var limitLine: null      // {value,label,color}
    property var referenceValues: []  // [{value,label,color}]
    property string valueFormat: ""
    property bool interactive: true
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""

    // -------------------------------------------------- additive (optional) API
    property int dataRevision: 0
    property string busyText: ""
    property string xLabel: ""
    property string xUnit: ""
    // additive: explicit low->high level ramp shared across all bands (the fixed
    // octave palette). Empty = legacy viridis level gradient.
    property var bandRamp: []
    // additive: optional shared colour-scale legend {min,max,label,unit,stops[],locked}
    property var colorScale: null
    property string hoverInfo: ""
    property real hoverX: 0
    property real hoverY: 0
    property var _centers: []
    function hoverTextAt(px) {
        if (!_centers || !_centers.length) return ""
        var best = -1
        var bestD = 28
        for (var i = 0; i < _centers.length; i++) {
            var d = Math.abs(Number(_centers[i]) - px)
            if (d < bestD) { bestD = d; best = i }
        }
        if (best < 0) return ""
        var cat = categories[best]
        if (!cat) return ""
        var val = categoryValue(cat)
        var unit = yAxis && yAxis.unit ? " " + yAxis.unit : ""
        var label = cat.label !== undefined && String(cat.label).length
                    ? String(cat.label) : ("#" + (best + 1))
        if (!isFinite(val)) return label + "\n—"
        return label + "\n" + U.fmtValue(val, valueFormat) + unit
    }
    Rectangle {
        id: hoverTip
        visible: root.hoverInfo.length > 0
        z: 200
        x: Math.min(Math.max(6, root.hoverX + 14), root.width - width - 6)
        y: Math.min(Math.max(6, root.hoverY + 14), root.height - height - 6)
        width: hoverText.implicitWidth + 18
        height: hoverText.implicitHeight + 12
        radius: 6
        color: Theme.panelBg
        border.width: 1
        border.color: Theme.accent
        opacity: 0.96
        Text {
            id: hoverText
            anchors.centerIn: parent
            text: root.hoverInfo
            color: Theme.textPrimary
            font.family: Theme.fontMono
            font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
        }
    }

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

    // ---------------------------------------------------------- repaint plumbing
    function requestPaint() {
        if (canvas && canvas.available && visible) canvas.requestPaint();
    }
    onDisplayModeChanged: requestPaint()
    onTraceColorChanged: requestPaint()
    onUniformColorChanged: requestPaint()
    onLevelGradientChanged: requestPaint()
    onCategoriesChanged: requestPaint()
    onXModeChanged: requestPaint()
    onYAxisChanged: requestPaint()
    onLimitLineChanged: requestPaint()
    onReferenceValuesChanged: requestPaint()
    onValueFormatChanged: requestPaint()
    onDataRevisionChanged: requestPaint()
    onBusyChanged: requestPaint()
    onEmptyTextChanged: requestPaint()
    onEmptyReasonChanged: requestPaint()
    onXLabelChanged: requestPaint()
    onXUnitChanged: requestPaint()
    onBandRampChanged: requestPaint()
    onColorScaleChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onDprChanged: requestPaint()
    onVisibleChanged: if (visible) requestPaint()
    Connections {
        target: Theme
        function onChanged() { root.requestPaint(); }
    }

    // ---------------------------------------------------------- helpers
    function validCategories() {
        var out = [];
        var list = categories;
        if (!list || !list.length) return out;
        for (var i = 0; i < list.length; i++) {
            if (list[i]) out.push(list[i]);
        }
        return out;
    }

    function hasLogCenters() {
        var cats = validCategories();
        if (!cats.length) return false;
        for (var i = 0; i < cats.length; i++) {
            var cf = cats[i].centerFrequency;
            if (!U.isNum(cf) || cf <= 0) return false;
        }
        return true;
    }

    function categoryValue(cat) {
        if (!cat) return NaN;
        if (cat.valid === false) return NaN;
        return U.isNum(cat.value) ? cat.value : NaN;
    }

    // ---------------------------------------------------------- painting
    // Steps preserve an explicit dB zoom range; bar baseline expansion is
    // specific to the legacy bar mode.
    function resolvedAxis(values, targetCount) {
        var axis = U.prepareAxis(yAxis, values, 0, 1);
        if (axis.auto && axis.scale === "linear" && displayMode === "bars") {
            axis.min = Math.min(0, axis.min);
            axis.max = Math.max(0, axis.max);
        }
        if(axis.unit!==heldUnit){heldUnit=axis.unit;heldMin=NaN;heldMax=NaN;}
        heldMin=isFinite(heldMin)?Math.min(heldMin,axis.min):axis.min;
        heldMax=isFinite(heldMax)?Math.max(heldMax,axis.max):axis.max;
        axis.min=heldMin;axis.max=heldMax;
        return U.snapLinearDomain(axis, targetCount);
    }

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
        var cats = validCategories();
        if (!cats.length) {
            U.drawEmptyState(ctx, st, width, height, emptyText, emptyReason);
            ctx.restore();
            return;
        }

        // ---- layout (bottom margin depends on label fit)
        var ml = 56;
        var mr = (colorScale ? 84 : 14);
        var header = 18;
        var plotW = Math.max(8, width - ml - mr);
        var plotH = Math.max(8, height - header - 30);
        var bandW = plotW / cats.length;
        ctx.font = U.fontSpec(st.fs, st.font);
        var maxLabelW = 0;
        for (var li = 0; li < cats.length; li++) {
            var lab = String(cats[li].label === undefined ? "" : cats[li].label);
            var lw = ctx.measureText(lab).width;
            if (lw > maxLabelW) maxLabelW = lw;
        }
        var logCenters = xMode === "centerFrequency" && hasLogCenters();
        var rotated = maxLabelW > bandW - 8;
        var mb = rotated ? 48 : (logCenters ? 44 : 30);
        var pr = { x: ml, y: header, w: plotW, h: Math.max(8, height - header - mb) };

        // ---- value domain
        var values = [];
        for (var vi = 0; vi < cats.length; vi++) {
            var cv = categoryValue(cats[vi]);
            if (U.isNum(cv)) values.push(cv);
        }
        var axis = resolvedAxis(values, Math.max(2, Math.floor(pr.h / 46)));
        var logScale = axis.scale === "log";
        var clipped = 0;
        var ymin = axis.min;
        var ymax = axis.max;

        function yPix(v) {
            if (logScale) {
                if (!(v > 0) || !(ymin > 0) || !(ymax > ymin)) return NaN;
                return pr.y + (1 - U.log10(v / ymin) / U.log10(ymax / ymin)) * pr.h;
            }
            if (!(ymax > ymin)) return NaN;
            return pr.y + (1 - (v - ymin) / (ymax - ymin)) * pr.h;
        }
        // Bars grow from the axis bottom unless zero is strictly inside the
        // domain (dBFS-style ranges ending at 0 must not grow from the top).
        var zeroInside = ymin < 0 && ymax > 0;
        var baseY = logScale ? pr.y + pr.h : yPix(zeroInside ? 0 : ymin);
        if (!isFinite(baseY)) baseY = pr.y + pr.h;
        baseY = U.clamp(baseY, pr.y, pr.y + pr.h);

        // ---- y grid + tick labels (1/2/5)
        var targetY = Math.max(4, Math.floor(pr.h / 34));
        var yt = logScale ? U.logTicks(ymin, ymax, targetY) : U.linearTicks(ymin, ymax, targetY);
        var yStep = logScale ? 0 : yt.step;
        ctx.lineWidth = 1;
        for (var yi = 0; yi < yt.ticks.length; yi++) {
            var yv = yt.ticks[yi];
            if (logScale ? (yv < ymin * (1 - 1e-9) || yv > ymax * (1 + 1e-9)) : (yv < ymin - 1e-9 || yv > ymax + 1e-9)) continue;
            var yy = yPix(yv);
            if (!isFinite(yy)) continue;
            ctx.strokeStyle = Math.abs(yv) < 1e-12 ? st.grid : st.minor;
            ctx.beginPath();
            ctx.moveTo(pr.x, yy + 0.5);
            ctx.lineTo(pr.x + pr.w, yy + 0.5);
            ctx.stroke();
            ctx.fillStyle = st.dim;
            ctx.font = U.fontSpec(st.fsSmall, st.mono);
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            ctx.fillText(U.fmtTick(yv, yStep), pr.x - 6, yy);
        }

        // ---- x band geometry
        var centers = [];   // screen x of each bar center
        var barWidths = [];
        var cfLo = 1;
        var cfHi = 10;
        function cfX(v) {
            if (!(cfHi > cfLo) || !(v > 0)) return pr.x;
            return pr.x + (U.log10(v / cfLo) / U.log10(cfHi / cfLo)) * pr.w;
        }
        if (logCenters) {
            var cfMin = Infinity;
            var cfMax = -Infinity;
            for (var lc = 0; lc < cats.length; lc++) {
                var cf = cats[lc].centerFrequency;
                if (cf < cfMin) cfMin = cf;
                if (cf > cfMax) cfMax = cf;
            }
            cfLo = cfMin / 1.35;
            cfHi = cfMax * 1.35;
            if (!(cfHi > cfLo)) { cfLo = cfMin; cfHi = cfMax * 1.1; }
            for (var cc = 0; cc < cats.length; cc++) centers.push(cfX(cats[cc].centerFrequency));
            for (var cw = 0; cw < centers.length; cw++) {
                var leftEdge = cw > 0 ? (centers[cw - 1] + centers[cw]) / 2 : pr.x;
                var rightEdge = cw < centers.length - 1 ? (centers[cw] + centers[cw + 1]) / 2 : pr.x + pr.w;
                // Symmetric bars must fit both half-cells, including end bands.
                barWidths.push(Math.max(1, 2*Math.min(centers[cw]-leftEdge,rightEdge-centers[cw])-4));
            }
        } else {
            for (var b = 0; b < cats.length; b++) centers.push(pr.x + bandW * (b + 0.5));
            for (var bw = 0; bw < cats.length; bw++) barWidths.push(Math.max(1, bandW - 4));
            // compact histogram: no inter-band separators
        }

        // ---- hover geometry
        root._centers = centers

        // ---- bars
        var lastValueRight = -1e9;
        var previousStep = null;
        ctx.save();
        ctx.beginPath(); ctx.rect(pr.x, pr.y, pr.w, pr.h); ctx.clip();
        for (var bi = 0; bi < cats.length; bi++) {
            var cat = cats[bi];
            var v = categoryValue(cat);
            var cx = centers[bi];
            var bw2 = barWidths[bi];
            var color = typeof cat.color === "string" && cat.color.length
                ? cat.color : channelPalette[bi % channelPalette.length];
            if (uniformColor) color = String(traceColor);
            if (!U.isNum(v)) {
                // invalid / missing: dash placeholder, never a fake 0 bar
                ctx.fillStyle = st.dim;
                ctx.font = U.fontSpec(st.fsSmall, st.mono);
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText("\u2014", cx, baseY - 8);
                previousStep = null;
                continue;
            }
            if (logScale && !(v > 0)) { clipped++; previousStep = null; continue; }
            var top = yPix(v);
            if (!isFinite(top)) continue;
            var barTop = Math.min(top, baseY);
            var barH = Math.abs(baseY - top);
            if (barH < 0.5) barH = 0.5;
            if (displayMode === "steps") {
                var left = bi > 0 ? (centers[bi - 1] + cx) / 2 : pr.x;
                var right = bi + 1 < centers.length ? (cx + centers[bi + 1]) / 2 : pr.x + pr.w;
                ctx.fillStyle = U.rgba(String(traceColor), 0.14);
                ctx.fillRect(left, barTop, right - left, barH);
                ctx.strokeStyle = String(traceColor);
                ctx.lineWidth = 0.9;
                ctx.beginPath();
                if (previousStep !== null) {
                    ctx.moveTo(left, previousStep); ctx.lineTo(left, top);
                } else ctx.moveTo(left, top);
                ctx.lineTo(right, top); ctx.stroke();
                previousStep = top;
                continue;
            }
            var ramp = U.isValidRamp(bandRamp) ? bandRamp : null;
            if (levelGradient) {
                // One level-calibrated ramp across the axis: an equal dB value
                // has the same color in every bar, as on an acoustic instrument.
                var grad = ctx.createLinearGradient(0, pr.y + pr.h, 0, pr.y);
                for (var stop = 0; stop <= 16; stop++) {
                    var ft = stop / 16;
                    grad.addColorStop(ft, ramp ? U.rampColor(ramp, ft) : U.paletteColor("viridis", ft));
                }
                ctx.fillStyle = grad;
            } else ctx.fillStyle = U.rgba(color, 0.85);
            ctx.fillRect(cx - bw2 / 2, barTop, bw2, barH);
            ctx.strokeStyle = U.rgba(st.text, 0.18);
            ctx.lineWidth = 1;
            ctx.strokeRect(cx - bw2 / 2 + 0.5, barTop + 0.5, Math.max(1, bw2 - 1), Math.max(1, barH - 1));
            // top cap line keeps small bars visible on the dark plot area
            ctx.fillStyle = levelGradient
                ? (ramp ? U.rampColor(ramp, U.clamp((v - ymin) / (ymax - ymin), 0, 1))
                        : U.paletteColor("viridis", U.clamp((v - ymin) / (ymax - ymin), 0, 1)))
                : U.rgba(color, 0.9);
            ctx.fillRect(cx - bw2 / 2, barTop, bw2, 1);

            // value label above the bar (tabular figures, no overlap)
            var vlabel = U.fmtValue(v, valueFormat);
            ctx.font = U.fontSpec(st.fsSmall, st.mono);
            var vw = ctx.measureText(vlabel).width;
            if (showValueLabels && vw < bw2 + 8 && cx - vw / 2 > lastValueRight + 8) {
                ctx.fillStyle = st.text;
                ctx.textAlign = "center";
                ctx.textBaseline = "alphabetic";
                var ly = Math.max(pr.y + st.fsSmall + 4, barTop - 4);
                ctx.fillText(vlabel, cx, ly);
                lastValueRight = cx + vw / 2;
            }
        }

        ctx.restore();
        // ---- limit line + reference values (over the bars)
        drawValueLine(ctx, pr, limitLine, baseY, yPix, st.error, true);
        if (referenceValues && referenceValues.length) {
            for (var rv = 0; rv < referenceValues.length; rv++) {
                drawValueLine(ctx, pr, referenceValues[rv], baseY, yPix,
                    typeof referenceValues[rv].color === "string" && referenceValues[rv].color.length
                        ? referenceValues[rv].color : st.info, false);
            }
        }

        // ---- shared level colour bar (same ramp + scale as the bars)
        if (colorScale) {
            var cs = colorScale;
            if (U.isValidRamp(bandRamp) && !(cs.stops && cs.stops.length >= 2)) {
                cs = { min: cs.min, max: cs.max, label: cs.label, unit: cs.unit, stops: bandRamp, locked: cs.locked };
            }
            U.drawColorBar(ctx, st, cs, pr.x + pr.w + 14, pr.y, mr - 22, pr.h, true);
        }

        // ---- x labels (log-frequency mode uses the generated frequency ticks
        // only; drawing band labels on top of them would collide)
        ctx.font = U.fontSpec(st.fs, st.font);
        ctx.fillStyle = st.dim;
        if (logCenters) {
            // handled below by the log-frequency tick block
        } else if (rotated) {
            for (var rl = 0; rl < cats.length; rl++) {
                var rlab = String(cats[rl].label === undefined ? "" : cats[rl].label);
                ctx.save();
                ctx.translate(centers[rl], pr.y + pr.h + 10);
                ctx.rotate(-Math.PI / 6);
                ctx.textAlign = "right";
                ctx.textBaseline = "middle";
                ctx.fillText(U.ellipsize(ctx, rlab, 62), 0, 0);
                ctx.restore();
            }
        } else {
            for (var cl = 0; cl < cats.length; cl++) {
                var clab = String(cats[cl].label === undefined ? "" : cats[cl].label);
                ctx.textAlign = "center";
                ctx.textBaseline = "top";
                ctx.fillText(U.ellipsize(ctx, clab, bandW - 6), centers[cl], pr.y + pr.h + 8);
            }
        }

        // log frequency axis ticks for centerFrequency mode
        if (logCenters) {
            var xt = U.logTicks(cfLo, cfHi, Math.max(2, Math.floor(pr.w / 95)));
            ctx.font = U.fontSpec(st.fs, st.mono);
            ctx.fillStyle = st.dim;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            var lastRight2 = -1e9;
            for (var xi = 0; xi < xt.ticks.length; xi++) {
                var xv2 = xt.ticks[xi];
                if (xv2 < cfLo * (1 - 1e-9) || xv2 > cfHi * (1 + 1e-9)) continue;
                var xx = cfX(xv2);
                var xw = ctx.measureText(U.fmtTick(xv2, 0)).width;
                if (xx - xw / 2 < lastRight2 + 8) continue;
                ctx.fillText(U.fmtTick(xv2, 0), xx, pr.y + pr.h + 8);
                lastRight2 = xx + xw / 2;
            }
        }

        // ---- axis captions + frame
        U.drawFrame(ctx, st, pr.x, pr.y, pr.w, pr.h);
        var yCaption = axis.label;
        if (axis.unit.length) yCaption = yCaption.length ? yCaption + " (" + axis.unit + ")" : axis.unit;
        if (yCaption.length) {
            ctx.font = U.fontSpec(st.fsSmall, st.font);
            ctx.fillStyle = st.dim;
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            ctx.fillText(U.ellipsize(ctx, yCaption, pr.w), pr.x, header / 2);
        }
        var xCaption = xLabel;
        if (xUnit.length) xCaption = xCaption.length ? xCaption + " (" + xUnit + ")" : xUnit;
        if (xCaption.length) {
            ctx.font = U.fontSpec(st.fsSmall, st.font);
            ctx.fillStyle = st.dim;
            ctx.textAlign = "center";
            ctx.textBaseline = "alphabetic";
            ctx.fillText(U.ellipsize(ctx, xCaption, pr.w - 40), pr.x + pr.w / 2, pr.y + pr.h + mb - 6);
        }
        if (clipped > 0) {
            var hint = "\u2264 0 \u00d7 " + clipped;
            ctx.font = U.fontSpec(st.fsSmall, st.mono);
            var hw2 = ctx.measureText(hint).width;
            ctx.fillStyle = U.rgba(st.warn, 0.16);
            ctx.fillRect(pr.x + pr.w - hw2 - 12, pr.y + 6, hw2 + 10, 16);
            ctx.fillStyle = st.warn;
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            ctx.fillText(hint, pr.x + pr.w - 7, pr.y + 14);
        }
        ctx.restore();
    }

    function drawValueLine(ctx, pr, ref, baseY, yPix, fallbackColor, isLimit) {
        if (!ref || !U.isNum(ref.value)) return;
        var value = ref.value;
        var yy = yPix(value);
        if (!isFinite(yy) || yy < pr.y - 1 || yy > pr.y + pr.h + 1) return;
        var color = typeof ref.color === "string" && ref.color.length ? ref.color : fallbackColor;
        ctx.save();
        ctx.strokeStyle = color;
        ctx.lineWidth = isLimit ? 1.4 : 1;
        ctx.setLineDash(isLimit ? [6, 4] : [3, 5]);
        ctx.beginPath();
        ctx.moveTo(pr.x, yy + 0.5);
        ctx.lineTo(pr.x + pr.w, yy + 0.5);
        ctx.stroke();
        ctx.restore();
        var label = typeof ref.label === "string" ? ref.label : "";
        if (!label.length) return;
        ctx.font = U.fontSpec(st.fsSmall, st.mono);
        var tw3 = ctx.measureText(label).width;
        ctx.fillStyle = U.rgba(st.bg, 0.85);
        ctx.fillRect(pr.x + pr.w - tw3 - 10, yy - 8, tw3 + 8, 15);
        ctx.fillStyle = color;
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        ctx.fillText(label, pr.x + pr.w - 6, yy);
    }

    Canvas {
        id: canvas
        smooth:false
        anchors.fill: parent
        onPaint: root.paintChart(getContext("2d"))
        onAvailableChanged: if (available) root.requestPaint()
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        hoverEnabled: true
        onPositionChanged: function (ev) {
            root.hoverInfo = root.hoverTextAt(ev.x)
            root.hoverX = ev.x
            root.hoverY = ev.y
        }
        onExited: root.hoverInfo = ""
    }
}
