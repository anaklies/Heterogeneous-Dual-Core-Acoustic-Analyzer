// LineChart - generic line chart for FFT / PSD / coherence / phase / decay /
// correlation etc. Implements CHART_DATA_CONTRACT.md section 2.
//
// Display-only plotting of [[x,y],...] points supplied by the page. Linear and
// log axes are supported; log axes clip values <= 0 (they are never drawn and a
// dim warning badge reports how many were clipped). 0 Hz therefore never enters
// a log axis. A/B cursors are draggable and snap to real series data points.
import QtQuick
import QtQuick.Window
import "ChartUtil.js" as U

Item {
    id: root
    property bool inspectionEnabled: false

    // ---------------------------------------------------------- contract inputs
    property var series: []            // [{name,color,points:[[x,y],...],width,dashed,fill,...}]
    property var xAxis: null           // {min,max,scale,label,unit,ticks?}
    property var yAxis: null
    property var cursorAX: null
    property var cursorBX: null
    property var referenceLines: []
    property var referenceBands: []
    property var markers: []          // additive: [{x,y,label,kind,color}] data-source annotations
    property bool showLegend: true
    property bool interactive: true
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""

    // -------------------------------------------------- additive (optional) API
    property int dataRevision: 0
    property string busyText: ""
    property string logClipText: ""
    property string cursorLabelA: "A"
    property string cursorLabelB: "B"

    // ---------------------------------------------------------- contract signals
    signal cursorChanged(real xa, real xb)
    signal pointClicked(real x, real y)

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
    property real heldYMin: NaN
    property real heldYMax: NaN
    property string heldUnit: ""
    function resetScale(){heldYMin=NaN;heldYMax=NaN;requestPaint();}
    onInspectionEnabledChanged: {
        if(inspectionEnabled){var v=visibleSeries();if(v.length){var p=v[0].points;if(p.length){dragCursorA=p[Math.floor((p.length-1)/3)][0];dragCursorB=p[Math.floor((p.length-1)*2/3)][0];}}}
        else {dragCursorA=NaN;dragCursorB=NaN;}
        requestPaint();
    }
    property real viewStart: 0
    property real viewEnd: 1
    property string dragMode: ""
    property bool dragMoved: false
    property real pressX: -1
    property real lastX: -1
    property real dragCursorA: NaN
    property real dragCursorB: NaN
    property int clippedLog: 0

    // effective domain, computed once per paint
    property var xr: ({ min: 0, max: 1, scale: "linear" })
    property var yr: ({ min: 0, max: 1, scale: "linear" })

    readonly property real marginLeft: 82
    readonly property real marginRight: 18
    readonly property real headerHeight: U.isNum(cursorAX) || U.isNum(cursorBX) || U.isNum(dragCursorA) || U.isNum(dragCursorB) ? 48 : 30
    readonly property real marginBottom: 52

    // ---------------------------------------------------------- repaint plumbing
    function requestPaint() {
        if (canvas && canvas.available && visible && !paintTimer.running) paintTimer.start();
    }
    onSeriesChanged: requestPaint()
    onXAxisChanged: requestPaint()
    onYAxisChanged: requestPaint()
    onCursorAXChanged: requestPaint()
    onCursorBXChanged: requestPaint()
    onReferenceLinesChanged: requestPaint()
    onReferenceBandsChanged: requestPaint()
    onMarkersChanged: requestPaint()
    onShowLegendChanged: requestPaint()
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

    Timer { id:paintTimer;interval:16;onTriggered:if(canvas.available&&root.visible)canvas.requestPaint() }
    // ---------------------------------------------------------- data helpers
    function visibleSeries() {
        var out = [];
        var list = series;
        if (!list || !list.length) return out;
        for (var i = 0; i < list.length; i++) {
            var s = list[i];
            if (!s || !s.points || s.points.length < 1) continue;
            if (s.visible === false) continue;
            out.push(s);
        }
        return out;
    }

    function collectValues(vis, wantX) {
        var out = [];
        for (var s = 0; s < vis.length; s++) {
            var pts = vis[s].points;
            var stride = U.sampleStride(pts.length, 4096);
            for (var i = 0; i < pts.length; i += stride) {
                var p = pts[i];
                if (!p || p.length < 2) continue;
                var v = wantX ? p[0] : p[1];
                if (U.isNum(v)) out.push(v);
            }
        }
        return out;
    }

    function plotRect() {
        return {
            x: marginLeft,
            y: headerHeight,
            w: Math.max(0, width - marginLeft - marginRight),
            h: Math.max(0, height - headerHeight - marginBottom)
        };
    }

    function normFromValue(v) {
        var minV = xr.min;
        var maxV = xr.max;
        if (xr.scale === "log") {
            if (!U.isLogValid(v) || !U.isLogValid(minV) || !U.isLogValid(maxV)) return NaN;
            return U.log10(v / minV) / U.log10(maxV / minV);
        }
        if (!U.isNum(v) || !(maxV > minV)) return NaN;
        return (v - minV) / (maxV - minV);
    }

    function valueFromNorm(t) {
        if (xr.scale === "log") {
            if (!U.isLogValid(xr.min) || !U.isLogValid(xr.max)) return NaN;
            return xr.min * Math.pow(xr.max / xr.min, t);
        }
        return xr.min + t * (xr.max - xr.min);
    }

    function screenX(v) {
        var t = normFromValue(v);
        if (!isFinite(t)) return NaN;
        var span = viewEnd - viewStart;
        if (!(span > 0)) return plotRect().x;
        return plotRect().x + ((t - viewStart) / span) * plotRect().w;
    }

    function valueAtPx(px) {
        var pr = plotRect();
        if (!(pr.w > 0)) return NaN;
        var t = viewStart + U.normIn(px, pr.x, pr.w) * (viewEnd - viewStart);
        return valueFromNorm(t);
    }

    function screenY(v) {
        var pr = plotRect();
        if (yr.scale === "log") {
            if (!U.isLogValid(v) || !U.isLogValid(yr.min) || !U.isLogValid(yr.max)) return NaN;
            return pr.y + (1 - U.log10(v / yr.min) / U.log10(yr.max / yr.min)) * pr.h;
        }
        if (!U.isNum(v) || !(yr.max > yr.min)) return NaN;
        return pr.y + (1 - (v - yr.min) / (yr.max - yr.min)) * pr.h;
    }

    function displayCursorA() {
        if (dragMode === "cursorA" && isFinite(dragCursorA)) return dragCursorA;
        if (U.isNum(cursorAX)) return cursorAX;
        return isFinite(dragCursorA) ? dragCursorA : null;
    }

    function displayCursorB() {
        if (dragMode === "cursorB" && isFinite(dragCursorB)) return dragCursorB;
        if (U.isNum(cursorBX)) return cursorBX;
        return isFinite(dragCursorB) ? dragCursorB : null;
    }

    function nearestPoint(points,value) {
        if(!points || !points.length)return null;
        var lo=0,hi=points.length-1;
        if(points[0] && points[hi] && points[0][0]<=points[hi][0]){
            while(hi-lo>1){var m=(lo+hi)>>1;if(!points[m]||!U.isNum(points[m][0]))break;if(points[m][0]<value)lo=m;else hi=m;}
            var a=points[lo],b=points[hi];if(a&&b)return Math.abs(a[0]-value)<=Math.abs(b[0]-value)?a:b;
        }
        var best=null,d=Infinity;
        for(var i=0;i<points.length;i+=Math.max(1,Math.ceil(points.length/512))){var p=points[i];if(p&&U.isNum(p[0])&&Math.abs(p[0]-value)<d){best=p;d=Math.abs(p[0]-value);}}
        return best;
    }
    function nearestSeriesX(px) {
        var list=visibleSeries(),value=valueAtPx(px),best=NaN,d=Infinity;
        for(var i=0;i<list.length;i++){var p=nearestPoint(list[i].points,value);if(p&&Math.abs(p[0]-value)<d){d=Math.abs(p[0]-value);best=p[0];}}
        return best;
    }
    function cursorDescription(x,label){
        var list=visibleSeries();var p=list.length?nearestPoint(list[0].points,x):null;
        return label+"  "+U.fmtTick(x,0.001)+(xr.unit?" "+xr.unit:"")+(p&&U.isNum(p[1])?" / "+U.fmtSI(p[1])+(yr.unit?" "+yr.unit:""):"");
    }

    function hasModifier(ev, mod) { return (ev.modifiers & mod) !== 0; }

    function minViewSpan() {
        return 1 / Math.max(16, plotRect().w);
    }

    function zoomAt(px, factor) {
        var span = viewEnd - viewStart;
        if (!(span > 0)) return;
        var anchor = viewStart + U.normIn(px, plotRect().x, plotRect().w) * span;
        var newSpan = U.clamp(span * factor, minViewSpan(), 1);
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
        if (!(pr.w > 0) || !(span > 0)) return;
        var shift = -dx / pr.w * span;
        viewStart += shift;
        viewEnd += shift;
        if (viewStart < 0) { viewEnd -= viewStart; viewStart = 0; }
        if (viewEnd > 1) { viewStart -= (viewEnd - 1); viewEnd = 1; }
        if (viewStart < 0) viewStart = 0;
        requestPaint();
    }

    function axTicks(axis, scale, lo, hi, target) {
        if (axis && axis.ticks && axis.ticks.length) {
            var out = [];
            for (var i = 0; i < axis.ticks.length; i++) {
                var t = axis.ticks[i];
                if (U.isNum(t) && t >= lo - 1e-9 && t <= hi + 1e-9) out.push(t);
            }
            if (out.length >= 2) return { ticks: out, step: 0, log: scale === "log" };
        }
        if (scale === "log") return U.logTicks(lo, hi, target);
        return U.linearTicks(lo, hi, target);
    }

    // ---------------------------------------------------------- painting
    function paintChart(ctx) {
        if (!ctx) return;
        ctx.save();

        // Font specs are plain strings; build them once per paint instead of
        // rebuilding the family string (with a regex strip) at every label.
        var fSmallMono = U.fontSpec(st.fsSmall, st.mono);
        var fSmall = U.fontSpec(st.fsSmall, st.font);
        var fMono = U.fontSpec(st.fs, st.mono);
        
        ctx.fillStyle = st.bg;
        ctx.fillRect(0, 0, width, height);
        if (width < 4 || height < 4) { ctx.restore(); return; }
        U.drawFrame(ctx, st, 0, 0, width, height);
        if (busy) {
            U.drawBusyState(ctx, st, width, height, busyText);
            ctx.restore();
            return;
        }
        var vis = visibleSeries();
        if (!vis.length) {
            U.drawEmptyState(ctx, st, width, height, emptyText, emptyReason);
            ctx.restore();
            return;
        }
        var pr = plotRect();
        if (pr.w < 8 || pr.h < 8) { ctx.restore(); return; }

        // ---- effective domains (log guard: clip <=0 values)
        // One sampling pass over the visible series now feeds both axis domains
        // and the display-only domain padding.  The previous code walked the
        // data three times (x collect, y collect, padding re-scan) per repaint.
        var xIsAuto = !(xAxis && U.isNum(xAxis.min) && U.isNum(xAxis.max) && xAxis.max > xAxis.min);
        var yIsAuto = !(yAxis && U.isNum(yAxis.min) && U.isNum(yAxis.max) && yAxis.max > yAxis.min);
        var xvals = xIsAuto ? [] : null;
        var yvals = yIsAuto ? [] : null;
        var dlo = Infinity, dhi = -Infinity;
        for (var cs = 0; cs < vis.length; cs++) {
            var cpts = vis[cs].points;
            var clen = cpts.length;
            var cstride = U.sampleStride(clen, 4096);
            for (var ci = 0; ci < clen; ci += cstride) {
                var cp = cpts[ci];
                if (!cp || cp.length < 2) continue;
                var cvx = cp[0];
                if (xvals && U.isNum(cvx)) xvals.push(cvx);
                var cvy = cp[1];
                if (U.isNum(cvy)) {
                    if (yvals) yvals.push(cvy);
                    if (cvy < dlo) dlo = cvy;
                    if (cvy > dhi) dhi = cvy;
                }
            }
        }
        xr = U.prepareAxis(xAxis, xvals, 1, 1000);
        yr = U.prepareAxis(yAxis, yvals, -120, 0);
        var unit=String(yr.unit||"");
        if(unit!==heldUnit){heldUnit=unit;heldYMin=NaN;heldYMax=NaN;}
        var low=yr.min,high=yr.max;
        if(unit.indexOf("FS")>=0 && unit.indexOf("dB")<0){
            var ceiling=unit.indexOf("Hz")>=0?1e-8:(unit.indexOf("²")>=0?1e-6:.01);
            low=Math.min(0,isFinite(dlo)?dlo:0);high=Math.max(ceiling,isFinite(dhi)?dhi*1.1:ceiling);
        }
        if(unit==="dBFS"){low=Math.min(-120,low);high=Math.max(0,high);}
        heldYMin=isFinite(heldYMin)?Math.min(heldYMin,low):low;
        heldYMax=isFinite(heldYMax)?Math.max(heldYMax,high):high;
        yr.min=heldYMin;yr.max=heldYMax;
        U.snapLinearDomain(xr, Math.max(2, Math.floor(pr.w / 95)));
        U.snapLinearDomain(yr, Math.max(2, Math.floor(pr.h / 46)));
        // Display-only domain padding: when the trace sits exactly on the axis
        // bound (e.g. a constant test signal) keep it visible instead of hiding
        // it under the frame.  The plotted values and units are unchanged.
        if (false && isFinite(dlo) && isFinite(dhi) && yr.max > yr.min) {
            var dspan = yr.max - yr.min;
            if (dlo <= yr.min + dspan * 1e-6) yr.min -= dspan * 0.03;
            if (dhi >= yr.max - dspan * 1e-6) yr.max += dspan * 0.03;
        }
        clippedLog = 0;

        // ---- value -> device coordinate transform, hoisted out of the loops.
        // A linear axis is one affine step; a log axis is one log step.  The hot
        // per-sample loops therefore never call screenX()/screenY() (each of
        // which rebuilt the plot rectangle object), and no per-sample garbage is
        // allocated.  Values/units/ticks are unchanged.
        var prx = pr.x, pry = pr.y, prw = pr.w, prh = pr.h;
        var xlog = xr.scale === "log";
        var ylog = yr.scale === "log";
        var vspan = viewEnd - viewStart;
        var sxA = 0, sxB = 0, syA = 0, syB = 0;
        var domainOk = vspan > 0 && xr.max > xr.min && yr.max > yr.min;
        if (domainOk) {
            if (!xlog) {
                sxA = prw / (vspan * (xr.max - xr.min));
                sxB = prx + (-xr.min / (xr.max - xr.min) - viewStart) / vspan * prw;
            } else if (xr.min > 0) {
                var xlr = Math.log(xr.max / xr.min);
                sxA = prw / (vspan * xlr);
                sxB = prx + (-Math.log(xr.min) / xlr - viewStart) / vspan * prw;
            } else {
                domainOk = false;
            }
            if (domainOk) {
                if (!ylog) {
                    var yspan = yr.max - yr.min;
                    syA = -prh / yspan;
                    syB = pry + prh + yr.min * prh / yspan;
                } else if (yr.min > 0) {
                    var ylr = Math.log(yr.max / yr.min);
                    syA = -prh / ylr;
                    syB = pry + prh + Math.log(yr.min) * prh / ylr;
                } else {
                    domainOk = false;
                }
            }
        }
        // prepareAxis guarantees a valid domain; this only guards a degenerate
        // state (e.g. a zero-width view) so the trace is never drawn with an
        // unset transform.
        if (!domainOk) { ctx.restore(); return; }

        // ---- background horizontal grid (y) + labels
        var yt = axTicks(yAxis, yr.scale, yr.min, yr.max, Math.max(5, Math.floor(pr.h / 36)));
        ctx.lineWidth = 1;
        for (var yi = 0; yi < yt.ticks.length; yi++) {
            var yv = yt.ticks[yi];
            if (yv < yr.min - 1e-9 || yv > yr.max + 1e-9) continue;
            var yy = screenY(yv);
            if (!isFinite(yy)) continue;
            var isZero = Math.abs(yv) < 1e-12;
            ctx.strokeStyle = isZero ? U.rgba(st.text, 0.28) : U.rgba(st.grid, 0.22);
            ctx.beginPath();
            ctx.moveTo(pr.x, yy + 0.5);
            ctx.lineTo(pr.x + pr.w, yy + 0.5);
            ctx.stroke();
            ctx.fillStyle = st.dim;
            ctx.font = fSmallMono;
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            ctx.fillText(U.fmtTick(yv, yt.step), pr.x - 6, yy);
        }

        // ---- vertical grid (x)
        var xt = axTicks(xAxis, xr.scale, valueFromNorm(viewStart), valueFromNorm(viewEnd),
                         Math.max(2, Math.floor(pr.w / 95)));
        var xTickScreen = [];
        for (var xi = 0; xi < xt.ticks.length; xi++) {
            var xv = xt.ticks[xi];
            var t = normFromValue(xv);
            if (!isFinite(t) || t < viewStart - 1e-9 || t > viewEnd + 1e-9) continue;
            var sx = pr.x + ((t - viewStart) / (viewEnd - viewStart)) * pr.w;
            xTickScreen.push({ x: sx, value: xv });
            ctx.strokeStyle = U.rgba(st.grid, 0.13);
            ctx.beginPath();
            ctx.moveTo(sx + 0.5, pr.y);
            ctx.lineTo(sx + 0.5, pr.y + pr.h);
            ctx.stroke();
        }

        // ---- reference bands (behind the data)
        if (referenceBands && referenceBands.length) {
            for (var rb = 0; rb < referenceBands.length; rb++) {
                var band = referenceBands[rb];
                if (!band || !U.isNum(band.y0) || !U.isNum(band.y1)) continue;
                var by0 = screenY(Math.max(band.y0, band.y1));
                var by1 = screenY(Math.min(band.y0, band.y1));
                if (!isFinite(by0) || !isFinite(by1)) continue;
                var color = typeof band.color === "string" && band.color.length ? band.color : st.accent;
                ctx.fillStyle = U.rgba(color, U.isNum(band.opacity) ? band.opacity : 0.12);
                ctx.fillRect(pr.x, by0, pr.w, Math.max(1, by1 - by0));
            }
        }

        // ---- series
        for (var s = 0; s < vis.length; s++) {
            var ser = vis[s];
            var pts = ser.points;
            var color = typeof ser.color === "string" && ser.color.length
                ? ser.color : channelPalette[s % channelPalette.length];
            var baseW = U.isNum(ser.width) && ser.width > 0 ? ser.width : (ser.reference ? 1.0 : (ser.selected ? 2.2 : 1.5));
            // Keep at least 1.5 *device* pixels so traces never wash out at 75% UI / 0.75 DPR.
            var lw = Math.max(baseW, (ser.reference ? 1.0 : 1.5) / Math.max(0.5, dpr));
            var stride = U.sampleStride(pts.length, Math.max(512, Math.floor(pr.w * 3)));
            var fillColor = "";
            if (ser.fill) {
                fillColor = typeof ser.fillColor === "string" && ser.fillColor.length
                    ? ser.fillColor : U.rgba(color, 0.14);
                var zeroInside = yr.min < 0 && yr.max > 0;
                var baseY = ylog ? (pry + prh) : (zeroInside ? syB : (pry + prh));
                if (!isFinite(baseY)) baseY = pry + prh;
                // one filled polygon per contiguous visible segment; gaps are
                // never bridged by the fill either
                var segOpen = false;
                var segStartX = NaN;
                var segEndX = NaN;
                for (var fi = 0; fi < pts.length; fi += stride) {
                    var fp = pts[fi];
                    var fok = fp && fp.length >= 2 && typeof fp[0] === "number" && isFinite(fp[0])
                        && typeof fp[1] === "number" && isFinite(fp[1]);
                    var fx = NaN, fy = NaN;
                    if (fok) {
                        var fvx = fp[0], fvy = fp[1];
                        if (xlog) { if (fvx > 0) fx = Math.log(fvx) * sxA + sxB; }
                        else fx = fvx * sxA + sxB;
                        if (ylog) { if (fvy > 0) fy = Math.log(fvy) * syA + syB; }
                        else fy = fvy * syA + syB;
                        fok = isFinite(fx) && isFinite(fy);
                    }
                    var fvis = fok &&
                        fx >= prx - 2 && fx <= prx + prw + 2 &&
                        fy >= pry - 4 && fy <= pry + prh + 4;
                    if (!fvis) {
                        if (segOpen) {
                            ctx.lineTo(segEndX, baseY);
                            ctx.lineTo(segStartX, baseY);
                            ctx.closePath();
                            ctx.fillStyle = fillColor;
                            ctx.fill();
                            segOpen = false;
                        }
                        continue;
                    }
                    if (!segOpen) {
                        ctx.beginPath();
                        ctx.moveTo(fx, baseY);
                        ctx.lineTo(fx, fy);
                        segOpen = true;
                        segStartX = fx;
                    } else {
                        ctx.lineTo(fx, fy);
                    }
                    segEndX = fx;
                }
                if (segOpen) {
                    ctx.lineTo(segEndX, baseY);
                    ctx.lineTo(segStartX, baseY);
                    ctx.closePath();
                    ctx.fillStyle = fillColor;
                    ctx.fill();
                }
            }
            ctx.strokeStyle = color;
            ctx.lineWidth = lw;
            ctx.lineJoin = "round";
            if (ser.dashed) ctx.setLineDash([5, 4]);
            else ctx.setLineDash([]);
            ctx.beginPath();
            var penDown = false;
            for (var i = 0; i < pts.length; i += stride) {
                var p = pts[i];
                if (!p || p.length < 2) { penDown = false; continue; }
                var vx = p[0], vy = p[1];
                if (typeof vx !== "number" || typeof vy !== "number"
                        || !isFinite(vx) || !isFinite(vy)) { penDown = false; continue; }
                var px = NaN, py = NaN;
                if (!xlog) px = vx * sxA + sxB;
                else if (vx > 0) px = Math.log(vx) * sxA + sxB;
                if (!ylog) py = vy * syA + syB;
                else if (vy > 0) py = Math.log(vy) * syA + syB;
                if (px !== px || py !== py || !isFinite(px) || !isFinite(py)) {
                    if (ylog && vy <= 0) clippedLog++;
                    if (xlog && vx <= 0) clippedLog++;
                    penDown = false;
                    continue;
                }
                if (px < prx - 2 || px > prx + prw + 2 || py < pry - 4 || py > pry + prh + 4) {
                    penDown = false;
                    continue;
                }
                if (!penDown) {
                    ctx.moveTo(px, py);
                    penDown = true;
                } else {
                    ctx.lineTo(px, py);
                }
            }
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // ---- reference lines (over the data, thin + dashed, labelled right)
        if (referenceLines && referenceLines.length) {
            for (var rl = 0; rl < referenceLines.length; rl++) {
                var ref = referenceLines[rl];
                if (!ref || !U.isNum(ref.y)) continue;
                var ry = screenY(ref.y);
                if (!isFinite(ry) || ry < pr.y - 1 || ry > pr.y + pr.h + 1) continue;
                var rcolor = typeof ref.color === "string" && ref.color.length ? ref.color : st.warn;
                ctx.save();
                ctx.strokeStyle = rcolor;
                ctx.lineWidth = 1;
                if (ref.dashed === false) ctx.setLineDash([]);
                else ctx.setLineDash([5, 4]);
                ctx.beginPath();
                ctx.moveTo(pr.x, ry + 0.5);
                ctx.lineTo(pr.x + pr.w, ry + 0.5);
                ctx.stroke();
                ctx.restore();
                var rlabel = typeof ref.label === "string" ? ref.label : "";
                if (rlabel.length) {
                    ctx.font = fSmallMono;
                    var rw2 = ctx.measureText(rlabel).width;
                    ctx.fillStyle = U.rgba(st.bg, 0.8);
                    ctx.fillRect(pr.x + pr.w - rw2 - 8, ry - 8, rw2 + 6, 14);
                    ctx.fillStyle = rcolor;
                    ctx.textAlign = "right";
                    ctx.textBaseline = "middle";
                    ctx.fillText(rlabel, pr.x + pr.w - 4, ry);
                }
            }
        }

        // ---- reference band labels
        if (referenceBands && referenceBands.length) {
            for (var rbl = 0; rbl < referenceBands.length; rbl++) {
                var band2 = referenceBands[rbl];
                if (!band2 || !U.isNum(band2.y0) || !U.isNum(band2.y1)) continue;
                var blo = screenY(Math.max(band2.y0, band2.y1));
                var bhi = screenY(Math.min(band2.y0, band2.y1));
                if (!isFinite(blo) || !isFinite(bhi)) continue;
                var blabel = typeof band2.label === "string" ? band2.label : "";
                if (!blabel.length) continue;
                var bcolor2 = typeof band2.color === "string" && band2.color.length ? band2.color : st.dim;
                ctx.font = fSmall;
                ctx.fillStyle = bcolor2;
                ctx.textAlign = "left";
                ctx.textBaseline = "middle";
                ctx.fillText(U.ellipsize(ctx, blabel, pr.w * 0.5), pr.x + 4, (blo + bhi) / 2);
            }
        }

        // ---- data-source markers (peak / onset / event / cursor); these are
        // coordinates supplied by the page, never re-derived from the trace
        U.drawMarkers(ctx, st, markers, screenX, screenY, { rect: pr, color: st.cursorA });

        // ---- frame + axis labels
        U.drawFrame(ctx, st, pr.x, pr.y, pr.w, pr.h);
        ctx.font = fMono;
        ctx.fillStyle = st.dim;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        var lastRight = -1e9;
        for (var xl = 0; xl < xTickScreen.length; xl++) {
            var entry = xTickScreen[xl];
            var label = U.fmtTick(entry.value, xt.step);
            var lw2 = ctx.measureText(label).width;
            if (entry.x - lw2 / 2 < lastRight + 8) continue;
            if (entry.x < pr.x - 1 || entry.x > pr.x + pr.w + 1) continue;
            var lx3 = entry.x;
            if (lx3 - lw2 / 2 < pr.x) {
                lx3 = pr.x;
                ctx.textAlign = "left";
            } else if (lx3 + lw2 / 2 > pr.x + pr.w) {
                lx3 = pr.x + pr.w;
                ctx.textAlign = "right";
            } else {
                ctx.textAlign = "center";
            }
            ctx.fillText(label, lx3, pr.y + pr.h + 6);
            lastRight = lx3 + lw2 / 2;
        }

        // x label + unit
        ctx.font = fSmall;
        ctx.fillStyle = st.dim;
        ctx.textAlign = "center";
        ctx.textBaseline = "alphabetic";
        var xLabel = xr.label;
        if (xr.unit.length) xLabel = xLabel.length ? xLabel + " (" + xr.unit + ")" : xr.unit;
        if (xLabel.length) ctx.fillText(U.ellipsize(ctx, xLabel, pr.w - 40), pr.x + pr.w / 2, pr.y + pr.h + marginBottom - 6);

        // y label + unit (header, left); the legend starts after it so the two
        // never overprint each other
        var yLabel = yr.label;
        if (yr.unit.length) yLabel = yLabel.length ? yLabel + " (" + yr.unit + ")" : yr.unit;
        var yLabelEnd = pr.x;
        if (yLabel.length) {
            ctx.font = fSmall;
            ctx.fillStyle = st.dim;
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            var yLabelText = U.ellipsize(ctx, yLabel, pr.w * 0.4);
            ctx.fillText(yLabelText, pr.x, 14);
            yLabelEnd = pr.x + ctx.measureText(yLabelText).width + 16;
        }

        // ---- legend (header) + cursor read-out (header, right)
        var readoutW = 0;
        var ca = displayCursorA();
        var cb = displayCursorB();
        ctx.font = fSmallMono;
        var parts = [];
        if (ca !== null) parts.push({ text: cursorDescription(ca,cursorLabelA), color: st.cursorA });
        if (cb !== null) parts.push({ text: cursorDescription(cb,cursorLabelB), color: st.cursorB });
        if (ca !== null && cb !== null) {
            var d = Math.abs(cb - ca);
            parts.push({ text: "\u0394 " + U.fmtTick(d, xt.step), color: st.dim });
        }
        for (var pi = 0; pi < parts.length; pi++) readoutW += ctx.measureText(parts[pi].text).width + 14;
        if (showLegend) {
            var legendRight = pr.x + pr.w;
            if (legendRight < pr.x) legendRight = pr.x;
            var lx = yLabelEnd;
            ctx.font = fSmall;
            ctx.textBaseline = "middle";
            for (var li = 0; li < vis.length; li++) {
                var sname = String(vis[li].name === undefined ? "" : vis[li].name);
                var nw = ctx.measureText(sname).width;
                if (lx + 24 + nw > legendRight) { break; }
                var lcolor = typeof vis[li].color === "string" && vis[li].color.length
                    ? vis[li].color : channelPalette[li % channelPalette.length];
                ctx.fillStyle = lcolor;
                // legend swatch = short line segment (same colour as the curve)
                ctx.fillRect(lx, 13, 14, 2);
                ctx.fillStyle = st.dim;
                ctx.textAlign = "left";
                ctx.fillText(sname, lx + 18, 14);
                lx += 24 + nw;
            }
        }
        ctx.font = fSmallMono;
        var rx2 = pr.x + pr.w;
        for (var pd = parts.length - 1; pd >= 0; pd--) {
            var tw2 = ctx.measureText(parts[pd].text).width;
            ctx.fillStyle = parts[pd].color;
            ctx.textAlign = "right";
            var available = rx2 - pr.x;
            if (available < 24) break;
            ctx.fillText(U.ellipsize(ctx, parts[pd].text, available), rx2, headerHeight - 10);
            rx2 -= tw2 + 14;
        }

        // ---- log clipping hint (values <=0 on a log axis are clipped, not drawn)
        if (clippedLog > 0) {
            var hint = logClipText.length ? logClipText : "\u2264 0 \u00d7 " + clippedLog;
            ctx.font = fSmallMono;
            var hw = ctx.measureText(hint).width;
            ctx.fillStyle = U.rgba(st.warn, 0.16);
            ctx.fillRect(pr.x + pr.w - hw - 12, pr.y + 6, hw + 10, 16);
            ctx.fillStyle = st.warn;
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            ctx.fillText(hint, pr.x + pr.w - 7, pr.y + 14);
        }

        // ---- cursors
        drawCursor(ctx, pr, ca, st.cursorA, cursorLabelA, xt.step, 0);
        drawCursor(ctx, pr, cb, st.cursorB, cursorLabelB, xt.step, 1);

        ctx.restore();
    }

    function drawCursor(ctx, pr, value, color, label, step, slot) {
        if (value === null || value === undefined) return;
        var x = screenX(value);
        if (!isFinite(x) || x < pr.x - 1 || x > pr.x + pr.w + 1) return;
        ctx.save();
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(x + 0.5, pr.y);
        ctx.lineTo(x + 0.5, pr.y + pr.h);
        ctx.stroke();
        ctx.setLineDash([]);
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

        function cursorHit(px) {
            var pr = root.plotRect();
            var best = "";
            var bestDist = 8;
            var a = root.displayCursorA();
            if (a !== null) {
                var ax = root.screenX(a);
                if (isFinite(ax) && Math.abs(ax - px) < bestDist) { bestDist = Math.abs(ax - px); best = "cursorA"; }
            }
            var b = root.displayCursorB();
            if (b !== null) {
                var bx = root.screenX(b);
                if (isFinite(bx) && Math.abs(bx - px) < bestDist) { bestDist = Math.abs(bx - px); best = "cursorB"; }
            }
            return best;
        }

        onPressed: function (ev) {
            if (!root.interactive || root.busy) return;
            var pr = root.plotRect();
            if (ev.x < pr.x || ev.x > pr.x + pr.w || ev.y < pr.y || ev.y > pr.y + pr.h) return;
            ev.accepted = true;
            root.pressX = ev.x;
            root.lastX = ev.x;
            root.dragMoved = false;
            var hit = cursorHit(ev.x);
            root.dragMode = hit !== "" ? hit : "pan";
        }

        onPositionChanged: function (ev) {
            if (!root.interactive) return;
            if (!pressed) {
                cursorShape = cursorHit(ev.x) !== "" ? Qt.SizeHorCursor : Qt.ArrowCursor;
                return;
            }
            if (root.dragMode === "") return;
            if (Math.abs(ev.x - root.pressX) > 3) root.dragMoved = true;
            if (root.dragMode === "pan") {
                root.applyPan(ev.x - root.lastX);
                root.lastX = ev.x;
            } else if (root.dragMode === "cursorA" || root.dragMode === "cursorB") {
                var snap = root.nearestSeriesX(ev.x);
                if (isFinite(snap)) {
                    if (root.dragMode === "cursorA") root.dragCursorA = snap;
                    else root.dragCursorB = snap;
                }
                root.requestPaint();
            }
        }

        onReleased: function (ev) {
            if (root.dragMode === "") return;
            var mode = root.dragMode;
            root.dragMode = "";
            if (mode === "cursorA" || mode === "cursorB") {
                var a = root.displayCursorA();
                var b = root.displayCursorB();
                if (a === null) a = NaN;
                if (b === null) b = NaN;
                root.cursorChanged(a, b);
            } else if (mode === "pan" && !root.dragMoved) {
                var xv = root.inspectionEnabled ? root.nearestSeriesX(ev.x) : root.valueAtPx(ev.x);
                if(root.inspectionEnabled && isFinite(xv))root.dragCursorA=xv;
                var yv = root.screenYToValue(ev.y);
                if (U.isNum(xv) && U.isNum(yv)) root.pointClicked(xv, yv);
            }
            root.requestPaint();
        }


        onDoubleClicked: function (ev) {
            if (!root.interactive) return;
            var pr = root.plotRect();
            if (ev.x < pr.x || ev.x > pr.x + pr.w || ev.y < pr.y || ev.y > pr.y + pr.h) return;
            root.viewStart = 0;
            root.viewEnd = 1;
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

    function screenYToValue(py) {
        var pr = plotRect();
        if (!(pr.h > 0)) return NaN;
        var t = 1 - U.clamp((py - pr.y) / pr.h, 0, 1);
        if (yr.scale === "log") {
            if (!U.isLogValid(yr.min) || !U.isLogValid(yr.max)) return NaN;
            return yr.min * Math.pow(yr.max / yr.min, t);
        }
        return yr.min + t * (yr.max - yr.min);
    }
}
