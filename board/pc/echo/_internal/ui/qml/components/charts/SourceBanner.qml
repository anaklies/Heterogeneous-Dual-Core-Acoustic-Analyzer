import QtQuick
import QtQuick.Controls
Item {
    id: root
    property string sourceKind: ""
    property string sourceLabel: ""
    property string validity: ""
    property var notes: []
    implicitHeight: 22
    Text {
        anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        text: root.sourceLabel.length ? root.sourceLabel : root.sourceKind === "test-fixture" ? (typeof App !== "undefined" ? App.t("studio.preview_only") : "Test fixture") : ""
        font.family: Theme.fontFamily; font.pixelSize: 12
        color: root.sourceKind === "test-fixture" ? Theme.warn : Theme.textSecondary
        elide: Text.ElideRight
    }
    HoverHandler { id: hover }
    ToolTip.visible: hover.hovered && root.validity.length > 0
    ToolTip.text: root.validity; ToolTip.delay: 500
}
