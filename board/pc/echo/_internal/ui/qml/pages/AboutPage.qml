import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
Item {
    Flickable {
        id: viewport
        anchors.fill: parent; contentWidth: width; contentHeight: aboutColumn.implicitHeight+56
        clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; active: true }
    ColumnLayout {
        id: aboutColumn; x:28; y:28; width: viewport.width-56
        spacing: 22
        RowLayout {
            spacing: 12
            Icon { name: "audio-waveform"; size: 32; color: Theme.accent }
            Text { text: "ECHO"; color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: 28; font.weight: Font.Medium }
        }
        Text { text: App.t("studio.instrument"); color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 16 }
        LabeledValue { Layout.maximumWidth: 600; Layout.fillWidth: true; label: App.t("about.version"); value: App.aboutData.version }
        Text { Layout.fillWidth: true; text: String(App.aboutData.authors); color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: 14; wrapMode: Text.Wrap }
        Text { Layout.fillWidth: true; text: App.aboutData.school; color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 14; wrapMode: Text.Wrap }
        Text { Layout.fillWidth: true; text: App.aboutData.license; color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 13; wrapMode: Text.Wrap }
    }
    }
}
