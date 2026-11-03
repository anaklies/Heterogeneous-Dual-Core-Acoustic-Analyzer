// EventTimeline - real event timeline for monitor features. Event positions are
// normalised 0..1 from the payload; the time axis labels come from timeAxis when
// supplied. Marker colour follows the event kind and the marker/legend shape
// follows the download state; all state labels are supplied by the page. No
// event is synthesised and no polling happens in the view layer.
import QtQuick
import "ChartUtil.js" as U

Item {
    id: root
    property var events: []            // [{position01,label,kind,downloadState,detail}]
    property var timeAxis: null        // {min,max,label,unit}
    property real durationSeconds: 0
    property var downloadLabels: ({})  // {downloaded, pending, failed, unknown}
    property bool showLegend: true
    property bool interactive: true
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""
    property string busyText: ""
    property int dataRevision: 0

    signal eventActivated(int index)

    readonly property var validEvents: {
        var out = []
        var list = events || []
        for (var i = 0; i < list.length && out.length < 512; i++) {
            var e = list[i]
            if (!e || typeof e !== "object") continue
            var p = U.isNum(e.position01) ? e.position01 : (U.isNum(e.position) ? e.position : NaN)
            if (!U.isNum(p)) continue
            out.push({ index: i, position01: U.clamp(p, 0, 1), label: e.label, kind: e.kind,
                       downloadState: e.downloadState, detail: e.detail })
        }
        return out
    }
    readonly property int eventCount: validEvents.length
    readonly property int hoverIndex: -1
    property int hoveredEvent: -1

    readonly property real dpr: Screen.devicePixelRatio
    readonly property var st: ({
        bg: Theme.plotBg, grid: Theme.plotGrid, minor: Theme.plotGridMinor,
        text: Theme.plotText, dim: Theme.plotTextDim,
        info: Theme.info, warn: Theme.warn, error: Theme.error,
        accent: Theme.accent, font: Theme.fontFamily, mono: Theme.fontMono,
        fs: Math.max(12, Math.round(13 * Theme.fontScale)),
        fsSmall: Math.max(11, Math.round(12 * Theme.fontScale))
    })

    function requestPaint() {
        if (canvas && canvas.available && visible) canvas.requestPaint()
    }
    onEventsChanged: requestPaint()
    onTimeAxisChanged: requestPaint()
    onDurationSecondsChanged: requestPaint()
    onDownloadLabelsChanged: requestPaint()
    onDataRevisionChanged: requestPaint()
    onBusyChanged: requestPaint()
    onEmptyTextChanged: requestPaint()
    onEmptyReasonChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onDprChanged: requestPaint()
    onVisibleChanged: if (visible) requestPaint()
    onHoveredEventChanged: requestPaint()
    Connections { target: Theme; function onChanged() { root.requestPaint() } }

    function eventColor(kind) {
        var k = String(kind || "").toLowerCase()
        if (k === "warn" || k === "warning") return st.warn
        if (k === "error" || k === "alarm") return st.error
        if (k === "ok" || k === "info") return st.info
        return Theme.channelColors[0]
    }

    function downloadStateOf(e) {
        var s = String(e.downloadState || "").toLowerCase()
        if (s === "downloaded" || s === "complete" || s === "ready") return "downloaded"
        if (s === "failed" || s === "error") return "failed"
        if (s === "pending" || s === "queued" || s === "downloading") return "pending"
        return s.length ? s : "unknown"
    }

    function stateLabel(state) {
        var labels = downloadLabels || ({})
        var v = labels[state]
        return v === undefined ? "" : String(v)
    }

    function plotRect() {
        return { x: 36, y: 24, w: Math.max(8, width - 36 - 16), h: Math.max(18, height - 24 - 34) }
    }

    function xFor(pr, position01) {
        return pr.x + U.clamp(position01, 0, 1) * pr.w
    }

    function nearestEvent(px, py) {
        var pr = plotRect()
        var best = -1
        var bestD = 12
        for (var i = 0; i < validEvents.length; i++) {
            var x = xFor(pr, validEvents[i].position01)
            var d = Math.abs(x - px)
            if (d < bestD) { bestD = d; best = i }
        }
        return py >= pr.y - 4 && py <= pr.y + pr.h + 10 ? best : -1
    }

    function paint(ctx) {
        if (!ctx) return
        ctx.save()
        var w = width
        var h = height
        ctx.clearRect(0, 0, w, h)
        ctx.fillStyle = st.bg
        ctx.fillRect(0, 0, w, h)
        if (w < 8 || h < 8) { ctx.restore(); return }
        U.drawFrame(ctx, st, 0, 0, w, h)
        if (busy) { U.drawBusyState(ctx, st, w, h, busyText); ctx.restore(); return }
        if (!validEvents.length) { U.drawEmptyState(ctx, st, w, h, emptyText, emptyReason); ctx.restore(); return }

        var pr = plotRect()
        var axis = timeAxis
        var axisMin = axis && U.isNum(axis.min) ? axis.min : 0
        var axisMax = axis && U.isNum(axis.max) ? axis.max : (durationSeconds > 0 ? durationSeconds : 1)
        if (!(axisMax > axisMin)) axisMax = axisMin + 1
        var unit = axis && axis.unit !== undefined ? String(axis.unit) : ""
        var axisLabel = axis && axis.label !== undefined ? String(axis.label) : ""

        // ---- time grid + labels
        var ticks = U.linearTicks(axisMin, axisMax, Math.max(2, Math.floor(pr.w / 100)))
        ctx.lineWidth = 1
        ctx.font = U.fontSpec(st.fsSmall, st.mono)
        for (var t = 0; t < ticks.ticks.length; t++) {
            var tv = ticks.ticks[t]
            if (tv < axisMin - 1e-9 || tv > axisMax + 1e-9) continue
            var frac = (tv - axisMin) / (axisMax - axisMin)
            var tx = pr.x + frac * pr.w
            ctx.strokeStyle = U.rgba(st.minor, 0.9)
            ctx.beginPath(); ctx.moveTo(tx + 0.5, pr.y); ctx.lineTo(tx + 0.5, pr.y + pr.h); ctx.stroke()
            ctx.fillStyle = st.dim
            ctx.textAlign = "center"; ctx.textBaseline = "top"
            if (tx > pr.x + 8 && tx < pr.x + pr.w - 8)
                ctx.fillText(U.fmtTick(tv, ticks.step) + (unit.length ? " " + unit : ""), tx, pr.y + pr.h + 5)
        }

        // ---- baseline
        var baseY = pr.y + pr.h - 12
        ctx.strokeStyle = st.grid
        ctx.beginPath(); ctx.moveTo(pr.x, baseY + 0.5); ctx.lineTo(pr.x + pr.w, baseY + 0.5); ctx.stroke()

        // ---- event markers + staggered labels
        for (var i = 0; i < validEvents.length; i++) {
            var e = validEvents[i]
            var x = xFor(pr, e.position01)
            var color = eventColor(e.kind)
            var state = downloadStateOf(e)
            var hovered = i === root.hoveredEvent
            var stem = 8 + (i % 3) * 5
            ctx.strokeStyle = U.rgba(color, hovered ? 1.0 : 0.75)
            ctx.lineWidth = hovered ? 1.6 : 1
            ctx.beginPath(); ctx.moveTo(x + 0.5, baseY); ctx.lineTo(x + 0.5, baseY - stem - 6); ctx.stroke()
            ctx.fillStyle = color
            ctx.strokeStyle = color
            if (state === "downloaded") {
                ctx.beginPath(); ctx.arc(x, baseY - stem - 6, 3.2, 0, Math.PI * 2); ctx.fill()
            } else if (state === "pending") {
                ctx.lineWidth = 1.4
                ctx.beginPath(); ctx.arc(x, baseY - stem - 6, 3.2, 0, Math.PI * 2); ctx.stroke()
            } else if (state === "failed") {
                ctx.lineWidth = 1.4
                ctx.beginPath()
                ctx.moveTo(x - 3, baseY - stem - 9); ctx.lineTo(x + 3, baseY - stem - 3)
                ctx.moveTo(x + 3, baseY - stem - 9); ctx.lineTo(x - 3, baseY - stem - 3)
                ctx.stroke()
            } else {
                ctx.beginPath()
                ctx.moveTo(x, baseY - stem - 9); ctx.lineTo(x + 3, baseY - stem - 6)
                ctx.lineTo(x, baseY - stem - 3); ctx.lineTo(x - 3, baseY - stem - 6)
                ctx.closePath(); ctx.fill()
            }
            var label = e.label === undefined ? "" : String(e.label)
            if (label.length) {
                var row = i % 3
                var ly = pr.y + 12 + row * 15
                var lx = Math.min(Math.max(pr.x + 2, x - 4), pr.x + pr.w - 6)
                ctx.font = U.fontSpec(st.fsSmall, st.font)
                var tw = ctx.measureText(label).width
                var maxW = Math.min(150, pr.w * 0.4)
                var text = U.ellipsize(ctx, label, maxW)
                tw = ctx.measureText(text).width
                var bx = lx
                if (bx + tw + 6 > pr.x + pr.w) bx = pr.x + pr.w - tw - 6
                ctx.fillStyle = U.rgba(st.bg, 0.8)
                ctx.fillRect(bx, ly - 7, tw + 6, 14)
                ctx.fillStyle = hovered ? st.text : U.rgba(color, 0.95)
                ctx.textAlign = "left"; ctx.textBaseline = "middle"
                ctx.fillText(text, bx + 3, ly)
            }
            var dl = stateLabel(state)
            if (dl.length && hovered) {
                ctx.fillStyle = st.dim
                ctx.font = U.fontSpec(st.fsSmall, st.mono)
                ctx.textAlign = "center"; ctx.textBaseline = "top"
                ctx.fillText(U.ellipsize(ctx, dl, 120), x, baseY + 16)
            }
        }

        // ---- axis caption + download-state legend
        ctx.font = U.fontSpec(st.fsSmall, st.font)
        ctx.fillStyle = st.dim
        ctx.textAlign = "left"
        ctx.textBaseline = "alphabetic"
        var caption = axisLabel
        if (unit.length) caption = caption.length ? caption + " (" + unit + ")" : unit
        if (caption.length) ctx.fillText(caption, pr.x, h - 6)
        if (showLegend) {
            var labels = downloadLabels || ({})
            var states = ["downloaded", "pending", "failed"]
            var lx2 = pr.x + pr.w
            ctx.textAlign = "right"
            for (var sti = states.length - 1; sti >= 0; sti--) {
                var stateName = states[sti]
                var lab = stateLabel(stateName)
                if (!lab.length) continue
                var tw2 = ctx.measureText(lab).width
                ctx.fillStyle = st.dim
                ctx.fillText(lab, lx2 - 10, 13)
                ctx.fillStyle = st.text
                ctx.beginPath()
                if (stateName === "downloaded") ctx.arc(lx2 - tw2 - 16, 10, 3, 0, Math.PI * 2)
                else if (stateName === "pending") { ctx.strokeStyle = st.text; ctx.lineWidth = 1.2; ctx.arc(lx2 - tw2 - 16, 10, 3, 0, Math.PI * 2) }
                else { ctx.fillRect(lx2 - tw2 - 18, 7, 5, 1.5); ctx.fillRect(lx2 - tw2 - 16, 6, 1.5, 6) }
                ctx.fill()
                lx2 -= tw2 + 34
            }
        }
        ctx.restore()
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        onPaint: root.paint(getContext("2d"))
        onAvailableChanged: if (available) root.requestPaint()
    }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        hoverEnabled: true
        enabled: root.interactive
        onClicked: function (ev) {
            var idx = root.nearestEvent(ev.x, ev.y)
            if (idx >= 0) root.eventActivated(root.validEvents[idx].index)
        }
    }
}
