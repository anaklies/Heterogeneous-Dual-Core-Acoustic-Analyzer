import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Button {
    id: root
    property string iconName: ""
    property string variant: "secondary"
    property bool compact: false
    property string tooltip: ""
    implicitHeight: compact ? 32 : 36
    implicitWidth: Math.max(36, row.implicitWidth + 24)
    leftPadding: 12; rightPadding: 12; topPadding: 4; bottomPadding: 4
    hoverEnabled: true
    Accessible.name: text
    font.family: Theme.fontFamily; font.pixelSize: 14
    ToolTip.visible: hovered && tooltip.length > 0
    ToolTip.text: tooltip; ToolTip.delay: 450
    background: Rectangle {
        radius: 4
        color: !root.enabled ? Theme.panelAlt : root.down ? Theme.pressed
             : root.variant === "primary" ? Theme.accentSoft : root.hovered ? Theme.hover : "transparent"
        border.width: root.variant === "ghost" ? 0 : 1
        border.color: root.activeFocus ? Theme.focusRing : root.variant === "primary" ? Theme.accent : Theme.border
    }
    contentItem: RowLayout {
        id: row; spacing: 7
        Icon { visible: root.iconName.length > 0; name: root.iconName; size: 17
            color: !root.enabled ? Theme.textDisabled : root.variant === "danger" ? Theme.error : root.variant === "primary" ? Theme.accent : Theme.textSecondary }
        Text { text: root.text; font: root.font; elide: Text.ElideRight
            color: !root.enabled ? Theme.textDisabled : root.variant === "danger" ? Theme.error : Theme.textPrimary
            verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true; Layout.minimumWidth: 0 }
    }
}
