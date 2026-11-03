// Two-row CH1..CH6 picker that fits the 264px inspector column.
import QtQuick
import QtQuick.Layouts
import "../../components"

ColumnLayout {
    id: root
    property int current: 0
    property string label: ""
    signal channelSelected(int value)
    Layout.fillWidth: true
    spacing: 6

    function optionsFor(start) {
        var out = []
        for (var i = start; i < start + 3; i++) {
            out.push({ value: i, label: "CH" + (i + 1) })
        }
        return out
    }
    Text {
        visible: root.label.length > 0
        text: root.label
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(18 * Theme.fontScale)
    }
    ChoiceChips {
        Layout.fillWidth: true
        options: root.optionsFor(0)
        current: root.current
        compact: true
        onSelected: function(value) { root.channelSelected(value) }
    }
    ChoiceChips {
        Layout.fillWidth: true
        options: root.optionsFor(3)
        current: root.current
        compact: true
        onSelected: function(value) { root.channelSelected(value) }
    }
}
