// LevelMeter - six channel level bars (peak meter), vertical or horizontal.
// Implements CHART_DATA_CONTRACT.md section 6.
//
// Relative dBFS display: the scale comes from the page (never hardcoded). An
// invalid meter is never painted as 0 dBFS: the bar stays empty and the value
// reads the dash placeholder. Clipping is shown with both a shape and the
// optional page-supplied clipText (localisation lives in the page).
import QtQuick
import QtQuick.Window
import "ChartUtil.js" as U

Item {
    id: root

    // ---------------------------------------------------------- contract inputs
    property var meters: []       // [{label,color,value,peak,valid,clip}]
    property var scale: null      // {min,max,label,unit}
    property string orientation: "vertical" // "vertical" | "horizontal"
    property bool interactive: true
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""

    // -------------------------------------------------- additive (optional) API
    property int dataRevision: 0
    property string busyText: ""
    property string clipText: ""
    property string valueFormat: "%.1f"

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
        fs: Math.max(12, Math.round(13 * Theme.fontScale)),
        fsSmall: Math.max(13, Math.round(14 * Theme.fontScale))
    })

    // ---------------------------------------------------------- repaint plumbing
    function requestPaint() {
        if (canvas && canvas.available && visible) canvas.requestPaint();
    }
    onMetersChanged: requestPaint()
    onScaleChanged: requestPaint()
    onOrientationChanged: requestPaint()
    onDataRevisionChanged: requestPaint()
    onBusyChanged: requestPaint()
    onEmptyTextChanged: requestPaint()
    onEmptyReasonChanged: requestPaint()
    onClipTextChanged: requestPaint()
    onValueFormatChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onDprChanged: requestPaint()
    onVisibleChanged: if (visible) requestPaint()
    Connections {
        target: Theme
        function onChanged() { root.requestPaint(); }
    }

    // ---------------------------------------------------------- helpers
    function validMeters() {
        var out = [];
        var list = meters;
        if (!list || !list.length) return out;
        for (var i = 0; i < list.length; i++) if (list[i]) out.push(list[i]);
        return out;
    }

    function scaleInfo() {
        var s = scale && typeof scale === "object" ? scale : {};
        var mn = U.isNum(s.min) ? s.min : -60;
        var mx = U.isNum(s.max) ? s.max : 0;
        if (!(mx > mn)) { mn = -60; mx = 0; }
        return {
            min: mn,
            max: mx,
            label: typeof s.label === "string" ? s.label : "",
            unit: typeof s.unit === "string" ? s.unit : ""
        };
    }

    function valueText(v) {
        if (!U.isNum(v)) return "\u2014";
        return U.fmtValue(v, valueFormat);
    }

    function fraction(v, sc) {
        if (!U.isNum(v)) return NaN;
        return U.clamp((v - sc.min) / (sc.max - sc.min), 0, 1);
    }

    function meterColor(m, index) {
        if (m && typeof m.color === "string" && m.color.length) return m.color;
        return channelPalette[index % channelPalette.length];
    }

    function isValid(m) {
        return m && m.valid !== false && U.isNum(m.value);
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
        var list = validMeters();
        if (!list.length) {
            U.drawEmptyState(ctx, st, width, height, emptyText, emptyReason);
            ctx.restore();
            return;
        }
        var sc = scaleInfo();
        if (orientation === "horizontal") paintHorizontal(ctx, list, sc);
        else paintVertical(ctx, list, sc);
        ctx.restore();
    }

    function paintVertical(ctx, list, sc) {
        var header = 20;
        var ml = 46;
        var mr = 10;
        var bottom = 38;
        var pr = {
            x: ml,
            y: header,
            w: Math.max(8, width - ml - mr),
            h: Math.max(8, height - header - bottom)
        };

        // scale caption (top left)
        var caption = sc.label;
        if (sc.unit.length) caption = caption.length ? caption + " (" + sc.unit + ")" : sc.unit;
        if (caption.length) {
            ctx.font = U.fontSpec(st.fsSmall, st.font);
            ctx.fillStyle = st.dim;
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            ctx.fillText(U.ellipsize(ctx, caption, pr.w * 0.5), 8, header / 2);
        }

        // scale ticks (1/2/5) shared by all columns
        var stp = U.linearTicks(sc.min, sc.max, Math.max(3, Math.floor(pr.h / 40)));
        ctx.lineWidth = 1;
        for (var i = 0; i < stp.ticks.length; i++) {
            var tv = stp.ticks[i];
            if (tv < sc.min - 1e-9 || tv > sc.max + 1e-9) continue;
            var yy = pr.y + (1 - fraction(tv, sc)) * pr.h;
            ctx.strokeStyle = Math.abs(tv) < 1e-12 ? st.grid : st.minor;
            ctx.beginPath();
            ctx.moveTo(pr.x, yy + 0.5);
            ctx.lineTo(pr.x + pr.w, yy + 0.5);
            ctx.stroke();
            ctx.fillStyle = st.dim;
            ctx.font = U.fontSpec(st.fsSmall, st.mono);
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            ctx.fillText(U.fmtTick(tv, stp.step), pr.x - 6, yy);
        }

        var n = list.length;
        var colW = pr.w / n;
        var trackW = U.clamp(colW * 0.5, 6, 30);
        for (var m = 0; m < n; m++) {
            var meter = list[m];
            var color = meterColor(meter, m);
            var cx = pr.x + colW * (m + 0.5);
            var tx = cx - trackW / 2;
            // track
            ctx.fillStyle = U.rgba(st.grid, 0.55);
            ctx.fillRect(tx, pr.y, trackW, pr.h);
            var valid = isValid(meter);
            var frac = valid ? fraction(meter.value, sc) : 0;
            if (valid) {
                var barH = Math.max(1, frac * pr.h);
                ctx.fillStyle = color;
                ctx.fillRect(tx, pr.y + pr.h - barH, trackW, barH);
                // peak marker
                if (U.isNum(meter.peak)) {
                    var pfrac = U.clamp((meter.peak - sc.min) / (sc.max - sc.min), 0, 1);
                    var py = pr.y + pr.h - pfrac * pr.h;
                    ctx.fillStyle = st.text;
                    ctx.fillRect(tx - 2, py - 1, trackW + 4, 2);
                }
            }
            // clip indicator (shape + optional localised text)
            if (meter.clip === true) {
                ctx.fillStyle = st.error;
                ctx.fillRect(cx - 4, pr.y + 2, 8, 8);
                if (clipText.length) {
                    ctx.font = U.fontSpec(st.fsSmall, st.font);
                    ctx.fillStyle = st.error;
                    ctx.textAlign = "center";
                    ctx.textBaseline = "top";
                    ctx.fillText(U.ellipsize(ctx, clipText, colW - 4), cx, pr.y + 12);
                }
            }
            // channel label + value
            ctx.font = U.fontSpec(st.fs, st.font);
            ctx.fillStyle = color;
            ctx.textAlign = "center";
            ctx.textBaseline = "alphabetic";
            var label = String(meter.label === undefined ? "" : meter.label);
            ctx.fillText(U.ellipsize(ctx, label, colW - 4), cx, pr.y + pr.h + 16);
            ctx.font = U.fontSpec(st.fsSmall, st.mono);
            ctx.fillStyle = valid ? st.text : st.dim;
            ctx.fillText(U.ellipsize(ctx, valueText(meter.value), colW - 4), cx, pr.y + pr.h + 32);
        }
    }

    function paintHorizontal(ctx, list, sc) {
        var header = 20;
        var ml = 66;
        var mr = 58;
        var bottom = 30;
        var pr = {
            x: ml,
            y: header,
            w: Math.max(8, width - ml - mr),
            h: Math.max(8, height - header - bottom)
        };
        var caption = sc.label;
        if (sc.unit.length) caption = caption.length ? caption + " (" + sc.unit + ")" : sc.unit;
        if (caption.length) {
            ctx.font = U.fontSpec(st.fsSmall, st.font);
            ctx.fillStyle = st.dim;
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            ctx.fillText(U.ellipsize(ctx, caption, pr.w * 0.5), 8, header / 2);
        }

        // optional localised clip legend in the header (shape + text)
        if (clipText.length) {
            var anyClip = false;
            for (var ac = 0; ac < list.length; ac++) if (list[ac].clip === true) anyClip = true;
            if (anyClip) {
                ctx.font = U.fontSpec(st.fsSmall, st.font);
                var ctw = ctx.measureText(clipText).width;
                var clx = width - ctw - 20;
                ctx.fillStyle = st.error;
                ctx.fillRect(clx, header / 2 - 4, 8, 8);
                ctx.textAlign = "left";
                ctx.textBaseline = "middle";
                ctx.fillText(clipText, clx + 12, header / 2);
            }
        }

        // scale ticks (vertical grid + labels below)
        var stp = U.linearTicks(sc.min, sc.max, Math.max(3, Math.floor(pr.w / 78)));
        ctx.lineWidth = 1;
        for (var i = 0; i < stp.ticks.length; i++) {
            var tv = stp.ticks[i];
            if (tv < sc.min - 1e-9 || tv > sc.max + 1e-9) continue;
            var xx = pr.x + fraction(tv, sc) * pr.w;
            ctx.strokeStyle = Math.abs(tv) < 1e-12 ? st.grid : st.minor;
            ctx.beginPath();
            ctx.moveTo(xx + 0.5, pr.y);
            ctx.lineTo(xx + 0.5, pr.y + pr.h);
            ctx.stroke();
            ctx.fillStyle = st.dim;
            ctx.font = U.fontSpec(st.fsSmall, st.mono);
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillText(U.fmtTick(tv, stp.step), xx, pr.y + pr.h + 8);
        }

        var n = list.length;
        var rowH = pr.h / n;
        var trackH = U.clamp(rowH * 0.4, 6, 18);
        for (var m = 0; m < n; m++) {
            var meter = list[m];
            var color = meterColor(meter, m);
            var cy = pr.y + rowH * (m + 0.5);
            var ty = cy - trackH / 2;
            ctx.fillStyle = U.rgba(st.grid, 0.55);
            ctx.fillRect(pr.x, ty, pr.w, trackH);
            var valid = isValid(meter);
            var frac = valid ? fraction(meter.value, sc) : 0;
            if (valid) {
                ctx.fillStyle = color;
                ctx.fillRect(pr.x, ty, Math.max(1, frac * pr.w), trackH);
                if (U.isNum(meter.peak)) {
                    var pfrac = U.clamp((meter.peak - sc.min) / (sc.max - sc.min), 0, 1);
                    var px = pr.x + pfrac * pr.w;
                    ctx.fillStyle = st.text;
                    ctx.fillRect(px - 1, ty - 2, 2, trackH + 4);
                }
            }
            // label (coloured channel identity)
            ctx.font = U.fontSpec(st.fs, st.font);
            ctx.fillStyle = color;
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            var label = String(meter.label === undefined ? "" : meter.label);
            ctx.fillText(U.ellipsize(ctx, label, ml - 12), pr.x - 8, cy);
            // value (tabular figures) and clip shape (text legend lives in the
            // header so it never overprints the numeric values)
            var clipW = meter.clip === true ? 14 : 8;
            if (meter.clip === true) {
                ctx.fillStyle = st.error;
                ctx.fillRect(pr.x + pr.w + 2, cy - 4, 8, 8);
            }
            ctx.font = U.fontSpec(st.fsSmall, st.mono);
            ctx.fillStyle = valid ? st.text : st.dim;
            ctx.textAlign = "left";
            ctx.fillText(valueText(meter.value), pr.x + pr.w + clipW, cy);
        }
    }

    Canvas {
        id: canvas
        smooth:false
        anchors.fill: parent
        onPaint: root.paintChart(getContext("2d"))
        onAvailableChanged: if (available) root.requestPaint()
    }
}
