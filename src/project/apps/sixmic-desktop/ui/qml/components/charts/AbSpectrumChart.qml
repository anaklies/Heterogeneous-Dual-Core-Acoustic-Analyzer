// AbSpectrumChart - A/B spectrum comparison: top panel overlays reference A,
// current B and the threshold; the bottom panel shows the delta trace against
// the threshold band. Series roles are supplied by the page (role a/b/delta or
// panel index) and colours/dash patterns stay visually distinct; nothing is
// computed here (the delta is a payload series, not a PC recalculation).
import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property bool inspectionEnabled: false
    property var series: []
    property var referenceLines: []
    property var referenceBands: []
    property var xAxis: null
    property var yAxis: null
    property var deltaYAxis: null
    property string topTitle: ""
    property string topSubtitle: ""
    property string deltaTitle: ""
    property string deltaSubtitle: ""
    property bool showLegend: true
    property int dataRevision: 0
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""

    readonly property var split: {
        var top = []
        var delta = []
        var list = series || []
        var aCount = 0
        for (var i = 0; i < list.length; i++) {
            var s = list[i]
            if (!s || typeof s !== "object") continue
            var role = String(s.role === undefined ? "" : s.role).toLowerCase()
            var copy = {
                name: s.name,
                color: s.color,
                points: s.points,
                width: s.width,
                dashed: s.dashed,
                fill: s.fill,
                fillColor: s.fillColor,
                visible: s.visible
            }
            if (role === "delta" || role === "difference" || role === "diff" || s.panel === 1) {
                if (!copy.color || String(copy.color).length === 0)
                    copy.color = Theme.channelColors[2]
                delta.push(copy)
            } else {
                if (!copy.color || String(copy.color).length === 0) {
                    copy.color = aCount === 0 ? Theme.channelColors[0] : Theme.channelColors[1]
                }
                if (role === "b" && copy.dashed === undefined) copy.dashed = true
                top.push(copy)
                aCount++
            }
        }
        return { top: top, delta: delta }
    }
    readonly property var abSeries: split.top
    readonly property var deltaSeries: split.delta

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 60
            spacing: 2
            Text {
                Layout.fillWidth: true
                text: root.topTitle
                visible: text.length > 0
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: root.topSubtitle
                visible: text.length > 0
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
                elide: Text.ElideRight
            }
            LineChart {
                id: topChart
                objectName: "abTopChart"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 50
                inspectionEnabled: root.inspectionEnabled
            dataRevision: root.dataRevision
                busy: root.busy
                series: root.abSeries
                xAxis: root.xAxis
                yAxis: root.yAxis
                referenceLines: root.referenceLines
                referenceBands: root.referenceBands
                showLegend: root.showLegend
                emptyText: root.emptyText
                emptyReason: root.emptyReason
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: root.deltaSeries.length > 0
            Layout.minimumHeight: 40
            visible: root.deltaSeries.length > 0
            spacing: 2
            Text {
                Layout.fillWidth: true
                text: root.deltaTitle
                visible: text.length > 0
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: root.deltaSubtitle
                visible: text.length > 0
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
                elide: Text.ElideRight
            }
            LineChart {
                id: deltaChart
                objectName: "abDeltaChart"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 40
                inspectionEnabled: root.inspectionEnabled
            dataRevision: root.dataRevision
                busy: root.busy
                series: root.deltaSeries
                xAxis: root.xAxis
                yAxis: root.deltaYAxis ? root.deltaYAxis : root.yAxis
                referenceLines: root.referenceLines
                referenceBands: root.referenceBands
                showLegend: false
                emptyText: root.emptyText
                emptyReason: root.emptyReason
            }
        }
    }
}
