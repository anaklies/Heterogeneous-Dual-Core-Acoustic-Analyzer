import QtQuick
import QtQuick.Layouts
RowLayout {
    id: root
    property string text: ""
    property string subtitle: ""
    property string iconName: ""
    property color accent: Theme.textSecondary
    Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 7
    Icon { visible: root.iconName.length > 0; name: root.iconName; size: 17; color: root.accent }
    Text { Layout.fillWidth: true; Layout.minimumWidth: 0; text: root.text; elide: Text.ElideRight
        color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: 15; font.weight: Font.Medium }
}
