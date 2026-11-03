import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
Item {
    id: root
    objectName: "featureEntryRow"
    property string pageId: ""
    // Kept for the page contract: bumped on every structural notification so
    // pages can observe it, but it no longer drives the delegate model.
    property int revision: 0
    // Read the workspace once per change; every delegate shares this value
    // instead of re-entering the App.featureWorkspace property getter.
    property var workspace: (typeof App !== "undefined" && App && App.featureWorkspace !== undefined) ? App.featureWorkspace : ({})
    // Stable entry groups. App emits featureEntriesChanged on every live state
    // refresh (~15 Hz); letting that notification replace the Repeater model
    // destroyed and recreated every tab button several times per second, and a
    // real mouse press+release spanning one rebuild never fired onClicked, so
    // the user had to click a tab several times. New groups are therefore only
    // applied when the data the tab row actually renders changed.
    property var groups: []
    property string entriesSignature: ""
    readonly property var entries: {
        var out=[]; for(var g=0;g<groups.length;g++) {
            var list=groups[g].features || []; for(var i=0;i<list.length;i++) out.push(list[i]);
        } return out;
    }
    readonly property bool hasGroups: entries.length > 0
    readonly property int entryCount: entries.length
    readonly property int groupCount: groups.length

    // Job states are recreated per live result frame (queued/starting/accepted/
    // running), so the raw state must be folded into a stable active/terminal
    // class before it can be part of a rebuild fingerprint; the tab row itself
    // only renders availability and the active workspace highlight.
    function signatureState(entry) {
        var state = String(entry.state || "")
        if (entry.running === true) return "active"
        if (state === "queued" || state === "starting" || state === "accepted"
                || state === "running" || state === "stopping") return "active"
        return state
    }
    // Cheap fingerprint of everything the tab row renders: ids/order, labels,
    // icons, availability/state and the localized tooltip reason. Locale and
    // catalog changes are covered because those strings are part of the
    // fingerprint; live chart frames never change any of them.
    function entrySignature(groupsValue) {
        var parts = []
        var source = groupsValue || []
        for (var g = 0; g < source.length; g++) {
            var group = source[g]
            if (!group) continue
            var list = group.features || []
            for (var i = 0; i < list.length; i++) {
                var entry = list[i]
                if (!entry) continue
                parts.push(String(entry.featureId) + "\u0001"
                           + String(entry.shortName || entry.name || "") + "\u0001"
                           + String(entry.name || "") + "\u0001"
                           + String(entry.icon || "") + "\u0001"
                           + (entry.available === false ? "0" : "1") + "\u0001"
                           + signatureState(entry) + "\u0001"
                           + String(entry.disabledReason || ""))
            }
        }
        return parts.join("\u0002")
    }
    function syncEntries() {
        if (typeof App === "undefined" || !App) return
        var fresh = []
        try {
            fresh = App.featureGroupsForPage(pageId) || []
        } catch (error) {
            return
        }
        var signature = entrySignature(fresh)
        if (signature === entriesSignature) return
        entriesSignature = signature
        groups = fresh
    }

    implicitHeight: 46
    readonly property bool overflowing: items.implicitWidth > root.width
    IconButton {
        z: 2; visible: root.overflowing; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
        iconName: "chevron-left"; tooltip: App.t("studio.previous_tools")
        enabled: tabs.contentX > 0
        onClicked: tabs.contentX = Math.max(0, tabs.contentX - tabs.width * 0.7)
    }
    IconButton {
        z: 2; visible: root.overflowing; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        iconName: "chevron-right"; tooltip: App.t("studio.more_tools")
        enabled: tabs.contentX < tabs.contentWidth - tabs.width - 1
        onClicked: tabs.contentX = Math.min(tabs.contentWidth - tabs.width, tabs.contentX + tabs.width * 0.7)
    }
    // Structural refresh trigger: catalog/availability/locale notifications.
    // Live data notifications are ignored unless the rendered entry data
    // really changed (see entrySignature), so clicks are never swallowed.
    Connections { target: App; function onFeatureEntriesChanged() { root.revision++; root.syncEntries(); } }
    onPageIdChanged: syncEntries()
    Component.onCompleted: syncEntries()
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
    Flickable {
        id: tabs; anchors.fill: parent; anchors.leftMargin: root.overflowing ? 36 : 0; anchors.rightMargin: root.overflowing ? 36 : 0
        contentWidth: items.implicitWidth; contentHeight: height
        flickableDirection: Flickable.HorizontalFlick; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded; height: 3 }
        Row {
            id: items; height: tabs.height; spacing: 3
            Repeater {
                model: root.entries
                delegate: Button {
                    id: tab
                    required property var modelData
                    property bool active: root.workspace.open === true && root.workspace.featureId === modelData.featureId
                    objectName: "featureEntry_" + modelData.featureId
                    width: Math.max(74, contents.implicitWidth + 24); height: 44
                    hoverEnabled: true
                    onClicked: App.openFeatureEntry(modelData.featureId)
                    background: Rectangle {
                        color: tab.hovered ? Theme.hover : "transparent"
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; color: tab.active ? Theme.accent : "transparent" }
                    }
                    contentItem: RowLayout {
                        id: contents; spacing: 7
                        Icon { name: tab.modelData.icon || "activity"; size: 20; color: tab.active ? Theme.accent : Theme.textSecondary }
                        Text { text: tab.modelData.shortName || tab.modelData.name; color: tab.active ? Theme.textPrimary : Theme.textSecondary
                            font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: tab.active ? Font.Medium : Font.Normal }
                    }
                    ToolTip.visible: hovered
                    ToolTip.text: modelData.name + (modelData.available ? "" : "\n" + String(modelData.disabledReason || ""))
                    ToolTip.delay: 450
                    Accessible.name: modelData.name
                }
            }
        }
    }
}