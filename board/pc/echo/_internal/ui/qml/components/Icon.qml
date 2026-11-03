import QtQuick
import QtQuick.Window

Item {
    id: root
    property string name: ""
    property int size: 28
    property color color: Theme.textSecondary
    property bool spinning: false
    implicitWidth: size
    implicitHeight: size
    width: size
    height: size
    Image {
        id: image
        anchors.fill: parent
        source: App.iconSource(root.name, root.color.toString())
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: false
        sourceSize.width: root.size * Math.max(2, Screen.devicePixelRatio)
        sourceSize.height: root.size * Math.max(2, Screen.devicePixelRatio)
    }
    RotationAnimation on rotation {
        running: root.spinning
        from: 0; to: 360; duration: 900; loops: Animation.Infinite
    }
}
