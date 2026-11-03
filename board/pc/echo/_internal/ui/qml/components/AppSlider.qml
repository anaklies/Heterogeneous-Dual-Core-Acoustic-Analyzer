import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string label: ""
    property real from: 0
    property real to: 100
    property real stepSize: 1
    property real value: 0
    property string valueText: ""
    property bool integer: false
    signal edited(real value)
    spacing: 2
    RowLayout {
        Layout.fillWidth: true
        Text {
            text: root.label
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
            Layout.fillWidth: true
        }
        Text {
            text: root.valueText.length > 0 ? root.valueText
                  : (root.integer ? Math.round(root.value).toString() : root.value.toFixed(2))
            color: Theme.textPrimary
            font.family: Theme.fontMono
            font.pixelSize: Math.round(18 * Theme.fontScale)
        }
    }
    Slider {
        id: slider
        Layout.fillWidth: true
        from: root.from
        to: root.to
        stepSize: root.stepSize
        value: root.value
        onMoved: root.edited(value)
        background: Rectangle {
            x: slider.leftPadding
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            implicitWidth: 160
            implicitHeight: 3
            width: slider.availableWidth
            height: 3
            radius: 2
            color: Theme.border
            Rectangle {
                width: slider.visualPosition * parent.width
                height: parent.height
                radius: 2
                color: Theme.accent
            }
        }
        handle: Rectangle {
            x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            implicitWidth: 14
            implicitHeight: 14
            radius: 7
            color: Theme.panelBg
            border.width: 2
            border.color: Theme.accent
        }
    }
}
