import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "ChartUtil.js" as U
Item {
    id: root
    objectName: "readoutStrip"
    property var rows: []
    property int maxItems: 32
    property bool wrapRows: false
    readonly property int gridColumns:Math.max(1,Math.floor(width/235))
    readonly property int gridRows:Math.ceil(Math.min(maxItems,(rows||[]).length)/gridColumns)
    implicitHeight: wrapRows ? Math.max(40,gridRows*40) : 40; height: implicitHeight
    function valueText(row) {
        if(!row || row.valid === false || row.value === null || row.value === undefined)return "—";
        if(typeof row.value === "number")return U.fmtReadout(row.value,row.valueFormat || "");
        if(typeof row.value === "boolean" && typeof App !== "undefined")return App.t(row.value?"studio.yes":"studio.no");
        return String(row.value);
    }
    Grid {
        id:wrapped;width:root.width;columns:root.gridColumns;columnSpacing:12;rowSpacing:4;visible:root.wrapRows
        Repeater {
            model:root.wrapRows ? Math.min(root.maxItems,(root.rows||[]).length) : 0
            delegate:Item {
                required property int index
                readonly property var modelData:root.rows[index]||({})
                width:Math.max(0,(root.width-12*(root.gridColumns-1))/root.gridColumns);height:36
                RowLayout {anchors.fill:parent;spacing:6
                    Text {Layout.maximumWidth:90;Layout.fillWidth:true;text:App.language!=="en" && modelData.displayLabel?modelData.displayLabel:(modelData.label||"");elide:Text.ElideRight;color:Theme.textSecondary;font.pixelSize:14}
                    Text {Layout.maximumWidth:110;text:root.valueText(modelData);elide:Text.ElideRight;color:modelData.valid===false?Theme.textDisabled:Theme.textPrimary;font.family:Theme.fontMono;font.pixelSize:17}
                    Text {text:modelData.unit||"";color:Theme.textSecondary;font.pixelSize:13}
                }
            }
        }
    }
    Flickable {
        visible:!root.wrapRows
        anchors.fill: parent; clip: true; contentWidth: contents.implicitWidth; contentHeight: height
        flickableDirection: Flickable.HorizontalFlick; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded; height: 3 }
        Row {
            id: contents; height: parent.height; spacing: 22
            Repeater {
                model: Math.min(root.maxItems,(root.rows||[]).length)
                delegate: Row {
                    required property int index
                    readonly property var modelData:root.rows[index]||({})
                    spacing: 6; height: 36
                    Text { text: (typeof App !== "undefined" && App.language !== "en" && modelData.displayLabel) ? modelData.displayLabel : (modelData.label || ""); height: parent.height; verticalAlignment: Text.AlignVCenter; color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 12 }
                    Text { text: root.valueText(modelData); height: parent.height; verticalAlignment: Text.AlignVCenter; color: modelData.valid === false ? Theme.textDisabled : Theme.textPrimary; font.family: Theme.fontMono; font.pixelSize: 15 }
                    Text { text: modelData.unit || ""; height: parent.height; verticalAlignment: Text.AlignVCenter; color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 12 }
                }
            }
        }
    }
}
