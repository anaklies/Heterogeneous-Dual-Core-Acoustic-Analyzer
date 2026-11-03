// PolarChart - directional power / DAS azimuth x elevation heat map.
// Implements CHART_DATA_CONTRACT.md section 5. This is NOT a localisation or
// source-separation display: the page is required to pass an explanatory caption.
//
// The raster comes from the Python QQuickImageProvider. For projection "polar"
// the provider is expected to draw the directional pattern as a square polar
// raster (azimuth 0 at the top, clockwise, elevation increasing outward); this
// component draws the matching ring/spoke frame and a readable colour bar.
// projection "rect" maps the raster linearly onto azimuth (x) / elevation (y).
import QtQuick
import QtQuick.Window
import "ChartUtil.js" as U

Item {
    id: root
    property var cursor:null
    signal pointClicked(real x,real y)
    onCursorChanged:requestPaint()

    // ---------------------------------------------------------- contract inputs
    property string imageUrl: ""
    // Numeric raster {matrix, azimuths, elevations, min, max, palette}.  The
    // power map is drawn cell-by-cell in THIS canvas together with the polar /
    // rectangular frame and labels (one real-time rendering, no pasted texture).
    property var raster: null
    property var azimuthRange: null    // {min,max} degrees
    property var elevationRange: null  // {min,max} degrees
    property var colorScale: null
    property string caption: ""
    property string projection: "polar"
    property bool interactive: true
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""

    // -------------------------------------------------- additive (optional) API
    property int dataRevision: 0
    property string busyText: ""
    // Auxiliary peaks supplied by the data source: [{x: azimuthDeg, y: elevationDeg,
    // label, kind}]. Display-only annotation; no peak search happens here.
    property var markers: []

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
        fs: Math.max(12, Math.round(13 * Theme.fontScale)),
        fsSmall: Math.max(13, Math.round(14 * Theme.fontScale))
    })

    readonly property real marginLeft: 30
    readonly property real marginRight: 126
    readonly property real headerHeight: 18
    readonly property real marginBottom: 40
    readonly property var plotArea: ({
        x: marginLeft,
        y: headerHeight,
        w: Math.max(0, width - marginLeft - marginRight),
        h: Math.max(0, height - headerHeight - marginBottom)
    })

    readonly property real polarSide: Math.max(0, Math.min(plotArea.w, plotArea.h))
    readonly property real polarCx: plotArea.x + plotArea.w / 2
    readonly property real polarCy: plotArea.y + plotArea.h / 2
    readonly property real polarR: Math.max(0, polarSide / 2 - 18)
    readonly property bool isRect: projection === "rect"
    readonly property var imageRect: isRect
        ? ({ x: plotArea.x, y: plotArea.y, w: plotArea.w, h: plotArea.h })
        : ({ x: polarCx - polarR, y: polarCy - polarR, w: polarR * 2, h: polarR * 2 })

    // ---------------------------------------------------------- repaint plumbing
    function requestPaint() {
        if (canvas && canvas.available && visible) canvas.requestPaint();
    }
    onImageUrlChanged: requestPaint()
    onRasterChanged: requestPaint()
    onAzimuthRangeChanged: requestPaint()
    onElevationRangeChanged: requestPaint()
    onColorScaleChanged: requestPaint()
    onCaptionChanged: requestPaint()
    onProjectionChanged: requestPaint()
    onMarkersChanged: requestPaint()
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
    function hasImage() {
        return imageUrl.length > 0 && img.status !== Image.Error;
    }

    readonly property bool hasRaster: !!(raster && raster.matrix
        && raster.matrix.length > 0 && raster.matrix[0]
        && raster.matrix[0].length > 0)

    function hasContent() {
        return hasRaster || hasImage();
    }

    function rasterColor(value, lo, hi, palette) {
        var span = hi - lo;
        if (!(span > 0)) return U.paletteColor(palette, 0.5);
        return U.paletteColor(palette, U.clamp((value - lo) / span, 0, 1));
    }

    function cellBounds(values, fallbackMin, fallbackMax) {
        var n = values.length;
        if (n === 0) return { lo: [], hi: [] };
        var lo = [], hi = [];
        if (n === 1) { lo.push(fallbackMin); hi.push(fallbackMax); return { lo: lo, hi: hi }; }
        var step = (values[n - 1] - values[0]) / (n - 1);
        if (!(step > 0)) step = (fallbackMax - fallbackMin) / n;
        for (var i = 0; i < n; i++) {
            lo.push(i === 0 ? Math.min(values[0] - step / 2, fallbackMin)
                            : values[i] - step / 2);
            hi.push(i === n - 1 ? Math.max(values[n - 1] + step / 2, fallbackMax)
                               : values[i] + step / 2);
        }
        return { lo: lo, hi: hi };
    }

    // Power map painted as filled cells inside THIS Canvas, then the frame/grid
    // is drawn on top in paintChart().  Polar mode uses annular sectors so the
    // colour surface and the degree rings/radial spokes share one geometry.
    function paintRaster(ctx, az, el) {
        var m = raster.matrix;
        var rows = m.length;
        var cols = m[0].length;
        if (!(rows > 0 && cols > 0)) return;
        var cs = colorScale || ({});
        var lo = U.isNum(cs.min) ? cs.min : (U.isNum(raster.min) ? raster.min : 0);
        var hi = U.isNum(cs.max) ? cs.max : (U.isNum(raster.max) ? raster.max : 1);
        var palette = (typeof cs.palette === "string" && cs.palette.length)
                ? cs.palette : (raster.palette || "viridis");
        var azs = raster.azimuths || [];
        var els = raster.elevations || [];
        var azB = cellBounds(azs, az.min, az.max);
        var elB = cellBounds(els, el.min, el.max);
        var pr = plotArea;
        if (isRect) {
            ctx.save(); ctx.beginPath(); ctx.rect(pr.x,pr.y,pr.w,pr.h);ctx.clip();
            for (var r = 0; r < rows; r++) {
                var y1 = pr.y + (1 - (elB.hi[r] - el.min) / Math.max(1e-9, el.max - el.min)) * pr.h;
                var y0 = pr.y + (1 - (elB.lo[r] - el.min) / Math.max(1e-9, el.max - el.min)) * pr.h;
                for (var c = 0; c < cols; c++) {
                    var x0 = pr.x + (azB.lo[c] - az.min) / Math.max(1e-9, az.max - az.min) * pr.w;
                    var x1 = pr.x + (azB.hi[c] - az.min) / Math.max(1e-9, az.max - az.min) * pr.w;
                    var value = m[r][c];
                    if (!U.isNum(value) || !isFinite(value)) continue;
                    ctx.fillStyle = rasterColor(value, lo, hi, palette);
                    ctx.fillRect(x0, Math.min(y0,y1), Math.max(1, x1 - x0) + 0.6, Math.max(1, Math.abs(y1-y0)) + 0.6);
                }
            }
            ctx.restore();
            return;
        }
        var cx = polarCx, cy = polarCy, radius = polarR;
        if (!(radius > 8)) return;
        for (var rr = 0; rr < rows; rr++) {
            var r0 = U.clamp((elB.lo[rr] - el.min) / Math.max(1e-9, el.max - el.min), 0, 1) * radius;
            var r1 = U.clamp((elB.hi[rr] - el.min) / Math.max(1e-9, el.max - el.min), 0, 1) * radius;
            if (r1 - r0 < 0.8) r1 = r0 + 0.8;
            for (var cc = 0; cc < cols; cc++) {
                var val = m[rr][cc];
                if (!U.isNum(val) || !isFinite(val)) continue;
                var a0 = (azB.lo[cc] - 90) * Math.PI / 180;
                var a1 = (azB.hi[cc] - 90) * Math.PI / 180;
                if (a1 - a0 < 0.002) a1 = a0 + 0.002;
                ctx.fillStyle = rasterColor(val, lo, hi, palette);
                ctx.strokeStyle = ctx.fillStyle;
                ctx.lineWidth = 0.7;
                ctx.beginPath();
                if (r0 <= 0.2) {
                    ctx.moveTo(cx, cy);
                    ctx.lineTo(cx + Math.cos(a0) * r1, cy + Math.sin(a0) * r1);
                    ctx.arc(cx, cy, r1, a0, a1, false);
                    ctx.closePath();
                } else {
                    ctx.arc(cx, cy, r1, a0, a1, false);
                    ctx.arc(cx, cy, r0, a1, a0, true);
                    ctx.closePath();
                }
                ctx.fill();
                ctx.stroke();
            }
        }
    }

    function rangeOf(r, fallbackMin, fallbackMax) {
        if (r && U.isNum(r.min) && U.isNum(r.max) && r.max > r.min) {
            return { min: r.min, max: r.max };
        }
        return { min: fallbackMin, max: fallbackMax };
    }

    function ticksFor(r, target, scale) {
        if (scale === "log") return U.logTicks(Math.max(1e-9, r.min), r.max, target);
        return U.linearTicks(r.min, r.max, target);
    }

    function drawDegreeLabel(ctx, text, x, y, align, baseline) {
        ctx.font = U.fontSpec(st.fsSmall, st.mono);
        ctx.fillStyle = st.dim;
        ctx.textAlign = align;
        ctx.textBaseline = baseline;
        ctx.fillText(text, x, y);
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

        var az = rangeOf(azimuthRange, 0, 360);
        var el = rangeOf(elevationRange, 0, 90);
        var pr = plotArea;
        if (pr.w < 8 || pr.h < 8) { ctx.restore(); return; }

        // Power raster first (same canvas), then frame/grid/labels on top so the
        // coordinates and the map can never drift apart.
        if (root.hasRaster) root.paintRaster(ctx, az, el);

        if (isRect) {
            paintRectProjection(ctx, pr, az, el);
        } else {
            paintPolarProjection(ctx, az, el);
        }

        if(cursor&&isRect&&U.isNum(cursor.x)&&U.isNum(cursor.y)) {
            var cx=pr.x+(cursor.x-az.min)/(az.max-az.min)*pr.w,cy=pr.y+(el.max-cursor.y)/(el.max-el.min)*pr.h;
            ctx.strokeStyle=Theme.plotCursorA;ctx.lineWidth=1;ctx.setLineDash([4,3]);ctx.beginPath();ctx.moveTo(cx,pr.y);ctx.lineTo(cx,pr.y+pr.h);ctx.moveTo(pr.x,cy);ctx.lineTo(pr.x+pr.w,cy);ctx.stroke();ctx.setLineDash([]);
            ctx.fillStyle=Theme.plotCursorA;ctx.font=U.fontSpec(14,st.font);ctx.fillText((typeof App!=="undefined"?App.t("instrument.azimuth"):"Azimuth")+" "+cursor.x.toFixed(1)+"° / "+(typeof App!=="undefined"?App.t("instrument.elevation"):"Elevation")+" "+cursor.y.toFixed(1)+"°",pr.x+8,pr.y+20);
        }
        // ---- auxiliary peak markers (supplied azimuth/elevation, display only)
        if (markers && markers.length) {
            var prm = plotArea;
            var elM = rangeOf(elevationRange, 0, 90);
            var azM = rangeOf(azimuthRange, 0, 360);
            var rectM = isRect;
            var cxM = polarCx;
            var cyM = polarCy;
            var rM = polarR;
            U.drawMarkers(ctx, st, markers, null, null, {
                rect: prm,
                color: st.cursorA,
                project: function (m) {
                    if (rectM) {
                        if (!(azM.max > azM.min) || !(elM.max > elM.min)) return null;
                        return {
                            x: prm.x + ((m.x - azM.min) / (azM.max - azM.min)) * prm.w,
                            y: prm.y + (1 - (m.y - elM.min) / (elM.max - elM.min)) * prm.h
                        };
                    }
                    if (!(elM.max > elM.min)) return null;
                    var ang = (m.x - 90) * Math.PI / 180;
                    var frac = U.clamp((m.y - elM.min) / (elM.max - elM.min), 0, 1);
                    return { x: cxM + Math.cos(ang) * rM * frac, y: cyM + Math.sin(ang) * rM * frac };
                }
            });
        }

        // ---- colour bar
        U.drawColorBar(ctx, st, colorScale, pr.x + pr.w + 14, pr.y, marginRight - 22, pr.h, true);

        // ---- caption (page supplied explanation, mandatory for directional power)
        if (caption.length) {
            ctx.font = U.fontSpec(st.fsSmall, st.font);
            ctx.fillStyle = st.dim;
            ctx.textAlign = "center";
            ctx.textBaseline = "alphabetic";
            ctx.fillText(U.ellipsize(ctx, caption, width - 24), width / 2, height - 8);
        }
        ctx.restore();
    }

    function paintPolarProjection(ctx, az, el) {
        var cx = polarCx;
        var cy = polarCy;
        var r = polarR;
        if (!(r > 8)) return;

        // elevation rings (outward = increasing elevation); dense enough to be
        // readable without collapsing into two rings
        var step = (el.max - el.min);
        var ringTarget = U.clamp(Math.round(step / 18), 3, 5);
        var rings = U.linearTicks(el.min, el.max, ringTarget).ticks;
        ctx.lineWidth = 1;
        for (var i = 0; i < rings.length; i++) {
            var ev = rings[i];
            if (ev < el.min - 1e-9 || ev > el.max + 1e-9) continue;
            var frac = step > 0 ? (ev - el.min) / step : 0;
            var rr = r * U.clamp(frac, 0, 1);
            if (rr < 2) continue;
            ctx.strokeStyle = U.rgba(st.grid, 0.28);
            ctx.beginPath();
            ctx.arc(cx, cy, rr, 0, Math.PI * 2);
            ctx.stroke();
            if (rr > 14) {
                var lx = cx + 4;
                drawDegreeLabel(ctx, U.fmtTick(ev, 0) + "\u00b0", lx, cy - rr, "left", "middle");
            }
        }

        // azimuth spokes (0 at top, clockwise). A full compass uses the
        // conventional 30 degree grid; smaller arcs use 1/2/5 ticks inside range.
        var azSpan = az.max - az.min;
        if (azSpan > 0) {
            var use = [];
            if (azSpan >= 300) {
                var start = Math.ceil(az.min / 30) * 30;
                for (var a = start; a <= az.max + 1e-6; a += 30) {
                    if (a >= az.min - 1e-6 && a <= az.max + 1e-6) use.push(a);
                }
            } else {
                var cand = U.linearTicks(az.min, az.max, Math.max(4, Math.floor(azSpan / 30))).ticks;
                for (var c = 0; c < cand.length; c++) {
                    if (cand[c] >= az.min - 1e-9 && cand[c] <= az.max + 1e-9) use.push(cand[c]);
                }
                if (use.length < 2) use = [az.min, az.max];
            }
            for (var s = 0; s < use.length; s++) {
                var av = use[s];
                if (azSpan >= 359.99 && Math.abs(av - az.max) < 1e-6) continue;
                var ang = (av - 90) * Math.PI / 180;
                ctx.strokeStyle = U.rgba(st.grid, 0.42);
                ctx.beginPath();
                ctx.moveTo(cx, cy);
                ctx.lineTo(cx + Math.cos(ang) * r, cy + Math.sin(ang) * r);
                ctx.stroke();
                var lx2 = cx + Math.cos(ang) * (r + 13);
                var ly2 = cy + Math.sin(ang) * (r + 13);
                var align = Math.abs(Math.cos(ang)) < 0.25 ? "center" : (Math.cos(ang) > 0 ? "left" : "right");
                var baseline = Math.abs(Math.sin(ang)) < 0.25 ? "middle" : (Math.sin(ang) > 0 ? "top" : "bottom");
                drawDegreeLabel(ctx, U.fmtTick(av, 0) + "\u00b0", lx2, ly2, align, baseline);
            }
        }

        // outer circle + centre mark
        ctx.strokeStyle = st.grid;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();
        ctx.strokeStyle = U.rgba(st.dim, 0.5);
        ctx.beginPath();
        ctx.moveTo(cx - 3, cy);
        ctx.lineTo(cx + 3, cy);
        ctx.moveTo(cx, cy - 3);
        ctx.lineTo(cx, cy + 3);
        ctx.stroke();
    }

    function paintRectProjection(ctx, pr, az, el) {
        var xt = ticksFor(az, Math.max(2, Math.floor(pr.w / 95)), "linear");
        var yt = ticksFor(el, Math.max(2, Math.floor(pr.h / 46)), "linear");
        ctx.lineWidth = 1;
        ctx.strokeStyle = U.rgba(st.grid, 0.35);
        for (var i = 0; i < xt.ticks.length; i++) {
            var xv = xt.ticks[i];
            if (xv < az.min - 1e-9 || xv > az.max + 1e-9) continue;
            var xx = pr.x + ((xv - az.min) / (az.max - az.min)) * pr.w;
            ctx.beginPath();
            ctx.moveTo(xx + 0.5, pr.y);
            ctx.lineTo(xx + 0.5, pr.y + pr.h);
            ctx.stroke();
            ctx.fillStyle = st.dim;
            ctx.font = U.fontSpec(st.fs, st.mono);
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            if (xx > pr.x + 14 && xx < pr.x + pr.w - 14) {
                ctx.fillText(U.fmtTick(xv, xt.step) + "\u00b0", xx, pr.y + pr.h + 6);
            }
        }
        for (var j = 0; j < yt.ticks.length; j++) {
            var yv = yt.ticks[j];
            if (yv < el.min - 1e-9 || yv > el.max + 1e-9) continue;
            var yy = pr.y + (1 - (yv - el.min) / (el.max - el.min)) * pr.h;
            ctx.beginPath();
            ctx.moveTo(pr.x, yy + 0.5);
            ctx.lineTo(pr.x + pr.w, yy + 0.5);
            ctx.stroke();
            ctx.fillStyle = st.dim;
            ctx.font = U.fontSpec(st.fsSmall, st.mono);
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            ctx.fillText(U.fmtTick(yv, yt.step) + "\u00b0", pr.x - 6, yy);
        }
        U.drawFrame(ctx, st, pr.x, pr.y, pr.w, pr.h);
    }

    Rectangle {
        anchors.fill: parent
        color: root.st.bg
        z: -1
    }

    Image {
        id: img
        source: root.imageUrl
        x: root.imageRect.x
        y: root.imageRect.y
        width: root.imageRect.w
        height: root.imageRect.h
        visible: root.imageUrl.length > 0 && root.imageRect.w > 0 && root.imageRect.h > 0
                 && !root.hasRaster
        fillMode: Image.Stretch
        smooth: true
        cache: false
        asynchronous: true
        onStatusChanged: root.requestPaint()
    }

    Canvas {
        id: canvas
        smooth:false
        anchors.fill: parent
        onPaint: root.paintChart(getContext("2d"))
        onAvailableChanged: if (available) root.requestPaint()
    }
    MouseArea {
        anchors.fill:parent;acceptedButtons:Qt.LeftButton
        onClicked:function(ev){var p=root.plotArea;if(!root.isRect||!root.cursor||ev.x<p.x||ev.x>p.x+p.w||ev.y<p.y||ev.y>p.y+p.h)return;var az=root.rangeOf(root.azimuthRange,0,360),el=root.rangeOf(root.elevationRange,-90,90);root.pointClicked(az.min+(ev.x-p.x)/p.w*(az.max-az.min),el.max-(ev.y-p.y)/p.h*(el.max-el.min));}
    }

}
