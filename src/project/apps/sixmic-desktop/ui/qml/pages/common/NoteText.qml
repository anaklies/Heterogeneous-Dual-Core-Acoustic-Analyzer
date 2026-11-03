// Small shared note text for the eight pages (page-local helper; not a design-system shadow).
import QtQuick
import QtQuick.Layouts

Text {
    property color textColor: Theme.textDisabled
    property int textSize: 11
    Layout.fillWidth: true
    color: textColor
    font.family: Theme.fontFamily
    font.pixelSize: textSize
    wrapMode: Text.Wrap
}
