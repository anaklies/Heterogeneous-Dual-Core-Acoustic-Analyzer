import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    id: root
    property var options: []          // [{value: any, label: string}]
    property var current: null
    property bool compact: false
    signal selected(var value)
    spacing: 6
    Repeater {
        model: root.options
        delegate: Button {
            id: chip
            property bool active: root.current === modelData.value
            text: modelData.label
            hoverEnabled: true
            implicitHeight: 32
            leftPadding: 10
            rightPadding: 10
            font.family: Theme.fontFamily
            font.pixelSize: Math.round((root.compact ? 15 : 17) * Theme.fontScale)
            onClicked: root.selected(modelData.value)
            background: Rectangle {
                radius: Theme.radiusControl
                color: chip.active ? Theme.accentSoft : (chip.hovered ? Theme.hover : Theme.panelAlt)
                border.width: 1
                border.color: chip.active ? Theme.accent : Theme.border
            }
            contentItem: Text {
                text: chip.text
                color: chip.active ? Theme.accent : Theme.textSecondary
                font: chip.font
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
        }
    }
}
