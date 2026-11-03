import QtQuick
import QtQuick.Layouts
import "../../components"
ColumnLayout {
    width: 264; spacing: 10
    SectionTitle { text: App.t("pl.recording"); iconName: "hard-drive" }
    LabeledValue { Layout.fillWidth: true; label: App.t("inspector.source"); value: App.dataSourceLabel }
    LabeledValue { Layout.fillWidth: true; label: App.t("recording_extra.records"); value: String(App.recordingData.recording.records || "0") }
    Text {
        Layout.fillWidth: true; text: App.t("pl.record_note")
        color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Math.round(18 * Theme.fontScale)
        wrapMode: Text.Wrap
    }
    Item { Layout.fillHeight: true }
}
