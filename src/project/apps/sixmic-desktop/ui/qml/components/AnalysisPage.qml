import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
Item {
    id: page
    property string pageId: ""
    property int revision: 0
    property real minimumCanvasHeight: {var p=(App.featureWorkspace.chart || {}).panels || [];return p.length>1?p.length*200+160:430;}
    property bool selectionPending: false
    function chooseFirst() {
        if (App.currentPage !== pageId) return;
        var entries=App.featureEntriesForPage(pageId) || [];
        if (!entries.length) return;
        var w=App.featureWorkspace || {};
        for(var i=0;i<entries.length;i++) if(w.open && w.featureId === entries[i].featureId) return;
        // Opening another feature can cancel the old job. Never do that just
        // because navigation changed while background monitoring is active.
        if(w.open && w.featureId === "event_trigger" && ["running","starting","accepted","stopping"].indexOf(w.state)>=0) return;
        App.openFeatureEntry(entries[0].featureId);
    }
    Component.onCompleted: Qt.callLater(chooseFirst)
    Connections { target: App; function onPageChanged() { Qt.callLater(page.chooseFirst); } }
    Flickable {
        id: viewport
        anchors.fill: parent; contentWidth: width; contentHeight: Math.max(height,page.minimumCanvasHeight)
        clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; active: true }
    ColumnLayout {
        width: viewport.width-28; height: Math.max(viewport.height,page.minimumCanvasHeight); x:14; spacing: 8
        FeatureEntryRow { Layout.fillWidth: true; pageId: page.pageId }
        FeatureWorkspace { pageScope: page.pageId; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 260 }
        Item { Layout.preferredHeight: 4 }
    }
    }
}
