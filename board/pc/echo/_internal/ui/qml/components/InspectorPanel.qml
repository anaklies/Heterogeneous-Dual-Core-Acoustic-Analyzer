import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Rectangle {
    id: root
    property string pageId: App.currentPage
    property string inspectorSource: ""
    property bool forceOpen: false
    signal collapseRequested()
    implicitWidth: 264
    color: Theme.chromeBg
    property var measurement: App.featureWorkspace || ({})
    Flickable {
        id: infoScroll
        anchors.fill: parent; contentWidth: width; contentHeight: Math.max(height,infoColumn.implicitHeight+28)
        clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; active: true }
    ColumnLayout {
        id: infoColumn; x:14; y:14; width: infoScroll.width-28; height: Math.max(infoScroll.height-28,implicitHeight); spacing: 14
        RowLayout {
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: App.t("studio.measurement_info"); color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: 14 }
            IconButton { objectName: "collapseInspectorButton"; iconName: "panel-right-close"; iconSize: 26
                implicitWidth: 44; implicitHeight: 44; tooltip: App.t("inspector.collapse")
                onClicked: { App.setInspectorCollapsed(true); root.collapseRequested(); } }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        Text { Layout.fillWidth: true; text: String(root.measurement.shortName || root.measurement.name || App.pageTitle)
            font.family: Theme.fontFamily; font.pixelSize: 16; font.weight: Font.Medium; color: Theme.textPrimary; wrapMode: Text.Wrap }
        SourceBadge { Layout.fillWidth: true; sourceKind: root.measurement.sourceKind || App.dataSource; label: root.measurement.sourceLabel || App.dataSourceLabel }
        LabeledValue { Layout.fillWidth: true; label: App.t("studio.state"); value: String(root.measurement.stateLabel || App.connectionStateLabel || "—") }
        LabeledValue { Layout.fillWidth: true; label: App.t("studio.units"); value: String(((root.measurement.chart || {}).colorScale || {}).unit || ((root.measurement.chart || {}).yAxis || {}).unit || "—") }
        LabeledValue { Layout.fillWidth: true; label: App.t("status.sample_rate"); value: App.audioSampleRate ? App.formatNumber(App.audioSampleRate) + " Hz" : "—" }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        Text { Layout.fillWidth: true; text: App.t("studio.device_params"); color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 13; wrapMode: Text.Wrap }
        Item { Layout.fillHeight: true }
        AppButton { Layout.fillWidth: true; text: App.t("studio.diagnostics"); iconName: "activity"; variant: "ghost"; onClicked: App.setCurrentPage("diagnostics") }
    }
    }
}
