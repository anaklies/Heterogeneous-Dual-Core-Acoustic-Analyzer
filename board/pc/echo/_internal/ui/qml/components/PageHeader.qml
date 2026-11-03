import QtQuick
import QtQuick.Layouts

GridLayout {
    id: root
    property string title: App.pageTitle
    property string subtitle: App.pageSubtitle
    property string sourceKind: App.dataSource
    default property alias content: actions.data
    columns: width < 760 ? 1 : 2
    columnSpacing: 16
    rowSpacing: 12
    Layout.minimumWidth: 0
    RowLayout {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        spacing: 10
        Text {
            objectName: "pageHeaderTitle"
            text: root.title
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: 20
            font.weight: Font.DemiBold
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            elide: Text.ElideRight
        }
        SourceBadge { implicitHeight: 20; sourceKind: root.sourceKind }
    }
    Flow {
        id: actions
        objectName: "pageHeaderActions"
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        Layout.preferredWidth: preferredActionWidth
        spacing: 8
        readonly property real preferredActionWidth: {
            var total = 0, count = 0;
            for (var i = 0; i < children.length; i++) {
                if (!children[i].visible) continue;
                total += children[i].implicitWidth;
                count++;
            }
            return total + Math.max(0, count - 1) * spacing;
        }
    }
}
