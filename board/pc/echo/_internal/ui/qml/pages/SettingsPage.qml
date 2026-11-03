import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
Item {
    id: page
    Flickable {
        anchors.fill: parent; anchors.margins: 24
        contentWidth: width; contentHeight: settingsColumn.implicitHeight; clip: true
        ColumnLayout {
            id: settingsColumn; width: Math.min(parent.width, 720); spacing: 24
            Text { text: App.t("studio.settings"); color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: 22; font.weight: Font.Medium }
            SectionTitle { text: App.t("studio.device"); iconName: "plug-zap" }
            RowLayout {
                Layout.fillWidth: true
                // The address field must NOT be bound directly to App.settings.host:
                // telemetry emits dataChanged frequently and would overwrite what the
                // user is typing (the reported "address resets to preset" bug).
                TextField {
                    id: address
                    objectName: "deviceAddressField"
                    Layout.fillWidth: true
                    placeholderText: App.t("studio.device_address")
                    font.family: Theme.fontFamily
                    font.pixelSize: 14
                    Component.onCompleted: address.text = String(App.settings.host || "")
                    // Keep App.settings in memory current while typing; the settings
                    // file is saved on connect/edit finish/save/app exit.
                    onTextEdited: {
                        var h = String(text || "").trim()
                        if (h.length > 0) App.setSetting("host", h)
                    }
                    onEditingFinished: {
                        var h = String(text || "").trim()
                        if (h.length > 0) {
                            text = h
                            App.setSetting("host", h)
                            App.applySettings()
                        } else {
                            text = String(App.settings.host || "")
                        }
                    }
                }
                Connections {
                    target: App
                    function onDataChanged() {
                        // Never fight the user's focus; only re-sync after commit or
                        // when another page/action changed the saved address.
                        if (!address.activeFocus) {
                            var saved = String(App.settings.host || "")
                            if (address.text !== saved) address.text = saved
                        }
                    }
                }
                AppButton {
                    objectName: "settingsConnectButton"
                    text: App.t("studio.connect")
                    iconName: "plug-zap"
                    enabled: !App.busy && String(address.text || "").trim().length > 0
                    onClicked: {
                        var h = String(address.text || "").trim()
                        if (h.length > 0) {
                            address.text = h
                            App.setSetting("host", h)
                            App.applySettings()
                            App.connectDevice(h, 48120, 48121)
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                AppButton {
                    objectName: "settingsSaveAddressButton"
                    text: App.t("studio.save_address")
                    iconName: "check"
                    variant: "ghost"
                    compact: true
                    enabled: String(address.text || "").trim().length > 0
                    onClicked: {
                        var h = String(address.text || "").trim()
                        if (h.length > 0) {
                            address.text = h
                            App.setSetting("host", h)
                            App.applySettings()
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: App.t("studio.device_manual_hint")
                    color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
            }
            Text { Layout.fillWidth: true; text: App.t("studio.fixed_interface"); color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 13; wrapMode: Text.Wrap }

            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
            SectionTitle { text: App.t("studio.appearance"); iconName: "monitor" }
            RowLayout {
                Text { text: App.t("settings.language"); color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 14 }
                Item { Layout.fillWidth: true }
                ChoiceChips { options: [{value:"zh",label:"中文"},{value:"en",label:"English"}]; current: App.language; onSelected: function(v) { App.setLanguage(v); } }
            }
            Text { Layout.fillWidth: true; text: App.t("studio.native_dpi"); color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 13; wrapMode: Text.Wrap }
            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
            SectionTitle { text: App.t("studio.export"); iconName: "download" }
            AppButton { text: App.t("studio.export_folder"); iconName: "folder-open"; onClicked: App.openPath(App.userDataDirectory()+"/exports") }
            Text { Layout.fillWidth: true; text: App.t("studio.export_formats"); color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 13; wrapMode: Text.Wrap }
        }
    }
}
