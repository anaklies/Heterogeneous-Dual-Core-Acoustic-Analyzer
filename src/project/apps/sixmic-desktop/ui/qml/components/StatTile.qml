import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

ColumnLayout {
    id: root
    property string label: ""
    property string value: "—"
    property string unit: ""
    property string status: ""       // ok | warn | error | neutral
    property string hint: ""
    HoverHandler { id: valueHover; acceptedDevices: PointerDevice.Mouse }
    ToolTip.visible: valueHover.hovered
    ToolTip.text: root.label + " = " + root.value + (root.unit.length ? " " + root.unit : "")
    spacing: 3
    Layout.minimumWidth: 0
    RowLayout {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        spacing: 6
        Text {
            text: root.label
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
            Layout.fillWidth: true
            elide: Text.ElideRight
        }
        Rectangle {
            visible: root.status.length > 0 && root.status !== "neutral"
            width: 7; height: 7; radius: 4
            color: root.status === "ok" ? Theme.ok
                   : root.status === "warn" ? Theme.warn
                   : root.status === "error" ? Theme.error : Theme.textDisabled
            Layout.alignment: Qt.AlignVCenter
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        spacing: 4
        Text {
            text: root.value
            color: Theme.textPrimary
            font.family: Theme.fontMono
            font.pixelSize: Math.round(37 * Theme.fontScale)
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Layout.fillWidth: true
            Layout.minimumWidth: 0
        }
        Text {
            visible: root.unit.length > 0
            text: root.unit
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
            Layout.alignment: Qt.AlignBottom
            Layout.bottomMargin: 4
        }
    }
    Text {
        visible: false
        text: root.hint
        color: Theme.textDisabled
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(18 * Theme.fontScale)
        wrapMode: Text.WordWrap
        maximumLineCount: 2
        elide: Text.ElideRight
        Layout.fillWidth: true
    }
}
