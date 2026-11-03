import QtQuick
import QtQuick.Layouts
RowLayout {
    id: root
    property string label: ""
    property string value: "—"
    property color valueColor: Theme.textPrimary
    property bool mono: true
    spacing: 10
    Text { Layout.fillWidth: true; Layout.minimumWidth: 0; text: root.label; color: Theme.textSecondary
        font.family: Theme.fontFamily; font.pixelSize: 13; elide: Text.ElideRight }
    Text { Layout.minimumWidth: 0; Layout.maximumWidth: 160; text: root.value; color: root.valueColor
        font.family: root.mono ? Theme.fontMono : Theme.fontFamily; font.pixelSize: 13; elide: Text.ElideRight; horizontalAlignment: Text.AlignRight }
}
