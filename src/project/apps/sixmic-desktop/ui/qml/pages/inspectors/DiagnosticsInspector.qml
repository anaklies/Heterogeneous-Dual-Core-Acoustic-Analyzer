import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../../components"

ColumnLayout {
    width: 264
    spacing: 10

    SectionTitle { text: App.t("diagnostics.local"); iconName: "activity" }
    LabeledValue { label: "user data"; value: App.diagnosticsData.path || "—" }
    LabeledValue { label: "logs"; value: App.diagnosticsData.logsPath || "—" }
    LabeledValue { label: "app"; value: App.version }
    LabeledValue { label: "backend"; value: App.diagnosticsData.versions.backend || "—" }
    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
    AppButton {
        Layout.fillWidth: true
        text: App.t("diagnostics.refresh")
        iconName: "refresh-cw"
        compact: true
        onClicked: App.refreshDiagnostics()
    }
    AppButton {
        Layout.fillWidth: true
        text: App.t("diagnostics.open_logs")
        iconName: "folder-open"
        compact: true
        onClicked: App.openPath(App.userDataDirectory() + "/logs")
    }
    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
    Text {
        Layout.fillWidth: true
        text: App.t("about.disclaimer")
        color: Theme.textDisabled
        visible: false
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(18 * Theme.fontScale)
        wrapMode: Text.Wrap
    }

    Item { Layout.fillHeight: true }
}
