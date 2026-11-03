import QtQuick
import QtQuick.Layouts
import "../components"

Item {
    id: page
    objectName: "advancedToolsPage"
    // Restored original four sub-pages; the old "feature workbench (51)" JSON
    // parameter page is gone.  Each sub-page carries its own page-scoped
    // FeatureEntryRow for the prompt's 8-category layout.
    property int subTab: 0
    property var subPages: ["PlotWorkbenchPage.qml", "PeriodicPage.qml", "RoomPage.qml"]

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 14

        GridLayout {
            Layout.fillWidth: true
            columns: width < 950 ? 1 : 2
            rowSpacing: 10
            Text {
                text: App.t("advanced.title")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(29 * Theme.fontScale)
                font.weight: Font.DemiBold
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                elide: Text.ElideRight
            }
            ChoiceChips {
                options: [
                    { value: "0", label: App.t("plots.workspace") },
                    { value: "1", label: App.t("advanced.periodic") },
                    { value: "2", label: App.t("advanced.room") }
                ]
                current: String(page.subTab)
                onSelected: function(value) { page.subTab = Number(value) }
            }
        }

        Loader {
            id: subLoader
            Layout.fillWidth: true
            Layout.fillHeight: true
            source: page.subTab >= 0 && page.subTab < page.subPages.length
                    ? Qt.resolvedUrl(page.subPages[page.subTab])
                    : ""
            onLoaded: {
                // sub pages are reuse of the original PL task pages; they hold no
                // PC-side algorithms and expose "not connected" states only.
            }
        }
    }
}
