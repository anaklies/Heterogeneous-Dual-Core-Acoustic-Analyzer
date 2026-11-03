// CapabilityPanel - capability / limitation text panel (directed DAS interface
// capabilities, raw-word fallbacks). The text comes from the payload; this
// component never invents measurements or enables automatic DOA.
import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property string text: ""
    property var rows: []
    property string caption: ""
    property string emptyText: ""
    property string emptyReason: ""
    property bool busy: false

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        Text {
            Layout.fillWidth: true
            text: root.text
            visible: text.length > 0
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
            wrapMode: Text.Wrap
        }
        ScalarReadout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 40
            rows: root.rows
            busy: root.busy
            emptyText: root.emptyText
            emptyReason: root.emptyReason
        }
        Text {
            Layout.fillWidth: true
            text: root.caption
            visible: text.length > 0
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
            wrapMode: Text.Wrap
            maximumLineCount: 3
            elide: Text.ElideRight
        }
    }
}
