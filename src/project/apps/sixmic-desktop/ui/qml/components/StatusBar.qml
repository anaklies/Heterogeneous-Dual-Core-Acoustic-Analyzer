import QtQuick
import QtQuick.Layouts
Rectangle {
    color: Theme.chromeBg
    implicitHeight: 28
    Rectangle { width: parent.width; height: 1; color: Theme.border }
    RowLayout {
        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14; spacing: 16
        Text { text: App.connectionStateLabel; color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 12 }
        Text { visible: App.audioSampleRate > 0; text: App.formatNumber(App.audioSampleRate) + " Hz"; color: Theme.textSecondary; font.family: Theme.fontMono; font.pixelSize: 12 }
        Text { text: App.t("studio.gaps") + " " + String(App.status.gaps || 0); color: Number(App.status.gaps || 0)>0 ? Theme.warn : Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 12 }
        Item { Layout.fillWidth: true }
        Text { text: App.dataSource === "test-fixture" ? App.t("studio.preview_only") : App.t("studio.pl_only"); color: App.dataSource === "test-fixture" ? Theme.warn : Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 12 }
    }
}
