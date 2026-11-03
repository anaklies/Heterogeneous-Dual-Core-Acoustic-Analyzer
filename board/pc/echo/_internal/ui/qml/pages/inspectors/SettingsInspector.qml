import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../../components"

ColumnLayout {
    width: 264
    spacing: 10

    SectionTitle { text: App.t("settings.title"); iconName: "settings" }
    LabeledValue { label: App.t("settings.language"); value: App.language === "zh" ? App.t("language.zh") : App.t("language.en") }
    LabeledValue { label: App.t("settings.theme"); value: App.t("theme." + App.themeMode) }
    LabeledValue { label: App.t("settings.host"); value: App.settings.host }
    LabeledValue { label: App.t("settings.control_port"); value: String(App.settings.controlPort) }
    LabeledValue { label: App.t("settings.binary_port"); value: String(App.settings.binaryPort) }
    LabeledValue { label: App.t("settings.time_window"); value: Number(App.settings.timeWindowSeconds).toFixed(1) + " s" }
    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
    Text {
        Layout.fillWidth: true
        text: App.t("settings.restart_hint")
        color: Theme.textDisabled
        visible: false
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(18 * Theme.fontScale)
        wrapMode: Text.Wrap
    }
    AppButton {
        Layout.fillWidth: true
        text: App.t("settings.open_dir")
        iconName: "folder"
        compact: true
        onClicked: App.openPath(App.userDataDirectory())
    }

    Item { Layout.fillHeight: true }
}
