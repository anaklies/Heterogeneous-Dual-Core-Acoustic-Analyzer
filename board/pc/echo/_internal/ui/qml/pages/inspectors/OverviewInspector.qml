import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../../components"

ColumnLayout {
    width: 264
    spacing: 10

    SectionTitle { text: App.t("overview.connection"); iconName: "plug-zap" }
    LabeledValue { label: App.t("settings.host"); value: App.connection.host || "—" }
    LabeledValue { label: App.t("settings.control_port"); value: String(App.connection.controlPort || "—") }
    LabeledValue { label: App.t("settings.binary_port"); value: String(App.connection.binaryPort || "—") }
    LabeledValue {
        label: "state"
        value: App.connectionStateLabel
        valueColor: App.connectionState === "connected" ? Theme.ok : Theme.warn
    }
    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
    SectionTitle { text: App.t("overview.features"); iconName: "grid-3x3" }
    LabeledValue { label: App.t("overview.available"); value: String(App.featureSummary.available) }
    LabeledValue { label: App.t("overview.experimental"); value: String(App.featureSummary.experimental) }
    LabeledValue { label: App.t("overview.not_ready"); value: String(App.featureSummary.not_ready) }
    LabeledValue { label: App.t("overview.unsupported"); value: String(App.featureSummary.unsupported) }
    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
    Text {
        Layout.fillWidth: true
        text: App.t("overview.scope_note")
        color: Theme.textDisabled
        visible: false
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(18 * Theme.fontScale)
        wrapMode: Text.Wrap
    }

    Item { Layout.fillHeight: true }
}
