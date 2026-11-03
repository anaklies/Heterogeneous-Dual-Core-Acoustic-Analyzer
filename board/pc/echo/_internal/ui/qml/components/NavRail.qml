import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
Rectangle {
    id: root
    readonly property bool compact: App.navCollapsed || (Window.window && Window.window.width < 1080)
    implicitWidth: compact ? 58 : 172
    Layout.preferredWidth: implicitWidth
    color: Theme.chromeBg
    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 8; spacing: 3
        IconButton { iconName: "panel-left-close"; tooltip: App.t("studio.navigation"); onClicked: App.setNavCollapsed(!App.navCollapsed) }
        Flickable {
            id: navigationScroll
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 0
            contentWidth: width; contentHeight: navigation.implicitHeight
            clip: true; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; active: true; width: 4 }
            ColumnLayout {
                id: navigation; width: navigationScroll.width; spacing: 3
        Repeater {
            model: App.navPages
            delegate: Button {
                id: entry
                required property var modelData
                property bool active: App.currentPage === modelData.id
                Layout.fillWidth: true; Layout.preferredHeight: 38
                hoverEnabled: true
                onClicked: App.setCurrentPage(modelData.id)
                background: Rectangle {
                    radius: 3; color: entry.active ? Theme.accentSoft : entry.hovered ? Theme.hover : "transparent"
                    Rectangle { width: 2; height: 18; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; color: entry.active ? Theme.accent : "transparent" }
                }
                contentItem: RowLayout {
                    spacing: 10
                    Icon { name: entry.modelData.icon; size: 20; color: entry.active ? Theme.accent : Theme.textSecondary }
                    Text { visible: !root.compact; Layout.fillWidth: true; Layout.minimumWidth: 0
                        text: App.t("studio.nav." + entry.modelData.id); elide: Text.ElideRight
                        font.family: Theme.fontFamily; font.pixelSize: 14; color: entry.active ? Theme.textPrimary : Theme.textSecondary }
                }
                ToolTip.visible: hovered && root.compact; ToolTip.text: App.t("studio.nav." + modelData.id); ToolTip.delay: 400
                Accessible.name: App.t("studio.nav." + modelData.id)
            }
        }
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        Repeater {
            model: App.bottomPages
            delegate: Button {
                id: bottom
                required property var modelData
                Layout.fillWidth: true; Layout.preferredHeight: 36
                onClicked: App.setCurrentPage(modelData.id)
                hoverEnabled: true
                background: Rectangle { color: bottom.hovered ? Theme.hover : "transparent"; radius: 3 }
                contentItem: RowLayout {
                    spacing: 10
                    Icon { name: bottom.modelData.icon; size: 19; color: Theme.textSecondary }
                    Text { visible: !root.compact; Layout.fillWidth: true; text: bottom.modelData.label; color: Theme.textSecondary
                        font.family: Theme.fontFamily; font.pixelSize: 13; elide: Text.ElideRight }
                }
                ToolTip.visible: hovered && root.compact; ToolTip.text: modelData.label
            }
        }
    }
}
