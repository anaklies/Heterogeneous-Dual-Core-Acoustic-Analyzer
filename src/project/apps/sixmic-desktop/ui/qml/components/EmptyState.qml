import QtQuick
import QtQuick.Layouts
Item {
    id: root
    property string title: ""
    property string reason: ""
    property string hint: ""
    property string iconName: "activity"
    ColumnLayout {
        anchors.centerIn: parent
        width: Math.max(40,Math.min(500,parent.width-32)); spacing: 10
        Icon { Layout.alignment: Qt.AlignHCenter; name: root.iconName; size: 30; color: Theme.textDisabled }
        Text { Layout.fillWidth: true; text: root.title; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
            font.family: Theme.fontFamily; font.pixelSize: 18; font.weight: Font.Medium; color: Theme.textPrimary }
        Text { Layout.fillWidth: true; visible: root.reason.length>0; text: root.reason; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
            font.family: Theme.fontFamily; font.pixelSize: 14; color: Theme.textSecondary }
        Text { Layout.fillWidth: true; visible: root.hint.length>0; text: root.hint; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
            font.family: Theme.fontFamily; font.pixelSize: 13; color: Theme.textSecondary }
    }
}
