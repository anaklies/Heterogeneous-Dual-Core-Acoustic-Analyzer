// TimelineChart - transport / event timeline for the bottom of the workspace.
// Implements CHART_DATA_CONTRACT.md section 7.
//
// All positions (position / selection / gaps / events) are normalised 0..1 of
// durationSeconds; absolute time conversion stays in the Python presentation
// layer (u64 sample ids never enter QML arithmetic). No scanning animation:
// playing only changes the play-head shape, repaint happens on data revision.
//
// QML note / documented contract deviation: the property change signal name
// selectionChanged is reserved by the selection property in QML, so the
// interaction signal with (start,end) arguments is exposed additively as
// selectionEdited(); selectionChanged() still fires when the page updates it.
import QtQuick
import QtQuick.Window
import "ChartUtil.js" as U

Item {
    id: root

    // ---------------------------------------------------------- contract inputs
    property real durationSeconds: 0
    property real position: 0
    property var events: []
    property var selection: null
    property var gaps: []
    property bool playing: false
    property bool interactive: true
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""

    // -------------------------------------------------- additive (optional) API
    property int dataRevision: 0
    property string busyText: ""
    property bool eventLabelsVisible: true

    // ---------------------------------------------------------- contract signals
    signal seekRequested(real position01)
    signal selectionEdited(real start, real end)

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

    // ---------------------------------------------------------- interaction state
    property string dragMode: ""       // "" | seek | select
    property bool dragMoved: false
    property real pressX: -1
    property real dragPosition: -1
    property var internalSelection: null
    property bool internalSelectionValid: false

    readonly property real marginLeft: 10
    readonly property real marginRight: 10
    readonly property real headerHeight: 18
    readonly property real marginBottom: 28

    // ---------------------------------------------------------- repaint plumbing
    function requestPaint() {
        if (canvas && canvas.available && visible) canvas.requestPaint();
    }
    onDurationSecondsChanged: requestPaint()
    onPositionChanged: requestPaint()
    onEventsChanged: requestPaint()
    onSelectionChanged: requestPaint()
    onGapsChanged: requestPaint()
    onPlayingChanged: requestPaint()
    onDataRevisionChanged: requestPaint()
    onBusyChanged: requestPaint()
    onEmptyTextChanged: requestPaint()
    onEmptyReasonChanged: requestPaint()
    onEventLabelsVisibleChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onDprChanged: requestPaint()
    onVisibleChanged: if (visible) requestPaint()
    Connections {
        target: Theme
        function onChanged() { root.requestPaint(); }
    }

    // ---------------------------------------------------------- helpers
    function trackRect() {
        var top = headerHeight;
        var h = Math.max(14, Math.min(34, height - headerHeight - marginBottom - 6));
        return {
            x: marginLeft,
            y: top,
            w: Math.max(8, width - marginLeft - marginRight),
            h: h
        };
    }

    function normFromX(px) {
        var tr = trackRect();
        return U.clamp((px - tr.x) / tr.w, 0, 1);
    }

    function displayPosition() {
        if (dragMode === "seek" && dragPosition >= 0) return dragPosition;
        return U.clamp(U.isNum(position) ? position : 0, 0, 1);
    }

    function displaySelection() {
        if (selection && U.isNum(selection.start) && U.isNum(selection.end)) return selection;
        if (internalSelectionValid) return internalSelection;
        return null;
    }

    function eventColor(kind) {
        if (kind === "warn") return st.warn;
        if (kind === "error") return st.error;
        if (kind === "info") return st.info;
        return st.ok;
    }

    function gapList() {
        var out = [];
        if (!gaps || !gaps.length) return out;
        for (var i = 0; i < gaps.length; i++) {
            var g = gaps[i];
            if (!g || !U.isNum(g.start) || !U.isNum(g.end)) continue;
            out.push({ start: U.clamp(Math.min(g.start, g.end), 0, 1), end: U.clamp(Math.max(g.start, g.end), 0, 1) });
        }
        return out;
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
        if (!(durationSeconds > 0)) {
            U.drawEmptyState(ctx, st, width, height, emptyText, emptyReason);
            ctx.restore();
            return;
        }

        var tr = trackRect();
        var dur = durationSeconds;
        var pos = displayPosition();

        // ---- track background
        ctx.fillStyle = U.rgba(st.grid, 0.30);
        ctx.fillRect(tr.x, tr.y, tr.w, tr.h);
        ctx.strokeStyle = st.grid;
        ctx.lineWidth = 1;
        ctx.strokeRect(tr.x + 0.5, tr.y + 0.5, tr.w - 1, tr.h - 1);

        // ---- time ticks (1/2/5) + labels below the track
        var ticks = U.linearTicks(0, dur, Math.max(2, Math.floor(tr.w / 95))).ticks;
        for (var i = 0; i < ticks.length; i++) {
            var tv = ticks[i];
            if (tv < -1e-9 || tv > dur + 1e-9) continue;
            var nx = U.clamp(tv / dur, 0, 1);
            var xx = tr.x + nx * tr.w;
            ctx.strokeStyle = st.minor;
            ctx.beginPath();
            ctx.moveTo(xx + 0.5, tr.y);
            ctx.lineTo(xx + 0.5, tr.y + tr.h);
            ctx.stroke();
            ctx.fillStyle = st.dim;
            ctx.font = U.fontSpec(st.fs, st.mono);
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            var label;
            if (dur >= 60) {
                var tm = Math.floor(tv / 60);
                var ts = Math.round(tv - tm * 60);
                if (ts >= 60) { tm += 1; ts -= 60; }
                label = tm + ":" + (ts < 10 ? "0" : "") + ts;
            } else {
                label = U.fmtSeconds(tv) + " s";
            }
            if (xx > tr.x + 12 && xx < tr.x + tr.w - 12) ctx.fillText(label, xx, tr.y + tr.h + 6);
        }

        // ---- gaps (missing data regions) with hatch-like boundary marks
        var gl = gapList();
        for (var g = 0; g < gl.length; g++) {
            var gx0 = tr.x + gl[g].start * tr.w;
            var gx1 = tr.x + gl[g].end * tr.w;
            var w = Math.max(1, gx1 - gx0);
            ctx.fillStyle = U.rgba(st.error, 0.16);
            ctx.fillRect(gx0, tr.y, w, tr.h);
            ctx.strokeStyle = U.rgba(st.error, 0.5);
            ctx.beginPath();
            ctx.moveTo(gx0 + 0.5, tr.y);
            ctx.lineTo(gx0 + 0.5, tr.y + tr.h);
            if (gx1 - gx0 > 2) {
                ctx.moveTo(gx1 - 0.5, tr.y);
                ctx.lineTo(gx1 - 0.5, tr.y + tr.h);
            }
            ctx.stroke();
        }

        // ---- selection band
        var sel = displaySelection();
        if (sel) {
            var s0 = U.clamp(Math.min(sel.start, sel.end), 0, 1);
            var s1 = U.clamp(Math.max(sel.start, sel.end), 0, 1);
            var sx = tr.x + s0 * tr.w;
            var sw = Math.max(1, (s1 - s0) * tr.w);
            ctx.fillStyle = U.rgba(st.accent, 0.22);
            ctx.fillRect(sx, tr.y, sw, tr.h);
            ctx.fillStyle = st.accent;
            ctx.fillRect(sx, tr.y, 2, tr.h);
            ctx.fillRect(sx + sw - 2, tr.y, 2, tr.h);
        }

        // ---- events (marks + staggered labels above the track)
        var rowRight = [-1e9, -1e9];
        // reserve the header right side for the position read-out so event labels
        // never overprint it
        var posText = U.fmtDuration(pos * dur) + " / " + U.fmtDuration(dur);
        ctx.font = U.fontSpec(st.fs, st.mono);
        var posTextW = ctx.measureText(posText).width;
        var headerLabelLimit = tr.x + tr.w - posTextW - 14;
        ctx.font = U.fontSpec(st.fsSmall, st.font);
        var evList = events;
        if (evList && evList.length) {
            for (var e = 0; e < evList.length; e++) {
                var ev = evList[e];
                if (!ev || !U.isNum(ev.position)) continue;
                var p = U.clamp(ev.position, 0, 1);
                var ex = tr.x + p * tr.w;
                var ecolor = eventColor(ev.kind);
                ctx.fillStyle = ecolor;
                ctx.fillRect(ex - 1, tr.y - 5, 2, 10);
                var elabel = typeof ev.label === "string" ? ev.label : "";
                if (eventLabelsVisible && elabel.length && ex - 2 < headerLabelLimit) {
                    var lw = ctx.measureText(elabel).width;
                    var row = 0;
                    for (var r = 0; r < 2; r++) {
                        if (ex - 2 > rowRight[r] + 6 || r === 1) { row = r; break; }
                    }
                    var availW = Math.min(tr.w * 0.35, headerLabelLimit - ex);
                    if (ex - 2 > rowRight[row] + 6 && availW > 24) {
                        ctx.fillStyle = ecolor;
                        ctx.textAlign = "left";
                        ctx.textBaseline = "middle";
                        var ly = tr.y - 14 - row * 13;
                        var shown = U.ellipsize(ctx, elabel, availW);
                        ctx.fillText(shown, ex - 1, ly);
                        rowRight[row] = ex - 1 + ctx.measureText(shown).width;
                    }
                }
            }
        }

        // ---- play-head (position readout in the header, mono/tabular)
        var px = tr.x + pos * tr.w;
        ctx.fillStyle = st.accent;
        ctx.fillRect(px - 1, tr.y - 6, 2, tr.h + 6);
        ctx.beginPath();
        if (playing) {
            ctx.moveTo(px - 5, tr.y - 7);
            ctx.lineTo(px + 5, tr.y - 7);
            ctx.lineTo(px, tr.y - 1);
            ctx.closePath();
            ctx.fill();
        } else {
            ctx.strokeStyle = st.accent;
            ctx.lineWidth = 2.2;
            ctx.beginPath();
            ctx.moveTo(px - 5, tr.y - 7);
            ctx.lineTo(px + 5, tr.y - 7);
            ctx.lineTo(px, tr.y - 1);
            ctx.closePath();
            ctx.stroke();
        }

        ctx.font = U.fontSpec(st.fs, st.mono);
        ctx.fillStyle = st.dim;
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        ctx.fillText(posText, tr.x + tr.w, headerHeight / 2 - 2);

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
            var tr = root.trackRect();
            if (ev.y < tr.y - 10 || ev.y > tr.y + tr.h + 8) return;
            ev.accepted = true;
            root.pressX = ev.x;
            root.dragMoved = false;
            var n = root.normFromX(ev.x);
            if (ev.modifiers & Qt.ShiftModifier) {
                root.dragMode = "select";
                root.internalSelection = { start: n, end: n };
                root.internalSelectionValid = true;
            } else {
                root.dragMode = "seek";
                root.dragPosition = n;
                root.seekRequested(n);
            }
            root.requestPaint();
        }

        onPositionChanged: function (ev) {
            if (!root.interactive) return;
            var tr = root.trackRect();
            if (!pressed) {
                cursorShape = (ev.y >= tr.y - 6 && ev.y <= tr.y + tr.h + 6) ? Qt.SizeHorCursor : Qt.ArrowCursor;
                return;
            }
            if (root.dragMode === "") return;
            if (Math.abs(ev.x - root.pressX) > 3) root.dragMoved = true;
            var n2 = root.normFromX(ev.x);
            if (root.dragMode === "seek") {
                root.dragPosition = n2;
                root.seekRequested(n2);
            } else if (root.dragMode === "select") {
                root.internalSelection = { start: root.internalSelection.start, end: n2 };
                root.internalSelectionValid = true;
            }
            root.requestPaint();
        }

        onReleased: function (ev) {
            if (root.dragMode === "") return;
            var mode = root.dragMode;
            root.dragMode = "";
            if (mode === "seek") {
                root.dragPosition = -1;
            } else if (mode === "select" && root.internalSelection) {
                var a = Math.min(root.internalSelection.start, root.internalSelection.end);
                var b = Math.max(root.internalSelection.start, root.internalSelection.end);
                if (b - a < 1e-9) {
                    root.internalSelection = null;
                    root.internalSelectionValid = false;
                } else {
                    root.selectionEdited(a, b);
                }
            }
            root.requestPaint();
        }

        onDoubleClicked: function (ev) {
            if (!root.interactive || root.busy) return;
            var n3 = root.normFromX(ev.x);
            root.seekRequested(n3);
        }

        onWheel: function (wheel) {
            // Timeline is not zoomable by contract; leave the wheel to the page.
        }
    }
}
