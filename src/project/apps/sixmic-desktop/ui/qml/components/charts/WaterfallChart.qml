// Display-only frequency/time/level surface. Numeric frames must be supplied by
// the data source; image colors are never decoded into invented measurements.
import QtQuick
import QtQuick.Window
import "ChartUtil.js" as U

Item {
    id: root
    clip: true
    // Ordered frames: [{time: seconds, points: [[frequencyHz, levelDb], ...]}].
    // Adjacent frames must share frequency bins; missing bins leave mesh holes.
    property var frames: []
    property var frequencyAxis: ({min: 20, max: 20000, scale: "log", label: "", unit: "Hz"})
    property var timeAxis: ({min: 0, max: 1, label: "", unit: "s"})
    property var colorScale: ({min: -100, max: 0, palette: "magma", label: "", unit: "dBFS"})
    property bool busy: false
    property bool interactive: true
    property string emptyText: ""
    property string emptyReason: ""
    property string busyText: ""
    property int dataRevision: 0
    property real depth: 0.30
    property real rise: 0.26
    property bool dragging: false
    readonly property real dpr: Screen.devicePixelRatio
    readonly property var st: ({bg: Theme.plotBg, grid: Theme.plotGrid,
        dim: Theme.plotTextDim, text: Theme.plotText, font: Theme.fontFamily,
        fs: Math.max(12, Math.round(13 * Theme.fontScale)),
        fsSmall: Math.max(11, Math.round(12 * Theme.fontScale))})
    // Hard limits apply before allocating or drawing any mesh, independently of
    // incoming payload size. Paint complexity <= 48 * 128 cells.
    readonly property int maxFrames: 48
    // DPR selects only the display mesh budget, never coordinate transforms.
    readonly property int maxBins: dragging ? 128 : Math.max(256, Math.min(1025, Math.floor(width * dpr)))
    readonly property var meshData: { var revision = dataRevision; return mesh(); }
    readonly property int validCellCount: meshData.cells.length

    function requestPaint() {
        if (canvas.available && visible) canvas.requestPaint();
    }
    onFramesChanged: requestPaint()
    onFrequencyAxisChanged: requestPaint()
    onTimeAxisChanged: requestPaint()
    onColorScaleChanged: requestPaint()
    onBusyChanged: requestPaint()
    onEmptyTextChanged: requestPaint()
    onEmptyReasonChanged: requestPaint()
    onBusyTextChanged: requestPaint()
    onDataRevisionChanged: requestPaint()
    onDepthChanged: requestPaint()
    onRiseChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onDprChanged: requestPaint()
    onVisibleChanged: if (visible) requestPaint()
    Connections { target: Theme; function onChanged() { root.requestPaint(); } }

    function axis(config, lo, hi) { return U.prepareAxis(config, [], lo, hi); }
    function norm(value, config) {
        var epsilon = (config.max - config.min) * 1e-9;
        if (!U.isNum(value) || value < config.min - epsilon || value > config.max + epsilon) return NaN;
        value = U.clamp(value, config.min, config.max);
        if (config.scale === "log") return value > 0 ? U.log10(value / config.min) / U.log10(config.max / config.min) : NaN;
        return (value - config.min) / (config.max - config.min);
    }
    function mesh() {
        var cells = [];
        var rows = frames || [];
        var fa = axis(frequencyAxis, 20, 20000);
        var ta = axis(timeAxis, 0, 1);
        var ca = axis(colorScale, -100, 0);
        // The provider owns display extraction, just as for WaveformChart.
        // Reject oversized payloads instead of drawing a misleading partial map.
        if (rows.length > maxFrames) return {cells: cells};
        var frameStride = Math.max(1, Math.ceil((rows.length - 1) / (maxFrames - 1)));
        // Never bridge skipped frames/bins containing a gap: only render adjacent
        // original cells. At high input resolution this is a sparse mesh.
        for (var r = 0; r + 1 < rows.length; r += frameStride) {
            var a = rows[r], b = rows[r + 1];
            if (!a || !b || !a.points || !b.points || !(b.time > a.time)) continue;
            var tz0 = norm(a.time, ta), tz1 = norm(b.time, ta);
            if (!isFinite(tz0) || !isFinite(tz1)) continue;
            var n = Math.min(a.points.length, b.points.length);
            if (a.points.length !== b.points.length || n > 16384) return {cells: []};
            var binStride = Math.max(1, Math.ceil((n - 1) / (maxBins - 1)));
            for (var c = 0; c + 1 < n; c += binStride) {
                var next = Math.min(n - 1, c + binStride);
                var p = a.points[c], q = a.points[next];
                var s = b.points[c], t = b.points[next];
                var gap = false;
                // Display LOD spans the full frequency range, never truncates
                // to the first256 bins, and never bridges missing source bins.
                for (var k = c; k <= next; k++) {
                    var ak=a.points[k], bk=b.points[k];
                    if (!ak || !bk || ak[0] !== bk[0] || !U.isNum(ak[1]) || !U.isNum(bk[1])) { gap=true; break; }
                }
                if (gap) continue;
                if (!p || !q || !s || !t || p[0] !== s[0] || q[0] !== t[0] || !(q[0] > p[0])) continue;
                if (!U.isNum(p[1]) || !U.isNum(q[1]) || !U.isNum(s[1]) || !U.isNum(t[1])) continue;
                var x0 = norm(p[0], fa), x1 = norm(q[0], fa);
                if (!isFinite(x0) || !isFinite(x1)) continue;
                function level(v) { var span = ca.max - ca.min; return span > 0 ? U.clamp((v - ca.min) / span, 0, 1) : 0.5; }
                cells.push({v: [[x0, tz0, level(p[1])], [x1, tz0, level(q[1])],
                                [x1, tz1, level(t[1])], [x0, tz1, level(s[1])]],
                            level: (level(p[1]) + level(q[1]) + level(s[1]) + level(t[1])) / 4});
            }
        }
        return {cells: cells, frequency: fa, time: ta, level: ca};
    }
    function paint(ctx) {
        ctx.save(); 
        ctx.clearRect(0, 0, width, height);
        ctx.fillStyle = st.bg; ctx.fillRect(0, 0, width, height);
        if (busy) { U.drawBusyState(ctx, st, width, height, busyText); ctx.restore(); return; }
        var data = meshData;
        if (!data.cells.length) { U.drawEmptyState(ctx, st, width, height, emptyText, emptyReason); ctx.restore(); return; }
        if (width < 240 || height < 180) { ctx.restore(); return; }
        var left = 62, top = 34, right = 102, bottom = 58;
        var w = width - left - right, h = height - top - bottom;
        var dx = w * depth, dy = h * rise, amplitude = h - dy;
        var frontY = top + h;
        function point(x, z, v) { return {x: left + x * (w - dx) + z * dx, y: frontY - z * dy - v * amplitude}; }
        function segment(a, b, color) {
            ctx.strokeStyle = color; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        }
        function label(text, x, y, align, budget) {
            ctx.textAlign = align; ctx.fillStyle = st.dim;
            ctx.fillText(U.ellipsize(ctx, text, budget || 80), x, y);
        }
        ctx.font = U.fontSpec(11, st.font); ctx.textBaseline = "middle";
        var ft = data.frequency.scale === "log" ? U.logTicks(data.frequency.min, data.frequency.max, 6) : U.linearTicks(data.frequency.min, data.frequency.max, 6);
        var lastX = -Infinity;
        for (var f = 0; f < ft.ticks.length; f++) {
            var fx = norm(ft.ticks[f], data.frequency);
            if (!isFinite(fx)) continue;
            var fp = point(fx, 0, 0);
            segment(fp, point(fx, 1, 0), st.grid);
            segment(point(fx, 1, 0), point(fx, 1, 1), st.grid);
            var text = U.fmtSI(ft.ticks[f]), tw = ctx.measureText(text).width;
            if (fp.x - tw / 2 > lastX + 14) {
                label(text, fp.x, frontY + 17, "center"); lastX = fp.x + tw / 2;
            }
        }
        var lt = U.linearTicks(data.level.min, data.level.max, Math.max(2, Math.floor(amplitude / 42)));
        for (var l = 0; l < lt.ticks.length; l++) {
            var v = (lt.ticks[l] - data.level.min) / (data.level.max - data.level.min);
            if (v < 0 || v > 1) continue;
            segment(point(0, 0, v), point(0, 1, v), st.grid);
            segment(point(0, 1, v), point(1, 1, v), st.grid);
            label(U.fmtTick(lt.ticks[l], lt.step), left - 10, point(0, 0, v).y, "right", 48);
        }
        for (var z = 0; z <= 4; z++) {
            segment(point(0, z / 4, 0), point(1, z / 4, 0), st.grid);
        }
        // Back-to-front painter's order; each patch uses only adjacent supplied
        // samples. No cylinders, fitted curves or acoustic computations.
        function triangle(a, b, c) {
            var pa=point(a[0],a[1],a[2]),pb=point(b[0],b[1],b[2]),pc=point(c[0],c[1],c[2]);
            ctx.beginPath();ctx.moveTo(pa.x,pa.y);ctx.lineTo(pb.x,pb.y);ctx.lineTo(pc.x,pc.y);ctx.closePath();
            // Affine vertex-color interpolation is display rendering only.
            var dx1=pb.x-pa.x,dy1=pb.y-pa.y,dx2=pc.x-pa.x,dy2=pc.y-pa.y,det=dx1*dy2-dx2*dy1;
            var lo=Math.min(a[2],b[2],c[2]),hi=Math.max(a[2],b[2],c[2]);
            if(Math.abs(det)<1e-7 || hi-lo<.004)ctx.fillStyle=U.paletteColor(colorScale.palette||"magma",(a[2]+b[2]+c[2])/3);
            else {
                var gx=((b[2]-a[2])*dy2-(c[2]-a[2])*dy1)/det;
                var gy=(dx1*(c[2]-a[2])-dx2*(b[2]-a[2]))/det;
                var d=gx*gx+gy*gy;
                if(d<1e-12)ctx.fillStyle=U.paletteColor(colorScale.palette||"magma",(lo+hi)/2);
                else {
                    var start=(lo-a[2])/d,end=(hi-a[2])/d;
                    var grad=ctx.createLinearGradient(pa.x+gx*start,pa.y+gy*start,pa.x+gx*end,pa.y+gy*end);
                    for(var stop=0;stop<=3;stop++)grad.addColorStop(stop/3,U.paletteColor(colorScale.palette||"magma",lo+(hi-lo)*stop/3));
                    ctx.fillStyle=grad;
                }
            }
            ctx.fill();
        }
        for(var i=data.cells.length-1;i>=0;i--) {
            var v=data.cells[i].v;
            triangle(v[0],v[1],v[2]);triangle(v[0],v[2],v[3]);
        }
        // Foreground axes remain legible after surface compositing.
        segment(point(0, 0, 0), point(1, 0, 0), st.dim);
        segment(point(0, 0, 0), point(0, 0, 1), st.dim);
        segment(point(1, 0, 0), point(1, 1, 0), st.dim);
        label(data.frequency.label + (data.frequency.unit ? " (" + data.frequency.unit + ")" : ""), left + (w - dx) / 2, height - 15, "center", w * 0.6);
        label((data.level.label ? data.level.label + " / " : "") + data.level.unit, left, 17, "left", w * 0.65);
        // Time values at well separated endpoints rather than crowded depth ticks.
        var t0 = point(1, 0, 0), t1 = point(1, 1, 0);
        label(U.fmtTick(data.time.min,0.001) + " " + data.time.unit, t0.x + 4, t0.y + 34, "left", 64);
        label(U.fmtTick(data.time.max,0.001) + " " + data.time.unit, t1.x + 8, t1.y, "left", 64);
        var bx = width - 54, by = top, bh = Math.max(24, h * 0.7);
        for (var k = 0; k < 96; k++) {
            ctx.fillStyle = U.paletteColor(colorScale.palette || "magma", 1 - k / 95);
            ctx.fillRect(bx, by + k * bh / 96, 9, bh / 96 + 1);
        }
        label(U.fmtTick(data.level.max), bx + 14, by + 4, "left", 38);
        label(U.fmtTick(data.level.min), bx + 14, by + bh - 3, "left", 38);
        ctx.restore();
    }
    Canvas {
        id: canvas
        anchors.fill: parent
        onPaint: root.paint(getContext("2d"))
        onAvailableChanged: if (available) root.requestPaint()
    }
    MouseArea {
        anchors.fill: parent
        enabled: root.interactive && !root.busy
        property real startX: 0
        property real startY: 0
        property real startDepth: 0
        property real startRise: 0
        onPressed: function(mouse) { root.dragging=true; startX = mouse.x; startY = mouse.y; startDepth = root.depth; startRise = root.rise; }
        onReleased: root.dragging=false
        onCanceled: root.dragging=false
        onPositionChanged: function(mouse) {
            if (!pressed) return;
            root.depth = U.clamp(startDepth + (mouse.x - startX) / Math.max(1, width), 0.10, 0.42);
            root.rise = U.clamp(startRise - (mouse.y - startY) / Math.max(1, height), 0.14, 0.44);
        }
        onDoubleClicked: { root.depth = 0.30; root.rise = 0.26; }
    }
}
