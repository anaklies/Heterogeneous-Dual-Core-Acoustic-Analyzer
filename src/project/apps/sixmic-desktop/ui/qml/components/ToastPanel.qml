import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    property var toastData: App.toast
    visible: toastData.visible === true
    opacity: visible ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 140 } }
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 46
    width: Math.min(560, content.implicitWidth + 40)
    height: content.implicitHeight + 20
    radius: Theme.radiusPanel
    color: Theme.panelBg
    border.width: 1
    border.color: toastData.level === "error" ? Theme.error
                 : toastData.level === "warn" ? Theme.warn
                 : toastData.level === "info" ? Theme.info : Theme.border
    z: 1000
    RowLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 12
        Icon {
            name: toastData.level === "error" ? "circle-x"
                 : toastData.level === "warn" ? "triangle-alert" : "info"
            size: 18
            color: toastData.level === "error" ? Theme.error
                  : toastData.level === "warn" ? Theme.warn : Theme.info
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Text {
                text: root.toastData.title || ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(18 * Theme.fontScale)
                font.weight: Font.DemiBold
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            Text {
                visible: (root.toastData.detail || "").length > 0
                text: root.toastData.detail || ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(18 * Theme.fontScale)
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }
    }
}
