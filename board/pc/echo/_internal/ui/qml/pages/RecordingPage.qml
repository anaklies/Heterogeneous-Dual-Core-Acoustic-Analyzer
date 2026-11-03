import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
Item {
    id: page
    property var record: App.recordingData.recording || ({})
    Flickable {
        id: viewport
        anchors.fill: parent; contentWidth: width; contentHeight: Math.max(height,440)
        clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; active: true }
    ColumnLayout {
        width: viewport.width-48; x:24; y:24; height: viewport.contentHeight-48; spacing: 16
        RowLayout {
            Layout.fillWidth: true
            SectionTitle { text: App.t("studio.nav.recording"); iconName: "hard-drive" }
            AppButton { text: page.record.state === "recording" ? App.t("studio.stop_record") : App.t("studio.start_record")
                iconName: page.record.state === "recording" ? "square" : "circle"
                enabled: page.record.state === "recording" || App.plInterface.canRecord
                onClicked: page.record.state === "recording" ? App.stopRecording() : App.startRecording() }
            AppButton { objectName: "exportDeviceRecording"; text: App.t("studio.export"); iconName: "download"
                enabled: App.connectionState === "connected" && String(page.record.records || "0") !== "0"
                onClicked: App.exportRecordingData(App.userDataDirectory()+"/exports") }
        }
        Panel {
            Layout.fillWidth: true; Layout.preferredHeight: 192
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 8; spacing: 14
                LabeledValue { Layout.fillWidth: true; label: App.t("studio.state"); value: App.t("recording_extra.state_" + String(page.record.state || "idle")) }
                LabeledValue { Layout.fillWidth: true; label: App.t("recording_extra.records"); value: String(page.record.records || "0") }
                LabeledValue { Layout.fillWidth: true; label: App.t("recording_extra.bytes"); value: String(page.record.bytes || "0") }
                LabeledValue { Layout.fillWidth: true; label: App.t("studio.gaps"); value: String(page.record.gaps || "0") }
                SourceBadge { sourceKind: App.dataSource; label: App.dataSourceLabel }
            }
        }
        Text { Layout.fillWidth: true; text: App.t("studio.record_hint"); font.family: Theme.fontFamily; font.pixelSize: 14; color: Theme.textSecondary; wrapMode: Text.Wrap }
        AppButton { text: App.t("studio.open_acquisition"); iconName: "audio-waveform"; onClicked: App.setCurrentPage("time") }
        Item { Layout.fillHeight: true }
    }
    }
}
