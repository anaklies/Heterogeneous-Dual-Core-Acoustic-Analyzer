import QtQuick
import QtQuick.Layouts
import "../../components"

ColumnLayout {
    width: 264
    spacing: 10
    SectionTitle { text: App.t("advanced.title"); iconName: "tools" }
    Text {
        text: App.t("advanced.not_connected")
        color: Theme.warn
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(18 * Theme.fontScale)
        wrapMode: Text.Wrap
        Layout.fillWidth: true
    }
    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
    Repeater {
        model: [
            { label: "periodic", title: App.t("advanced.periodic") },
            { label: "room", title: App.t("advanced.room") }
        ]
        delegate: LabeledValue {
            label: modelData.title
            value: App.t("status.not_connected")
            valueColor: Theme.warn
        }
    }
    Item { Layout.fillHeight: true }
}
