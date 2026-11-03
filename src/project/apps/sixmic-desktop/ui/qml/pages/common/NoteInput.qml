// Multi-line plain-text input (QtQuick TextEdit) for the report note field.
import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    property alias text: edit.text
    property string placeholder: ""
    readonly property bool editing: edit.activeFocus
    Layout.fillWidth: true
    implicitHeight: 88
    radius: Theme.radiusControl
    color: Theme.panelAlt
    border.width: 1
    border.color: edit.activeFocus ? Theme.focusRing : Theme.border

    TextEdit {
        id: edit
        anchors.fill: parent
        anchors.margins: 10
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(18 * Theme.fontScale)
        selectionColor: Theme.selection
        selectedTextColor: Theme.textPrimary
        wrapMode: TextEdit.Wrap
        textFormat: TextEdit.PlainText
        selectByMouse: true
        clip: true
        readOnly: !root.enabled
    }
    Text {
        visible: edit.text.length === 0 && root.placeholder.length > 0
        text: root.placeholder
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.topMargin: 10
        anchors.leftMargin: 10
        color: Theme.textDisabled
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(18 * Theme.fontScale)
    }
}
