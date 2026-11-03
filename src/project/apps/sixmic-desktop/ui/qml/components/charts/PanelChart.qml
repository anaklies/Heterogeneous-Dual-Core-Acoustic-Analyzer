// PanelChart - one or two stacked chart panels for dual-panel payloads
// (coherence + phase, frequency weighting + time weighting, PSD + CSD, ...).
// Panel config keys mirror the single-chart contract:
//   {render:"line"|"bars", title, subtitle, series, categories, xAxis, yAxis,
//    markers, referenceLines, referenceBands, limitLine, referenceValues,
//    showLegend, emptyText, emptyReason, bandRamp, colorScale, valueFormat,
//    xMode, xLabel, xUnit}
// No acoustic calculation: panels are display routing only.
import QtQuick
import QtQuick.Layouts
import "ChartUtil.js" as U

Item {
    id: root
    property bool inspectionEnabled: false
    property bool showLegend:true
    property var panels: []
    property int gap: 8
    property int dataRevision: 0
    property bool interactive: true
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""

    readonly property var validPanels: {
        var out = []
        var list = panels || []
        for (var i = 0; i < list.length && i < 3; i++) {
            if (list[i] && typeof list[i] === "object") out.push(list[i])
        }
        return out
    }
    readonly property int panelCount: validPanels.length

    ColumnLayout {
        anchors.fill: parent
        spacing: root.gap
        visible: root.validPanels.length > 0

        Repeater {
            model: root.panelCount
            delegate: ColumnLayout {
                id: panelColumn
                required property int index
                readonly property var modelData: root.validPanels[index] || ({})
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 60
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: panelColumn.modelData && panelColumn.modelData.title !== undefined
                          ? String(panelColumn.modelData.title) : ""
                    visible: text.length > 0
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }
                Text {
                    Layout.fillWidth: true
                    text: panelColumn.modelData && panelColumn.modelData.subtitle !== undefined
                          ? String(panelColumn.modelData.subtitle) : ""
                    visible: false
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }
                Item {
                    id: chartHost
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 50
                    readonly property var cfg: panelColumn.modelData || ({})
                    readonly property bool bars: cfg.render === "bars"
                    LineChart {
                        anchors.fill: parent
                        objectName: "panelLineChart"
                        visible: !chartHost.bars
                        dataRevision: root.dataRevision
                        inspectionEnabled: root.inspectionEnabled
                        interactive: root.interactive
                        busy: root.busy
                        series: chartHost.cfg.series || []
                        xAxis: chartHost.cfg.xAxis || null
                        yAxis: chartHost.cfg.yAxis || null
                        markers: chartHost.cfg.markers || []
                        referenceLines: chartHost.cfg.referenceLines || []
                        referenceBands: chartHost.cfg.referenceBands || []
                        showLegend: root.showLegend && (chartHost.cfg.showLegend === undefined ? true : chartHost.cfg.showLegend)
                        emptyText: chartHost.cfg.emptyText !== undefined && String(chartHost.cfg.emptyText).length
                                   ? String(chartHost.cfg.emptyText) : root.emptyText
                        emptyReason: chartHost.cfg.emptyReason !== undefined && String(chartHost.cfg.emptyReason).length
                                     ? String(chartHost.cfg.emptyReason) : root.emptyReason
                    }
                    BarChart {
                        anchors.fill: parent
                        objectName: "panelBarChart"
                        visible: chartHost.bars
                        dataRevision: root.dataRevision
                        inspectionEnabled: root.inspectionEnabled
                        interactive: root.interactive
                        busy: root.busy
                        categories: chartHost.cfg.categories || []
                        xMode: chartHost.cfg.xMode || "category"
                        yAxis: chartHost.cfg.yAxis || null
                        limitLine: chartHost.cfg.limitLine || null
                        referenceValues: chartHost.cfg.referenceValues || []
                        bandRamp: chartHost.cfg.bandRamp || []
                        colorScale: chartHost.cfg.colorScale || null
                        valueFormat: chartHost.cfg.valueFormat || ""
                        xLabel: chartHost.cfg.xLabel || ""
                        xUnit: chartHost.cfg.xUnit || ""
                        emptyText: chartHost.cfg.emptyText !== undefined && String(chartHost.cfg.emptyText).length
                                   ? String(chartHost.cfg.emptyText) : root.emptyText
                        emptyReason: chartHost.cfg.emptyReason !== undefined && String(chartHost.cfg.emptyReason).length
                                     ? String(chartHost.cfg.emptyReason) : root.emptyReason
                    }
                }
            }
        }
    }

    ChartEmptyState {
        anchors.fill: parent
        visible: root.validPanels.length === 0
        text: root.emptyText
        reason: root.emptyReason
        busy: root.busy
    }
}
