import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
Rectangle {
    id: root
    implicitHeight: 48
    color: Theme.chromeBg
    Rectangle { anchors.bottom: parent.bottom; height: 1; width: parent.width; color: Theme.border }
    RowLayout {
        anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 12; spacing: 10
        Icon { name: "audio-waveform"; size: 25; color: Theme.accent }
        Text { text: "ECHO"; color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: 19; font.weight: Font.DemiBold }
        Rectangle { width: 1; height: 20; color: Theme.border; Layout.leftMargin: 8; Layout.rightMargin: 8 }
        Text { visible: root.width > 1150; text: App.t("studio.instrument"); color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 13 }
        Item { Layout.fillWidth: true }
        SourceBadge { visible: App.dataSource === "test-fixture" && root.width > 1000; sourceKind: App.dataSource; label: App.t("studio.preview_only") }
        Rectangle { width: 5; height: 5; radius: 3; color: App.connectionState === "connected" ? Theme.ok : Theme.textDisabled }
        Text { visible: root.width > 800; text: App.connectionState === "connected" ? String(App.connection.host || "") : App.t("studio.disconnected")
            color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 13
            Layout.maximumWidth: 170; elide: Text.ElideMiddle }
        AppButton { compact: true; text: App.connectionState === "connected" ? App.t("studio.disconnect") : App.t("studio.connect")
            iconName: App.connectionState === "connected" ? "power" : "plug-zap"
            enabled: !App.busy
            onClicked: App.connectionState === "connected" ? App.disconnectDevice() : App.connectDevice(App.settings.host, 48120, 48121) }
        IconButton { visible: root.width > 760; iconName: "folder-open"; tooltip: App.t("studio.export_folder"); onClicked: App.openPath(App.userDataDirectory()+"/exports") }
        Rectangle { width: 1; height: 20; color: Theme.border }
        IconButton { iconName: "panel-right-open"; tooltip: App.t("studio.measurement_info"); selected: !App.inspectorCollapsed
            onClicked: { var w=Window.window; if(w && w.toggleInspector) w.toggleInspector(); else App.setInspectorCollapsed(!App.inspectorCollapsed); } }
        IconButton { iconName: "maximize-2"; tooltip: App.t("topbar.fullscreen"); onClicked: { var w=Window.window; if(w && w.toggleFullScreen) w.toggleFullScreen(); } }
        IconButton { iconName: "settings"; tooltip: App.t("topbar.settings"); onClicked: App.setCurrentPage("settings") }
    }
}
