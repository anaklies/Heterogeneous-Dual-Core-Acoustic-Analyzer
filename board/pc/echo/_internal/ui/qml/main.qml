import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "components"

ApplicationWindow {
    id: window
    visible: true
    width: App.settings.windowWidth > 0 ? App.settings.windowWidth : 1920
    height: App.settings.windowHeight > 0 ? App.settings.windowHeight : 1080
    minimumWidth: 600
    minimumHeight: 360
    color: Theme.appBg
    title: "echo"
    font.family: Theme.fontFamily

    property var pageMap: ({
        "overview": "pages/OverviewPage.qml",
        "time": "pages/TimeDomainPage.qml",
        "spectrum": "pages/SpectrumPage.qml",
        "bands": "pages/BandsPage.qml",
        "periodic": "pages/PeriodicPage.qml",
        "multichannel": "pages/MultichannelPage.qml",
        "room": "pages/RoomPage.qml",
        "advanced": "pages/AdvancedToolsPage.qml",
        "events": "pages/EventsPage.qml",
        "recording": "pages/RecordingPage.qml",
        "diagnostics": "pages/DiagnosticsPage.qml",
        "settings": "pages/SettingsPage.qml",
        "about": "pages/AboutPage.qml"
    })
    property var inspectorMap: ({
        "overview": "pages/inspectors/OverviewInspector.qml",
        "time": "pages/inspectors/TimeDomainInspector.qml",
        "spectrum": "pages/inspectors/SpectrumInspector.qml",
        "bands": "pages/inspectors/BandsInspector.qml",
        "periodic": "pages/inspectors/PeriodicInspector.qml",
        "multichannel": "pages/inspectors/MultichannelInspector.qml",
        "room": "pages/inspectors/RoomInspector.qml",
        "advanced": "pages/inspectors/AdvancedInspector.qml",
        "events": "pages/inspectors/EventsInspector.qml",
        "recording": "pages/inspectors/RecordingInspector.qml",
        "diagnostics": "pages/inspectors/DiagnosticsInspector.qml",
        "settings": "pages/inspectors/SettingsInspector.qml",
        "about": "pages/inspectors/AboutInspector.qml"
    })
    property string currentPageFile: pageMap[App.currentPage] !== undefined ? pageMap[App.currentPage] : ""

    function toggleInspector() {
        if (width < 1320) { App.setInspectorCollapsed(false); inspectorDrawer.open(); }
        else App.setInspectorCollapsed(!App.inspectorCollapsed);
    }
    Drawer {
        id: inspectorDrawer
        objectName: "measurementDrawer"
        width: Math.min(292, window.width - 40); height: window.height
        edge: Qt.RightEdge
        onClosed: if (window.width < 1320) App.setInspectorCollapsed(true)
        InspectorPanel { anchors.fill: parent; forceOpen: true; onCollapseRequested: inspectorDrawer.close() }
    }

    onWidthChanged: if (inspectorDrawer && width >= 1320 && inspectorDrawer.visible) inspectorDrawer.close()
    property bool fullScreenMode: visibility === Window.FullScreen
    property bool maximizedMode: visibility === Window.Maximized

    function saveGeometry() {
        App.setSetting("windowMaximized", window.maximizedMode || window.fullScreenMode)
        if (visibility !== Window.Windowed) return
        App.setSetting("windowWidth", Math.round(width))
        App.setSetting("windowHeight", Math.round(height))
        App.setSetting("windowX", Math.round(x))
        App.setSetting("windowY", Math.round(y))
    }

    function toggleFullScreen() {
        if (visibility === Window.FullScreen) {
            window.visibility = Window.Windowed
            width = Math.min(1920, Screen.availableWidth)
            height = Math.min(1080, Screen.availableHeight)
        } else {
            window.visibility = Window.FullScreen
        }
    }

    Shortcut { sequence: "Ctrl+O"; onActivated: App.setCurrentPage("recording") }
    Shortcut { sequence: "Ctrl+,"; onActivated: App.setCurrentPage("settings") }
    Shortcut { sequence: "F1"; onActivated: App.setCurrentPage("about") }
    Shortcut { sequence: "F5"; onActivated: App.setCurrentPage("diagnostics") }
    Shortcut { sequence: "Ctrl+Shift+L"; onActivated: App.toggleLanguage() }
    Shortcut { sequence: "Ctrl+Shift+D"; onActivated: App.setThemeMode(Theme.resolved === "dark" ? "light" : "dark") }
    Shortcut { sequence: "Ctrl+R"; onActivated: App.recordingData.recording.state === "recording" ? App.stopRecording() : App.startRecording() }
    Shortcut { sequence: "F11"; onActivated: window.toggleFullScreen() }

    onClosing: function(close) {
        saveGeometry()
        close.accepted = true
    }

    Component.onCompleted: {
        var savedW = Number(App.settings.windowWidth || 0)
        var savedH = Number(App.settings.windowHeight || 0)
        if (savedW > 640 && savedH > 480) {
            width = savedW
            height = savedH
            if (App.settings.windowX > 0) x = App.settings.windowX
            if (App.settings.windowY > 0) y = App.settings.windowY
            if (App.settings.windowMaximized) window.visibility = Window.Maximized
        } else {
            width = Math.min(1920, Screen.availableWidth)
            height = Math.min(1080, Screen.availableHeight)
            window.visibility = Window.Maximized
        }
    }

    Item {
        anchors.fill: parent
        Rectangle {
            anchors.fill:parent
            gradient:Gradient {
                GradientStop {position:0;color:Qt.lighter(Theme.appBg,1.16)}
                GradientStop {position:1;color:Qt.darker(Theme.appBg,1.08)}
            }
        }
        Image {anchors.fill:parent;source:Qt.resolvedUrl("../../assets/patterns/pattern-craft-blue-radial.svg");fillMode:Image.PreserveAspectCrop;visible:Theme.resolved==="dark";opacity:.65;sourceSize:Qt.size(1920,1200);smooth:true}
        Image {anchors.fill:parent;source:Qt.resolvedUrl("../../assets/patterns/room-instrument.svg");fillMode:Image.Tile;opacity:.018;sourceSize:Qt.size(80,80);smooth:false}

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            AppToolBar { Layout.fillWidth: true; Layout.preferredHeight: 48 }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                NavRail { Layout.fillHeight: true }

                Item {
                    id: pageHost
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0
                        Loader {
                        id: pageLoader
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        source: window.currentPageFile
                        onStatusChanged: {
                            if (pageLoader.status === Loader.Error) {
                                pageError.visible = true
                            } else if (pageLoader.status === Loader.Ready) {
                                pageError.visible = false
                            }
                        }
                    }
                    }
                    ColumnLayout {
                        id: pageError
                        visible: false
                        anchors.centerIn: parent
                        width: parent.width * 0.7
                        spacing: 8
                        Text {
                            text: App.t("topbar.workspace") + " · " + App.currentPage
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(21 * Theme.fontScale)
                            font.weight: Font.Medium
                        }
                        Text {
                            text: App.t("empty.not_connected")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(18 * Theme.fontScale)
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }

                Rectangle {
                    Layout.fillHeight: true
                    width: 1
                    color: Theme.border
                    visible: window.width >= 1320 && !App.inspectorCollapsed
                }
                InspectorPanel {
                    visible: window.width >= 1320 && !App.inspectorCollapsed
                    Layout.preferredWidth: 264
                    Layout.fillHeight: true
                    inspectorSource: window.inspectorMap[App.currentPage] !== undefined
                                     ? Qt.resolvedUrl(window.inspectorMap[App.currentPage]) : ""
                }
            }

            StatusBar { Layout.fillWidth: true }
        }

        ToastPanel { }
        LoadingOverlay { }
    }
}
