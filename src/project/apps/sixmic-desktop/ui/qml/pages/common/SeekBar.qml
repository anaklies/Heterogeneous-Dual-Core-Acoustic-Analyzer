// One-way playback seek bar: backend position in, user seek out (no two-way value binding).
import QtQuick

Item {
    id: root
    property real position: 0          // normalized 0..1 from backend (never used as a sample index)
    property real dragPosition: 0
    property bool dragging: false
    property real visualPosition: Math.max(0, Math.min(1, root.dragging ? root.dragPosition : root.position))
    signal seek(real value)
    implicitHeight: 22

    Rectangle {
        id: track
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        height: 4
        radius: 2
        color: Theme.border
        Rectangle {
            width: root.visualPosition * track.width
            height: track.height
            radius: 2
            color: Theme.accent
        }
    }
    Rectangle {
        id: handle
        width: 12
        height: 12
        radius: 6
        anchors.verticalCenter: parent.verticalCenter
        x: Math.max(0, Math.min(root.width - width, root.visualPosition * root.width - width / 2))
        color: Theme.panelBg
        border.width: 2
        border.color: Theme.accent
    }
    MouseArea {
        anchors.fill: parent
        function valueAt(mx) {
            return Math.max(0, Math.min(1, mx / Math.max(1, root.width)))
        }
        onPressed: function(mouse) {
            root.dragging = true
            root.dragPosition = valueAt(mouse.x)
        }
        onPositionChanged: function(mouse) {
            if (root.dragging) root.dragPosition = valueAt(mouse.x)
        }
        onReleased: function(mouse) {
            root.dragging = false
            root.seek(valueAt(mouse.x))
        }
        onCanceled: root.dragging = false
    }
}
