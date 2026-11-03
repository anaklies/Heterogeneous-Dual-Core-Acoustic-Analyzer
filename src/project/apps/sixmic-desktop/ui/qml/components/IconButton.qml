import QtQuick
import QtQuick.Controls
Button {
    id: root
    property string iconName: ""
    property string tooltip: ""
    property int iconSize: 20
    property bool selected: false
    property bool busy: false
    implicitWidth: 36; implicitHeight: 36
    hoverEnabled: true
    ToolTip.visible: hovered && tooltip.length > 0
    ToolTip.text: tooltip; ToolTip.delay: 450
    Accessible.name: tooltip
    background: Rectangle {
        radius: 4
        color: root.down ? Theme.pressed : root.selected ? Theme.accentSoft : root.hovered ? Theme.hover : "transparent"
        border.width: root.activeFocus ? 1 : 0; border.color: Theme.focusRing
    }
    contentItem: Item {
        Icon { anchors.centerIn: parent; name: root.iconName; size: root.iconSize
            color: !root.enabled ? Theme.textDisabled : root.selected ? Theme.accent : Theme.textSecondary
            spinning: root.busy }
    }
}
