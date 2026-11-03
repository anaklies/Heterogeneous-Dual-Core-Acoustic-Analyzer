// ReadoutChart - instrument readout strip above a single line/bar chart, or
// above PanelChart when panels are supplied (room decay/clarity, statistics,
// harmonic bars, insulation bars, ...). Values and axes come from the payload.
import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property bool inspectionEnabled: false
    property var readoutRows: []
    property int readoutColumns: 0
    property bool showReadout: true
    property bool wrapReadouts: false
    property string render: "line"
    property var panels: []

    // line / bar payload
    property var series: []
    property var categories: []
    property var xAxis: null
    property var yAxis: null
    property var markers: []
    property var referenceLines: []
    property var referenceBands: []
    property var limitLine: null
    property var referenceValues: []
    property var bandRamp: []
    property var colorScale: null
    property string valueFormat: ""
    property string xMode: "category"
    property string xLabel: ""
    property string xUnit: ""
    property bool showLegend: false
    property int dataRevision: 0
    property bool interactive: true
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""

    readonly property bool hasReadout: showReadout && readoutRows && readoutRows.length > 0

    ColumnLayout {
        anchors.fill: parent
        spacing: 4

        ReadoutStrip {
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
            visible: root.hasReadout
            rows: root.readoutRows
            wrapRows: root.wrapReadouts
        }
        Loader {
            id: contentLoader
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: 1
            sourceComponent: root.panels && root.panels.length > 0
                             ? panelComponent
                             : (root.render === "bars" ? barComponent : lineComponent)
        }
    }

    Component {
        id: lineComponent
        LineChart {
            anchors.fill: parent
            objectName: "readoutLineChart"
            dataRevision: root.dataRevision
            inspectionEnabled: root.inspectionEnabled
            interactive: root.interactive
            busy: root.busy
            series: root.series
            xAxis: root.xAxis
            yAxis: root.yAxis
            markers: root.markers
            referenceLines: root.referenceLines
            referenceBands: root.referenceBands
            showLegend: root.showLegend
            emptyText: root.emptyText
            emptyReason: root.emptyReason
        }
    }
    Component {
        id: barComponent
        BarChart {
            anchors.fill: parent
            objectName: "readoutBarChart"
            dataRevision: root.dataRevision
            inspectionEnabled: root.inspectionEnabled
            interactive: root.interactive
            busy: root.busy
            categories: root.categories
            xMode: root.xMode
            yAxis: root.yAxis
            limitLine: root.limitLine
            referenceValues: root.referenceValues
            bandRamp: root.bandRamp
            colorScale: root.colorScale
            valueFormat: root.valueFormat
            xLabel: root.xLabel
            xUnit: root.xUnit
            emptyText: root.emptyText
            emptyReason: root.emptyReason
        }
    }
    Component {
        id: panelComponent
        PanelChart {
            anchors.fill: parent
            objectName: "chartPanel"
            dataRevision: root.dataRevision
            panels: root.panels
            showLegend:root.showLegend
            inspectionEnabled: root.inspectionEnabled
            interactive: root.interactive
            busy: root.busy
            emptyText: root.emptyText
            emptyReason: root.emptyReason
        }
    }
}
