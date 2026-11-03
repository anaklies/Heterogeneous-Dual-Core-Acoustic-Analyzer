// ChartToolbar - compact chart header: localised title left (page icon + short
// title), view-only operations right (fit / A-B cursor / legend / 2D-3D / save).
// Every label and tooltip string is supplied by the page; the component hardcodes
// no UI text. Click targets are 32x32 with 20 px vector icons (no icon theme
// dependency, so the charts stay loadable in isolation). View operations only
// emit signals - they never start a PL measurement.
import QtQuick
import QtQuick.Window

Item {
    id: root
    objectName: "chartToolbar"
    implicitHeight: 36
    height: 36

    // ------------------------------------------------------------- page inputs
    property string title: ""
    property string subtitle: ""
    property string iconSource: ""
    property bool showFit: true
    property bool showLog: false
    property bool showCursor: false
    property bool showLegend: false
    property bool show3D: false
    property bool showSave: true
    property bool logActive: false
    property bool cursorActive: false
    property bool legendActive: true
    property bool threeDActive: false
    property string fitTooltip: ""
    property string logTooltip: ""
    property string cursorTooltip: ""
    property string legendTooltip: ""
    property string threeDTooltip: ""
    property string saveTooltip: ""

    // ------------------------------------------------------------- page signals
    signal fitRequested()
    signal logToggled(bool active)
    signal cursorToggled(bool active)
    signal legendToggled(bool active)
    signal threeDToggled(bool active)
    signal saveRequested()

    readonly property real dpr: Screen.devicePixelRatio
    readonly property var st: ({
        text: Theme.textPrimary,
        dim: Theme.textSecondary,
        border: Theme.border,
        hover: Theme.hover,
        pressed: Theme.pressed,
        accent: Theme.accent,
        accentSoft: Theme.accentSoft,
        bg: Theme.panelBg,
        font: Theme.fontFamily,
        fs: Math.max(12, Math.round(13 * Theme.fontScale)),
        fsSmall: Math.max(11, Math.round(12 * Theme.fontScale))
    })

    function tooltipFor(key) {
        if (key === "fit") return fitTooltip
        if (key === "log") return logTooltip
        if (key === "cursor") return cursorTooltip
        if (key === "legend") return legendTooltip
        if (key === "3d") return threeDTooltip
        if (key === "save") return saveTooltip
        return ""
    }

    function activeFor(key) {
        if (key === "log") return logActive
        if (key === "cursor") return cursorActive
        if (key === "legend") return legendActive
        if (key === "3d") return threeDActive
        return false
    }

    readonly property var buttonKeys: buttonModel()
    readonly property int buttonCount: buttons ? buttons.count : 0

    function buttonModel() {
        var list = []
        if (showFit) list.push({ key: "fit" })
        if (showLog) list.push({ key: "log" })
        if (showCursor) list.push({ key: "cursor" })
        if (showLegend) list.push({ key: "legend" })
        if (show3D) list.push({ key: "3d" })
        if (showSave) list.push({ key: "save" })
        return list
    }

    function activate(key) {
        if (key === "fit") root.fitRequested()
        else if (key === "log") { root.logActive = !root.logActive; root.logToggled(root.logActive) }
        else if (key === "cursor") { root.cursorActive = !root.cursorActive; root.cursorToggled(root.cursorActive) }
        else if (key === "legend") { root.legendActive = !root.legendActive; root.legendToggled(root.legendActive) }
        else if (key === "3d") { root.threeDActive = !root.threeDActive; root.threeDToggled(root.threeDActive) }
        else if (key === "save") root.saveRequested()
    }

    // 20 px vector glyphs drawn at device-pixel resolution, 1.4 px strokes.
    function paintIcon(ctx, key, active, hovered) {
        if (!ctx) return
        var size = 20
        ctx.save()
        ctx.clearRect(0, 0, size, size)
        var color = active ? st.accent : (hovered ? st.text : st.dim)
        ctx.strokeStyle = color
        ctx.fillStyle = color
        ctx.lineWidth = 1.4
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        if (key === "fit") {
            var m = 3.5
            var e = 7
            ctx.beginPath()
            ctx.moveTo(m, m + e); ctx.lineTo(m, m); ctx.lineTo(m + e, m)
            ctx.moveTo(size - m - e, m); ctx.lineTo(size - m, m); ctx.lineTo(size - m, m + e)
            ctx.moveTo(size - m, size - m - e); ctx.lineTo(size - m, size - m); ctx.lineTo(size - m - e, size - m)
            ctx.moveTo(m + e, size - m); ctx.lineTo(m, size - m); ctx.lineTo(m, size - m - e)
            ctx.stroke()
        } else if (key === "log") {
            ctx.beginPath()
            ctx.moveTo(4, 3); ctx.lineTo(4, 17); ctx.lineTo(18, 17)
            ctx.stroke()
            ctx.beginPath()
            var first = true
            for (var k = 0; k <= 20; k++) {
                var tx = k / 20
                var ty = Math.log(1 + 99 * tx) / Math.log(100)
                var px = 5 + tx * 12
                var py = 16 - ty * 11
                if (first) { ctx.moveTo(px, py); first = false } else ctx.lineTo(px, py)
            }
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(8, 17); ctx.lineTo(8, 15)
            ctx.moveTo(11, 17); ctx.lineTo(11, 15.6)
            ctx.moveTo(14, 17); ctx.lineTo(14, 16)
            ctx.moveTo(17, 17); ctx.lineTo(17, 16)
            ctx.stroke()
        } else if (key === "cursor") {
            ctx.setLineDash([2, 2])
            ctx.beginPath()
            ctx.moveTo(6.5, 4); ctx.lineTo(6.5, size - 4)
            ctx.moveTo(13.5, 4); ctx.lineTo(13.5, size - 4)
            ctx.stroke()
            ctx.setLineDash([])
            ctx.beginPath()
            ctx.moveTo(6.5, 8); ctx.lineTo(3.5, 5); ctx.moveTo(6.5, 8); ctx.lineTo(9.5, 5)
            ctx.moveTo(13.5, 8); ctx.lineTo(10.5, 5); ctx.moveTo(13.5, 8); ctx.lineTo(16.5, 5)
            ctx.stroke()
        } else if (key === "legend") {
            ctx.beginPath()
            for (var i = 0; i < 3; i++) {
                var y = 5 + i * 5
                ctx.strokeRect(3, y - 1.5, 4, 3)
                ctx.moveTo(10, y); ctx.lineTo(size - 3, y)
            }
            ctx.stroke()
        } else if (key === "3d") {
            ctx.beginPath()
            ctx.strokeRect(3.5, 7.5, 9, 9)
            ctx.moveTo(3.5, 7.5); ctx.lineTo(7.5, 3.5)
            ctx.lineTo(16.5, 3.5); ctx.lineTo(16.5, 12.5); ctx.lineTo(12.5, 16.5)
            ctx.moveTo(7.5, 3.5); ctx.lineTo(7.5, 12.5); ctx.lineTo(16.5, 12.5)
            ctx.moveTo(7.5, 12.5); ctx.lineTo(3.5, 16.5)
            ctx.stroke()
        } else if (key === "save") {
            ctx.beginPath()
            ctx.moveTo(10, 3); ctx.lineTo(10, 12)
            ctx.moveTo(6, 8.5); ctx.lineTo(10, 12.5); ctx.lineTo(14, 8.5)
            ctx.moveTo(4, 14); ctx.lineTo(4, 17); ctx.lineTo(16, 17); ctx.lineTo(16, 14)
            ctx.stroke()
        }
        ctx.restore()
    }

    Row {
        id: left
        objectName: "chartTitleRow"
        anchors.left: parent.left
        anchors.right: rightOps.left
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6
        height: 32
        clip: true

        Image {
            id: pageIcon
            width: 20
            height: 20
            anchors.verticalCenter: parent.verticalCenter
            source: root.iconSource
            sourceSize: Qt.size(Math.round(20 * root.dpr), Math.round(20 * root.dpr))
            fillMode: Image.PreserveAspectFit
            visible: root.iconSource.length > 0 && status !== Image.Error
            smooth: true
        }
        Column {
            width: Math.max(0, left.width - (pageIcon.visible ? 26 : 0))
            anchors.verticalCenter: parent.verticalCenter
            spacing: 1
            Text {
                objectName: "chartTitle"
                width: parent.width
                text: root.title
                visible: text.length > 0
                color: root.st.text
                font.family: root.st.font
                font.pixelSize: root.st.fs
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                maximumLineCount: 1
            }
            Text {
                objectName: "chartSubtitle"
                width: parent.width
                text: root.subtitle
                visible: text.length > 0
                color: root.st.dim
                font.family: root.st.font
                font.pixelSize: root.st.fsSmall
                elide: Text.ElideRight
                maximumLineCount: 1
            }
        }
    }

    Row {
        id: rightOps
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 0
        Repeater {
            id: buttons
            objectName: "chartToolbarRepeater"
            model: root.buttonModel()
            delegate: Item {
                id: button
                required property var modelData
                width: button.modelData.key === "fit" ? 48 : 36
                height: 34
                objectName: "chartToolbarBtn_" + modelData.key
                readonly property bool active: root.activeFor(modelData.key)
                readonly property string tip: root.tooltipFor(modelData.key)
                Rectangle {
                    anchors.fill: parent
                    radius: Math.round(6 * Theme.fontScale)
                    color: button.active ? root.st.accentSoft
                         : (mouse.containsMouse ? root.st.hover : "transparent")
                    border.width: button.active ? 1 : 0
                    border.color: button.active ? root.st.accent : "transparent"
                }
                Canvas {
                    id: glyph
                    objectName: "chartIcon_" + button.modelData.key
                    width: 20
                    height: 20
                    anchors.centerIn: parent
                    visible:button.modelData.key !== "fit"
                                onPaint:root.paintIcon(getContext("2d"),button.modelData.key,button.active,mouse.containsMouse)
                    /*onPaint: root.paintIcon(getContext("2d"), button.modelData.key,
                                            button.active, mouse.containsMouse)*/
                    onAvailableChanged: if (available) requestPaint()
                }
                Text {anchors.centerIn:parent;visible:button.modelData.key === "fit";text:typeof App!=="undefined"?App.t("instrument.reset"):"Reset";font.pixelSize:13;color:root.st.dim}
                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onContainsMouseChanged: glyph.requestPaint()
                    onClicked: root.activate(button.modelData.key)
                }
                Rectangle {
                    id: tipBox
                    visible: mouse.containsMouse && button.tip.length > 0
                    z: 50
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.bottom
                    anchors.topMargin: 2
                    width: tipText.implicitWidth + 14
                    height: tipText.implicitHeight + 8
                    radius: 5
                    color: root.st.bg
                    border.width: 1
                    border.color: root.st.border
                    Text {
                        id: tipText
                        anchors.centerIn: parent
                        text: button.tip
                        color: root.st.text
                        font.family: root.st.font
                        font.pixelSize: root.st.fsSmall
                    }
                }
            }
        }
    }
}
