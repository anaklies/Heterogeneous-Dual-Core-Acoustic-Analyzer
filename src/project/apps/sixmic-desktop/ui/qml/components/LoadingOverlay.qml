import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    visible: App.busy
    color: Qt.rgba(0.07, 0.10, 0.13, 0.42)
    z: 900
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; hoverEnabled: true }
    Rectangle {
        anchors.centerIn: parent
        width: row.implicitWidth + 32
        height: 44
        radius: Theme.radiusPanel
        color: Theme.panelBg
        border.width: 1
        border.color: Theme.border
        RowLayout {
            id: row
            anchors.centerIn: parent
            spacing: 10
            Icon { name: "loader-circle"; size: 18; color: Theme.accent; spinning: true }
            Text {
                text: App.busyText.length > 0 ? App.busyText : App.t("busy.connecting")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(18 * Theme.fontScale)
            }
        }
    }
}
