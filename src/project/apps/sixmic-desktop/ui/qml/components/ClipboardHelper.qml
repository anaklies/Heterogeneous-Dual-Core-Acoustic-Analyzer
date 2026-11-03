import QtQuick
import QtQuick.Controls

Item {
    function copy(text) {
        clipboard.text = String(text)
        clipboard.selectAll()
        clipboard.copy()
    }
    TextEdit {
        id: clipboard
        visible: false
    }
}
