import QtQuick
Rectangle {
    id: root
    property bool elevated: false
    property bool plot: false
    property int padding: 14
    default property alias content: inner.data
    color: plot ? Theme.plotBg : Theme.panelBg
    gradient:Gradient {
        GradientStop {position:0;color:root.plot?Theme.plotBg:Qt.lighter(Theme.panelBg,1.065)}
        GradientStop {position:1;color:root.plot?Theme.plotBg:Theme.panelBg}
    }
    radius: Theme.radiusPanel; border.width: 1; border.color: Theme.border
    clip: true
    // Explicit hint only: a fill-anchored child's implicit size may depend on us.
    property real preferredContentHeight: 160
    implicitHeight: preferredContentHeight + padding * 2
    Item { id: inner; anchors.fill: parent; anchors.margins: root.padding }
}
