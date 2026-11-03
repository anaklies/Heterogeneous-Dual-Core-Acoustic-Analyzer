// NoiseRatingChart - NC/NR estimate display: measured band spectrum (payload),
// optional reference family curves supplied by the payload (the PC never
// fabricates NC/NR reference tables or computes the rating), estimate readouts
// and the explicit reference note. All labels come from the page.
import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property bool inspectionEnabled: false
    property var series: []
    property var referenceFamilies: []   // [{name,points:[[freq,db],...],color,dashed}]
    property var markers: []
    property var referenceLines: []
    property var referenceBands: []
    property var readoutRows: []
    property var xAxis: null
    property var yAxis: null
    property string note: ""
    property string family: ""
    property bool showLegend: true
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""
    property int dataRevision: 0

    readonly property var combinedSeries: {
        var out = []
        var measured = series || []
        for (var i = 0; i < measured.length; i++) out.push(measured[i])
        var families = referenceFamilies || []
        for (var f = 0; f < families.length && f < 40; f++) {
            var fam = families[f]
            if (!fam || !fam.points || !fam.points.length) continue
            out.push({
                name: fam.name !== undefined ? fam.name : "",
                points: fam.points,
                color: fam.color !== undefined && String(fam.color).length
                       ? fam.color : Theme.channelColors[f % Theme.channelColors.length],
                dashed: fam.dashed === undefined ? true : fam.dashed,
                width: 1,
                visible: true
            })
        }
        return out
    }
    readonly property int familyCount: referenceFamilies ? referenceFamilies.length : 0

    ColumnLayout {
        anchors.fill: parent
        spacing: 4
        ReadoutStrip {
            Layout.fillWidth: true
            Layout.minimumHeight:40;Layout.preferredHeight:40;Layout.maximumHeight:40
            visible: root.readoutRows && root.readoutRows.length > 0
            rows: root.readoutRows
        }
        LineChart {
            objectName: "noiseLineChart"
            Layout.fillWidth: true
            Layout.fillHeight: true
            inspectionEnabled: root.inspectionEnabled
            dataRevision: root.dataRevision
            busy: root.busy
            series: root.combinedSeries
            xAxis: root.xAxis
            yAxis: root.yAxis
            markers: root.markers
            referenceLines: root.referenceLines
            referenceBands: root.referenceBands
            showLegend: root.showLegend
            emptyText: root.emptyText
            emptyReason: root.emptyReason
        }
        Text {
            Layout.fillWidth: true
            text: root.note
            visible: text.length > 0
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
    }
}
