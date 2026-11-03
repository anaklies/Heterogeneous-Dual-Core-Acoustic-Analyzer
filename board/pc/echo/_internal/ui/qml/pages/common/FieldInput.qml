// Single-line text input (QtQuick primitives only) for report title / directory fields.
import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    property alias text: input.text
    property string placeholder: ""
    property int inputFontSize: 13
    readonly property bool editing: input.activeFocus
    Layout.fillWidth: true
    implicitHeight: 34
    radius: Theme.radiusControl
    color: Theme.panelAlt
    border.width: 1
    border.color: input.activeFocus ? Theme.focusRing : Theme.border

    TextInput {
        id: input
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: root.inputFontSize
        selectionColor: Theme.selection
        selectedTextColor: Theme.textPrimary
        clip: true
        readOnly: !root.enabled
    }
    Text {
        visible: input.text.length === 0 && root.placeholder.length > 0
        text: root.placeholder
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        anchors.leftMargin: 10
        color: Theme.textDisabled
        font.family: Theme.fontFamily
        font.pixelSize: root.inputFontSize
    }
}
