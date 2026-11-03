// HeatmapChart - STFT / waterfall 2D heat map. Implements
// CHART_DATA_CONTRACT.md section 4.
//
// The heat surface comes from the Python QQuickImageProvider through imageUrl
// (image://plots/<kind>/<revision>): one image blit covers the whole plot area
// on every live update. This component only displays it: it maps the image
// exactly onto the axis rectangle, draws axes with 1/2/5 ticks and a readable
// colour bar from colorScale, and never computes acoustic values.
// The numeric raster is a fallback: it is used only when no image is available
// (e.g. a payload without an image provider entry) and is then drawn
// cell-by-cell inside the Canvas. An absent surface is an explicit empty state
// (no synthetic raster, no default rainbow: sequential data must use
// viridis/cividis, differences may use the zero-centred diverging map).
import QtQuick
import QtQuick.Window
import "ChartUtil.js" as U

Item {
    id: root

    // ---------------------------------------------------------- contract inputs
    property string imageUrl: ""
    // Fallback numeric raster {matrix, min, max, palette}, used only when no
    // image is available; it is then drawn cell-by-cell inside the Canvas.
    // A live source (e.g. STFT) may ship a deliberately small sampling matrix
    // here while the image carries the full display surface.
    property var raster: null
    property var xAxis: null
    property var yAxis: null
    property var colorScale: null
    property var cursor: null        // {x:real,y:real}
    property bool interactive: true
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""

    // -------------------------------------------------- additive (optional) API
    property int dataRevision: 0
    property string busyText: ""

    // ---------------------------------------------------------- contract signals
    signal pointClicked(real x, real y)

    // ---------------------------------------------------------- theme / style
    readonly property real dpr: Screen.devicePixelRatio
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

    readonly property real marginLeft: 66
    readonly property real marginRight: 84
    readonly property real headerHeight: 20
    readonly property real marginBottom: 38
    readonly property var plotArea: ({
        x: marginLeft,
        y: headerHeight,
        w: Math.max(0, width - marginLeft - marginRight),
        h: Math.max(0, height - headerHeight - marginBottom)
    })

    // effective axes (log guard applied in paint)
    property var xr: ({ min: 0, max: 1, scale: "linear" })
    property var yr: ({ min: 0, max: 1, scale: "linear" })

    // ---------------------------------------------------------- repaint plumbing
    function requestPaint() {
        if (canvas && canvas.available && visible && !paintTimer.running)paintTimer.start();
    }
    onImageUrlChanged: requestPaint()
    onRasterChanged: requestPaint()
    onXAxisChanged: requestPaint()
    onYAxisChanged: requestPaint()
    onColorScaleChanged: requestPaint()
    onCursorChanged: requestPaint()
    onDataRevisionChanged: requestPaint()
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

    // ---------------------------------------------------------- helpers
    function axisInfo(config, fallbackMin, fallbackMax) {
        var axis = U.prepareAxis(config, [], fallbackMin, fallbackMax);
        return axis;
    }

    function axisAt(axis, px, p0, plen, vertical) {
        if (axis.scale === "log") {
            if (!(axis.min > 0) || !(axis.max > axis.min)) return NaN;
            var t = vertical ? 1 - U.clamp((px - p0) / plen, 0, 1) : U.clamp((px - p0) / plen, 0, 1);
            return axis.min * Math.pow(axis.max / axis.min, t);
        }
        var t2 = vertical ? 1 - U.clamp((px - p0) / plen, 0, 1) : U.clamp((px - p0) / plen, 0, 1);
        return axis.min + t2 * (axis.max - axis.min);
    }

    function axisPix(axis, value, p0, plen, vertical) {
        if (!U.isNum(value)) return NaN;
        if (axis.scale === "log") {
            if (!(axis.min > 0) || !(axis.max > axis.min) || !(value > 0)) return NaN;
            var t = U.log10(value / axis.min) / U.log10(axis.max / axis.min);
            return vertical ? p0 + (1 - t) * plen : p0 + t * plen;
        }
        if (!(axis.max > axis.min)) return NaN;
        var t2 = (value - axis.min) / (axis.max - axis.min);
        return vertical ? p0 + (1 - t2) * plen : p0 + t2 * plen;
    }

    function axisTicks(axis, target) {
        if (axis.scale === "log") return U.logTicks(axis.min, axis.max, target);
        return U.linearTicks(axis.min, axis.max, target);
    }

    function hasImage() {
        return imageUrl.length > 0 && img.status !== Image.Error;
    }

    readonly property bool hasRaster: !!(raster && raster.matrix
        && raster.matrix.length > 0 && raster.matrix[0]
        && raster.matrix[0].length > 0)

    function hasContent() {
        return hasRaster || hasImage();
    }

    function sampleMatrix(m, fx, fy) {
        var rows = m.length;
        var cols = m[0].length;
        var cx = U.clamp(fx, 0, 1) * (cols - 1);
        var ry = U.clamp(fy, 0, 1) * (rows - 1);
        var c0 = Math.floor(cx);
        var r0 = Math.floor(ry);
        var c1 = Math.min(cols - 1, c0 + 1);
        var r1 = Math.min(rows - 1, r0 + 1);
        var tx = cx - c0;
        var ty = ry - r0;
        var v00 = m[r0][c0], v10 = m[r0][c1], v01 = m[r1][c0], v11 = m[r1][c1];
        if (!U.isNum(v00) || !U.isNum(v10) || !U.isNum(v01) || !U.isNum(v11)) {
            var nearest = m[Math.round(ry)][Math.round(cx)];
            return U.isNum(nearest) ? nearest : NaN;
        }
        return (v00 * (1 - tx) + v10 * tx) * (1 - ty)
                + (v01 * (1 - tx) + v11 * tx) * ty;
    }

    // Fallback path only (no imageUrl): bilinear resampling in *plot pixel*
    // space, cell by cell inside this Canvas. Each sample is converted through
    // the axes, so the surface stays registered with the tick grid even on a
    // logarithmic frequency axis. Cost grows with plot area (~34k cells), so a
    // live chart always prefers the image surface above.
    function drawRasterCells(ctx, pr) {
        var m = raster.matrix;
        if (!m || !m.length || !m[0].length) return;
        var cs = colorScale || ({});
        var lo = U.isNum(cs.min) ? cs.min : (U.isNum(raster.min) ? raster.min : 0);
        var hi = U.isNum(cs.max) ? cs.max : (U.isNum(raster.max) ? raster.max : 1);
        var constant = !(hi > lo);
        var span = constant ? 1 : (hi - lo);
        var palette = (typeof cs.palette === "string" && cs.palette.length)
                ? cs.palette : (raster.palette || "inferno");
        var xmin = xr.min, xmax = xr.max, ymin = yr.min, ymax = yr.max;
        var xvalid = xmax > xmin, yvalid = ymax > ymin;
        if (!xvalid || !yvalid) return;
        var step = Math.max(2, Math.ceil(pr.w / 300));
        var sx = Math.floor(pr.w / step);
        var sy = Math.floor(pr.h / step);
        var last = null;
        for (var j = 0; j < sy; j++) {
            var py = pr.y + j * step;
            var yv = axisAt(yr, py + step / 2, pr.y, pr.h, true);
            if (!isFinite(yv)) continue;
            var yd = raster.yDomain || ({min:ymin,max:ymax});
            var fy = (yv - yd.min) / (yd.max - yd.min);
            for (var i = 0; i < sx; i++) {
                var px = pr.x + i * step;
                var xv = axisAt(xr, px + step / 2, pr.x, pr.w, false);
                if (!isFinite(xv)) continue;
                var xd = raster.xDomain || ({min:xmin,max:xmax});
                var fx = (xv - xd.min) / (xd.max - xd.min);
                var v = sampleMatrix(m, fx, fy);
                if (!U.isNum(v) || !isFinite(v)) continue;
                var t = constant ? 0.5 : U.clamp((v - lo) / span, 0, 1);
                var color = U.paletteColor(palette, t);
                if (color !== last) { ctx.fillStyle = color; last = color; }
                ctx.fillRect(px, py, step + 0.75, step + 0.75);
            }
        }
    }

    // ---------------------------------------------------------- painting
    function paintChart(ctx) {
        if (!ctx) return;
        ctx.save();
        
        ctx.clearRect(0, 0, width, height);
        if (width < 4 || height < 4) { ctx.restore(); return; }

        if (busy) {
            ctx.fillStyle = st.bg;
            ctx.fillRect(0, 0, width, height);
            U.drawFrame(ctx, st, 0, 0, width, height);
            U.drawBusyState(ctx, st, width, height, busyText);
            ctx.restore();
            return;
        }
        if (!hasContent()) {
            ctx.fillStyle = st.bg;
            ctx.fillRect(0, 0, width, height);
            U.drawFrame(ctx, st, 0, 0, width, height);
            U.drawEmptyState(ctx, st, width, height, emptyText, emptyReason);
            ctx.restore();
            return;
        }

        var pr = plotArea;
        if (pr.w < 8 || pr.h < 8) { ctx.restore(); return; }
        xr = axisInfo(xAxis, 0, 1);
        yr = axisInfo(yAxis, 0, 1);

        // ---- heat surface: the image (blitted under this transparent canvas)
        // is the normal path; raster cells are the fallback only.
        if (root.hasRaster && !root.hasImage()) root.drawRasterCells(ctx, pr);

        // ---- grid aligned with the raster (drawn over the raster, subtle)
        var xt = axisTicks(xr, Math.max(2, Math.floor(pr.w / 95)));
        var yt = axisTicks(yr, Math.max(2, Math.floor(pr.h / 46)));
        ctx.lineWidth = 1;
        ctx.strokeStyle = U.rgba(st.grid, 0.35);
        for (var xi = 0; xi < xt.ticks.length; xi++) {
            var xv = xt.ticks[xi];
            var xx = axisPix(xr, xv, pr.x, pr.w, false);
            if (!isFinite(xx) || xx < pr.x || xx > pr.x + pr.w) continue;
            ctx.beginPath();
            ctx.moveTo(xx + 0.5, pr.y);
            ctx.lineTo(xx + 0.5, pr.y + pr.h);
            ctx.stroke();
            ctx.fillStyle = st.dim;
            ctx.font = U.fontSpec(st.fs, st.mono);
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            if (xx > pr.x + 12 && xx < pr.x + pr.w - 12) ctx.fillText(U.fmtTick(xv, xt.step), xx, pr.y + pr.h + 6);
        }
        for (var yi = 0; yi < yt.ticks.length; yi++) {
            var yv = yt.ticks[yi];
            var yy = axisPix(yr, yv, pr.y, pr.h, true);
            if (!isFinite(yy) || yy < pr.y || yy > pr.y + pr.h) continue;
            ctx.beginPath();
            ctx.moveTo(pr.x, yy + 0.5);
            ctx.lineTo(pr.x + pr.w, yy + 0.5);
            ctx.stroke();
            ctx.fillStyle = st.dim;
            ctx.font = U.fontSpec(st.fsSmall, st.mono);
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            ctx.fillText(U.fmtTick(yv, yt.step), pr.x - 6, yy);
        }

        // ---- frame
        U.drawFrame(ctx, st, pr.x, pr.y, pr.w, pr.h);

        // ---- axis captions
        ctx.font = U.fontSpec(st.fsSmall, st.font);
        ctx.fillStyle = st.dim;
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        var yCap = yr.label;
        if (yr.unit.length) yCap = yCap.length ? yCap + " (" + yr.unit + ")" : yr.unit;
        if (yCap.length) ctx.fillText(U.ellipsize(ctx, yCap, pr.w * 0.45), pr.x, headerHeight / 2);
        var xCap = xr.label;
        if (xr.unit.length) xCap = xCap.length ? xCap + " (" + xr.unit + ")" : xr.unit;
        if (xCap.length) {
            ctx.textAlign = "center";
            ctx.textBaseline = "alphabetic";
            ctx.fillText(U.ellipsize(ctx, xCap, pr.w - 40), pr.x + pr.w / 2, pr.y + pr.h + marginBottom - 6);
        }

        // ---- colour bar + label/unit/range
        U.drawColorBar(ctx, st, colorScale, pr.x + pr.w + 16, pr.y, 12, pr.h, true);

        // ---- cursor crosshair + readout
        if (cursor && U.isNum(cursor.x) && U.isNum(cursor.y)) {
            var cx = axisPix(xr, cursor.x, pr.x, pr.w, false);
            var cy = axisPix(yr, cursor.y, pr.y, pr.h, true);
            if (isFinite(cx) && isFinite(cy)) {
                ctx.save();
                ctx.strokeStyle = st.cursorA;
                ctx.lineWidth = 1;
                ctx.setLineDash([4, 3]);
                ctx.beginPath();
                ctx.moveTo(cx + 0.5, pr.y);
                ctx.lineTo(cx + 0.5, pr.y + pr.h);
                ctx.moveTo(pr.x, cy + 0.5);
                ctx.lineTo(pr.x + pr.w, cy + 0.5);
                ctx.stroke();
                ctx.restore();
                var readout = U.fmtTick(cursor.x, 0) + (xr.unit.length ? " " + xr.unit : "")
                    + "  " + U.fmtTick(cursor.y, 0) + (yr.unit.length ? " " + yr.unit : "");
                ctx.font = U.fontSpec(st.fsSmall, st.mono);
                var rw = ctx.measureText(readout).width;
                ctx.fillStyle = U.rgba(st.bg, 0.82);
                ctx.fillRect(pr.x + pr.w - rw - 12, pr.y + 6, rw + 10, 16);
                ctx.fillStyle = st.cursorA;
                ctx.textAlign = "right";
                ctx.textBaseline = "middle";
                ctx.fillText(readout, pr.x + pr.w - 7, pr.y + 14);
            }
        }

        ctx.restore();
    }

    Rectangle {
        anchors.fill: parent
        color: root.st.bg
        z: -1
    }

    Image {
        id: img
        source: root.imageUrl
        x: root.plotArea.x
        y: root.plotArea.y
        width: root.plotArea.w
        height: root.plotArea.h
        // Show the image whenever one is available: the raster fallback is only
        // painted when the image is absent or failed to load.
        visible: root.imageUrl.length > 0 && root.plotArea.w > 0 && root.plotArea.h > 0
                 && img.status !== Image.Error
        fillMode: Image.Stretch
        smooth: true
        cache: false
        asynchronous: true
        onStatusChanged: root.requestPaint()
    }

    Timer {id:paintTimer;interval:16;onTriggered:if(canvas.available&&root.visible)canvas.requestPaint()}
    Canvas {
        id: canvas
        smooth:false
        anchors.fill: parent
        onPaint: root.paintChart(getContext("2d"))
        onAvailableChanged: if (available) root.requestPaint()
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        hoverEnabled: false
        onPositionChanged:function(ev){if(pressed&&root.cursor)reportPoint(ev);}
        onClicked:function(ev){reportPoint(ev);}
        function reportPoint(ev) {
            if (!root.interactive || root.busy || !root.hasContent()) return;
            var pr = root.plotArea;
            if (ev.x < pr.x || ev.x > pr.x + pr.w || ev.y < pr.y || ev.y > pr.y + pr.h) return;
            var xv = root.axisAt(root.xr, ev.x, pr.x, pr.w, false);
            var yv = root.axisAt(root.yr, ev.y, pr.y, pr.h, true);
            if (isFinite(xv) && isFinite(yv)) root.pointClicked(xv, yv);
        }
    }
}
