import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

Panel {
    id: root
    padding: 10
    property var replay: App.recordingData.replay
    property bool hasLive: App.connectionState === "connected" && App.frameCount > 0
    property bool hasData: isReplay || hasLive
    property real position: replay ? replay.position : (hasLive ? 1.0 : 0.0)
    property real durationSeconds: replay ? replay.durationSeconds : Number(App.settings.timeWindowSeconds)
    property bool isReplay: replay !== null
    property var events: App.eventsData.events
    property var gaps: replay ? (replay.gaps || []) : []
    property bool playing: replay ? replay.playbackState === "playing" : false
    color: Theme.panelBg

    function seek(normalized) {
        if (root.isReplay) App.seekPlayback(normalized.toFixed(6))
    }

    RowLayout {
        anchors.fill: parent
        spacing: 12
        RowLayout {
            spacing: 4
            IconButton {
                iconName: root.playing ? "pause" : "play"
                tooltip: root.playing ? App.t("topbar.pause") : App.t("topbar.play")
                enabled: root.isReplay && root.hasData
                onClicked: App.setPlaybackState(root.playing ? "paused" : "playing")
            }
            IconButton {
                iconName: "square"
                tooltip: App.t("topbar.stop")
                enabled: root.isReplay && root.hasData
                onClicked: App.setPlaybackState("stopped")
            }
            Text {
                Layout.preferredWidth: 118
                text: !root.hasData
                      ? App.t("timeline.no_data")
                      : (root.isReplay
                         ? (root.position * root.durationSeconds).toFixed(2) + " / " +
                           root.durationSeconds.toFixed(2) + " s"
                         : App.t("timeline.live"))
                color: Theme.textSecondary
                font.family: Theme.fontMono
                font.pixelSize: Math.round(18 * Theme.fontScale)
                horizontalAlignment: Text.AlignRight
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Canvas {
                id: canvas
                anchors.fill: parent
                property real cursor: root.position
                property real eventCount: root.events.length
                onCursorChanged: canvas.requestPaint()
                onEventCountChanged: canvas.requestPaint()
                Connections {
                    target: App
                    function onDataChanged() { canvas.requestPaint() }
                }
                onPaint: {
                    const ctx = getContext("2d")
                    ctx.reset()
                    const w = width, h = height
                    if (w < 4 || h < 4) return
                    const top = 14, barTop = top + 18, barH = 8
                    ctx.fillStyle = Theme.plotBg
                    ctx.fillRect(0, top, w, h - top - 4)
                    if (!root.hasData) {
                        ctx.fillStyle = Theme.plotTextDim
                        ctx.font = "12px 'Cascadia Mono', monospace"
                        const text = App.t("timeline.no_data")
                        ctx.fillText(text, (w - ctx.measureText(text).width) / 2, top + 16)
                        return
                    }
                    // grid + gaps
                    ctx.strokeStyle = Theme.plotGrid
                    ctx.lineWidth = 1
                    const gapList = root.gaps || []
                    for (let gi = 0; gi < gapList.length; gi++) {
                        const gap = gapList[gi]
                        const total = root.durationSeconds > 0 ? root.durationSeconds : 1
                        let gStart = 0, gEnd = 1
                        try {
                            gStart = Math.max(0, Math.min(1, Number(gap.firstMissingSampleIndex || 0) / 1e9))
                            gEnd = Math.max(gStart, Math.min(1, Number(gap.lastMissingSampleIndex || 0) / 1e9))
                        } catch (e) { gStart = 0.45; gEnd = 0.5 }
                        ctx.fillStyle = "rgba(201,55,44,0.35)"
                        ctx.fillRect(gStart * w, barTop, Math.max(2, (gEnd - gStart) * w), barH)
                    }
                    ctx.strokeStyle = Theme.plotGrid
                    for (let i = 1; i < 10; i++) {
                        const x = Math.round(w * i / 10) + 0.5
                        ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, h - 6); ctx.stroke()
                    }
                    // track
                    ctx.fillStyle = Theme.plotGridMinor
                    ctx.fillRect(0, barTop, w, barH)
                    // events
                    const evs = root.events || []
                    for (let i = 0; i < evs.length && i < 200; i++) {
                        const ev = evs[i]
                        const p = Number(ev.position !== undefined ? ev.position : 0.5)
                        const x = Math.max(1, Math.min(w - 3, p * w))
                        ctx.fillStyle = ev.kind === "error" ? Theme.error : (ev.kind === "warn" ? Theme.warn : Theme.info)
                        ctx.fillRect(x - 1, top + 2, 2, 8)
                    }
                    // cursor
                    const cx = Math.max(0, Math.min(w - 1, root.position * w))
                    ctx.strokeStyle = Theme.accent
                    ctx.lineWidth = 1.5
                    ctx.beginPath(); ctx.moveTo(cx, top); ctx.lineTo(cx, h - 6); ctx.stroke()
                    ctx.fillStyle = Theme.accent
                    ctx.beginPath(); ctx.arc(cx, top + 3, 3.5, 0, Math.PI * 2); ctx.fill()
                    // labels
                    ctx.fillStyle = Theme.plotTextDim
                    ctx.font = "11px monospace"
                    const total = root.durationSeconds
                    const label = root.isReplay ? total.toFixed(2) + " s" : App.t("timeline.live")
                    ctx.fillText(label, w - ctx.measureText(label).width - 2, h - 2)
                }
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton
                    onPressed: function(mouse) { root.seek(Math.max(0, Math.min(1, mouse.x / width))) }
                    onPositionChanged: function(mouse) {
                        if (pressed) root.seek(Math.max(0, Math.min(1, mouse.x / width)))
                    }
                }
            }
        }
        RowLayout {
            spacing: 10
            Text {
                text: App.t("timeline.events") + " " + (root.events ? root.events.length : 0)
                color: Theme.textSecondary
                font.family: Theme.fontMono
                font.pixelSize: Math.round(18 * Theme.fontScale)
            }
            IconButton {
                iconName: false ? "chevron-down" : "chevron-up"
                tooltip: App.t("timeline.zoom")
                onClicked: App.setTimelineVisible(!false)
            }
        }
    }
}
