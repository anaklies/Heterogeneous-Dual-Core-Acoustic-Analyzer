import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "ChartUtil.js" as U
Item {
    id: root
    property var rows: []
    property int columns: 0
    property bool interactive: false
    property bool busy: false
    property string emptyText: ""
    property string emptyReason: ""
    property string valueFormat: ""
    function valueText(row) {
        if(!row || row.valid===false || row.value===undefined || row.value===null)return "—";
        if(typeof row.value === "number")return U.fmtReadout(row.value,row.valueFormat || root.valueFormat);
        if(typeof row.value === "boolean" && typeof App !== "undefined")return App.t(row.value?"studio.yes":"studio.no");
        return String(row.value);
    }

    // Live chart frames deliver a brand-new rows array ~15x/s. Feeding that
    // array straight into ListView replaced the delegate model on every frame,
    // which snapped contentY back to 0 ("the list keeps being pulled back").
    // The rows therefore live in a ListModel that is updated in place while
    // the visible row set (label/unit order) is unchanged; only a real row-set
    // change rebuilds the model. Delegate visuals/text are unchanged.
    ListModel { id: rowStore }
    function normalizedRows() {
        var out = []
        var source = root.busy ? [] : (root.rows || [])
        for (var i = 0; i < source.length; i++) {
            var row = source[i]
            if (!row || typeof row !== "object") continue
            out.push({
                label: String((typeof App !== "undefined" && App.language !== "en" ? row.displayLabel : "") || row.label || ""),
                readoutText: root.valueText(row),
                unit: String(row.unit || ""),
                valid: row.valid !== false
            })
        }
        return out
    }
    function sameRowSet(next) {
        if (next.length !== rowStore.count) return false
        for (var i = 0; i < next.length; i++) {
            var current = rowStore.get(i)
            if (current.label !== next[i].label || current.unit !== next[i].unit) return false
        }
        return true
    }
    function syncRows() {
        var next = normalizedRows()
        if (!sameRowSet(next)) {
            rowStore.clear()
            for (var i = 0; i < next.length; i++) rowStore.append(next[i])
            return
        }
        for (var j = 0; j < next.length; j++) {
            var current = rowStore.get(j)
            if (current.readoutText !== next[j].readoutText)
                rowStore.setProperty(j, "readoutText", next[j].readoutText)
            if (current.valid !== next[j].valid)
                rowStore.setProperty(j, "valid", next[j].valid)
        }
    }
    onRowsChanged: syncRows()
    onBusyChanged: syncRows()
    onValueFormatChanged: syncRows()
    Component.onCompleted: syncRows()

    ListView {
        id: list
        objectName: "scalarReadoutList"
        anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter
        anchors.topMargin: 12
        width: Math.min(parent.width-32,860)
        clip: true; model: rowStore
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        delegate: Item {
            id: rowItem
            required property string label
            required property string readoutText
            required property string unit
            required property bool valid
            width: list.width; height: 62
            RowLayout {
                anchors.fill: parent; anchors.bottomMargin: 1; spacing: 14
                Text { Layout.fillWidth: true; Layout.minimumWidth: 0; text: rowItem.label; elide: Text.ElideRight
                    font.family: Theme.fontFamily; font.pixelSize: 14; color: Theme.textSecondary }
                Text { Layout.maximumWidth: 260; text: rowItem.readoutText; elide: Text.ElideRight; horizontalAlignment: Text.AlignRight
                    font.family: Theme.fontMono; font.pixelSize: 24; color: rowItem.valid ? Theme.textPrimary : Theme.textDisabled }
                Text { Layout.preferredWidth: 86; text: rowItem.unit; elide: Text.ElideRight; font.family: Theme.fontFamily; font.pixelSize: 13; color: Theme.textSecondary }
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border; opacity: .65 }
        }
    }
    Text { anchors.centerIn: parent; visible: !root.rows.length || root.busy; text: root.emptyText; color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 14 }
}
