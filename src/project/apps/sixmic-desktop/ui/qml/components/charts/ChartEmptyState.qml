// ChartEmptyState - explicit chart no-data / invalid state. Never draws fake data.
// Named ChartEmptyState (not EmptyState) so importing "../components" and
// "../components/charts" together cannot shadow the shared UI EmptyState type.
import QtQuick

Item {
    id: root
    property string text: ""
    property string reason: ""
    property bool busy: false
    property string busyText: ""

    readonly property var st: ({
        dim: Theme.plotTextDim,
        bg: Theme.plotBg,
        font: Theme.fontFamily,
        fs: Math.max(12, Math.round(13 * Theme.fontScale)),
        fsSmall: Math.max(11, Math.round(12 * Theme.fontScale))
    })
    Rectangle {
        anchors.fill: parent
        color: root.st.bg
    }
    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 32, 520)
        spacing: 6
        Text {
            width: parent.width
            text: root.busy ? (root.busyText.length ? root.busyText : root.text) : root.text
            color: root.st.dim
            font.family: root.st.font
            font.pixelSize: root.st.fs
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            width: parent.width
            visible: !root.busy && text.length > 0
            text: root.reason
            color: root.st.dim
            opacity: 0.85
            font.family: root.st.font
            font.pixelSize: root.st.fsSmall
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
    }
}