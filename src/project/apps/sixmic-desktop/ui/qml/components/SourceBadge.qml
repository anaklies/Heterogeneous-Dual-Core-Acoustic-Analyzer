import QtQuick
import QtQuick.Layouts
Rectangle {
    id: root
    property string sourceKind: App.dataSource
    property string label: App.dataSourceLabel
    implicitWidth: Math.min(190, row.implicitWidth + 16)
    implicitHeight: 24
    radius: 3; color: "transparent"
    RowLayout {
        id: row; anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8; spacing: 6
        Rectangle { width: 5; height: 5; radius: 3; color: root.sourceKind === "test-fixture" ? Theme.warn : root.sourceKind === "pl-live" ? Theme.ok : Theme.textDisabled }
        Text { Layout.fillWidth: true; Layout.minimumWidth: 0; text: root.label; elide: Text.ElideRight
            color: root.sourceKind === "test-fixture" ? Theme.warn : Theme.textSecondary
            font.family: Theme.fontFamily; font.pixelSize: 12 }
    }
}
