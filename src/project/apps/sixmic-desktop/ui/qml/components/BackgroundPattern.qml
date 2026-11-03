import QtQuick

/* Low-contrast engineering pattern backdrop for welcome/console cards only.
   Static SVG tiles (no continuous animation) to keep analysis views cheap. */
Item {
    id: root
    property string variant: "grid_tech"   // grid_tech | retro_grid | hex_tech
    property real strength: 0.5
    property color tint: Theme.accent
    property bool animated: false
    clip: true
    Image {
        id: tile
        anchors.fill: parent
        anchors.margins: -32
        source: App.assetSource("patterns/" + root.variant + ".svg")
        fillMode: Image.Tile
        asynchronous: true
        opacity: 0.55 * Math.max(0.2, Math.min(1.0, root.strength))
        smooth: true
        NumberAnimation on x {
            from: 0; to: -32; duration: 42000
            loops: Animation.Infinite
            running: root.animated && root.visible
            easing.type: Easing.InOutSine
        }
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.0) }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.0) }
        }
        color: "transparent"
    }
}
