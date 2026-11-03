import QtQuick
import QtQuick.Layouts

Panel {
    id: root
    property string title: ""
    default property alias plotContent: plotHost.data
    Layout.minimumWidth: 0
    padding: 10
    ColumnLayout {
        anchors.fill: parent
        spacing: 7
        SectionTitle { text: root.title }
        Item {
            id: plotHost
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0
            clip: true
        }
    }
}
