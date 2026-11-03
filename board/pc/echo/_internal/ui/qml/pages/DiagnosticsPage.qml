import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
Item {
    Flickable {
        anchors.fill: parent; anchors.margins: 24; contentWidth: width; contentHeight: column.implicitHeight; clip: true
        ColumnLayout {
            id: column; width: Math.min(parent.width, 780); spacing: 18
            RowLayout {
                Layout.fillWidth: true
                SectionTitle { text: App.t("studio.diagnostics"); iconName: "activity" }
                AppButton { text: App.t("studio.refresh"); iconName: "refresh-cw"; compact: true; onClicked: App.refreshDiagnostics() }
            }
            LabeledValue { Layout.fillWidth: true; label: App.t("studio.state"); value: App.connectionStateLabel }
            LabeledValue { Layout.fillWidth: true; label: App.t("studio.device_address"); value: String(App.connection.host || "—") }
            LabeledValue { Layout.fillWidth: true; label: App.t("studio.api"); value: String(App.featureStatus.interfaceVersion || App.featureStatus.apiVersion || "—") }
            Text { Layout.fillWidth: true; text: String(App.featureStatus.deviceSoftwareNote || ""); color: Theme.warn; font.family: Theme.fontFamily; font.pixelSize: 14; wrapMode: Text.Wrap }
            Text { Layout.fillWidth: true; text: String(App.featureWorkspace.disabledReason || ""); color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 14; wrapMode: Text.Wrap }
            AppButton { text: App.t("studio.save_diagnostics"); iconName: "download"; onClicked: App.saveDiagnosticsReport(App.userDataDirectory()+"/exports") }
            Text { text: App.t("studio.diagnostics_note"); Layout.fillWidth: true; color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 13; wrapMode: Text.Wrap }
        }
    }
}
