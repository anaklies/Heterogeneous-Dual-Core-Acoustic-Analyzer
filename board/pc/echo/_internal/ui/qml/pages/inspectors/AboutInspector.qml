import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../../components"

ColumnLayout {
    width: 264
    spacing: 10

    SectionTitle { text: App.t("about.authors"); iconName: "users" }
    Text {
        text: "刘珉志、孟德旭"
        color: Theme.textPrimary
        font.family: Theme.fontFamilyCjk
        font.pixelSize: Math.round(20 * Theme.fontScale)
    }
    Text {
        text: "黑龙江大学"
        color: Theme.textSecondary
        font.family: Theme.fontFamilyCjk
        font.pixelSize: Math.round(18 * Theme.fontScale)
    }
    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
    LabeledValue { label: App.t("about.version"); value: App.version }
    LabeledValue { label: App.t("about.build"); value: App.buildDate }
    LabeledValue { label: "Qt"; value: "6.12" }
    LabeledValue { label: "Python"; value: "3.12" }
    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
    Text {
        Layout.fillWidth: true
        text: App.t("about.licenses")
        color: Theme.textDisabled
        visible: false
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(18 * Theme.fontScale)
        wrapMode: Text.Wrap
    }

    Item { Layout.fillHeight: true }
}
