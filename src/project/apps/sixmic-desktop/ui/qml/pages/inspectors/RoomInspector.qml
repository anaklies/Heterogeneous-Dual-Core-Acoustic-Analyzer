// Room acoustics inspector (tab-aware): boundary notes / channels / capability status.
import QtQuick
import QtQuick.Layouts
import "../../components"
import "../common"

ColumnLayout {
    width: 264
    spacing: 10

    ColumnLayout {
        visible: App.inspectorTab === 0
        Layout.fillWidth: true
        spacing: 8
        SectionTitle { text: App.t("inspector.params"); iconName: "gauge" }
        LabeledValue {
            label: App.t("room.status")
            value: String((App.featureWorkspace || {}).stateLabel || App.t("overview.not_ready"))
            valueColor: (App.featureWorkspace || {}).available === true ? Theme.ok : Theme.warn
        }
        LabeledValue { label: App.t("inspector.source"); value: String((App.featureWorkspace || {}).sourceLabel || App.t("source.none")) }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        NoteText { text: App.t("room.no_rt60") }
        NoteText { text: App.t("room.stipa") }
        NoteText { text: App.t("room.boundary") }

    }

    ColumnLayout {
        visible: App.inspectorTab === 1
        Layout.fillWidth: true
        spacing: 6
        SectionTitle { text: App.t("inspector.channels"); iconName: "layers" }
        Repeater {
            model: App.timeDomainData.channels || []
            delegate: RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Rectangle {
                    width: 10
                    height: 10
                    radius: 5
                    color: modelData.color || Theme.textSecondary
                }
                Text {
                    Layout.fillWidth: true
                    text: modelData.name || "CH"
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(18 * Theme.fontScale)
                }
            }
        }
        Text {
            Layout.fillWidth: true
            text: App.t("time.channel_hint")
            color: Theme.textDisabled
            visible: false
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
            wrapMode: Text.Wrap
        }
    }

    ColumnLayout {
        visible: App.inspectorTab === 2
        Layout.fillWidth: true
        spacing: 6
        SectionTitle { text: App.t("room.features"); iconName: "cpu" }
        Repeater {
            model: App.pageFeatures
            delegate: FeatureStatusRow {
                feature: modelData
                showFeatureId: false
            }
        }
        Text {
            Layout.fillWidth: true
            visible: false
            text: App.t("empty.room_unavailable")
            color: Theme.textDisabled
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
            wrapMode: Text.Wrap
        }
    }

    Item { Layout.fillHeight: true }
}
