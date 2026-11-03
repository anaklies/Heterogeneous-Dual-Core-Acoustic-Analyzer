import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../../components"

ColumnLayout {
    width: 264
    spacing: 10

    SectionTitle { text: App.t("events.detail"); iconName: "bell-ring" }
    LabeledValue {
        label: "eventId"
        value: (App.eventsData.events || []).length > 0
               ? String(App.eventsData.events[0].eventId) : "—"
    }
    LabeledValue {
        label: App.t("events.ack_state")
        value: (App.eventsData.events || []).length > 0 &&
               App.eventsData.events[0].ack && App.eventsData.events[0].ack.acked
               ? App.t("events.yes") : App.t("events.no")
    }
    AppButton {
        Layout.fillWidth: true
        text: App.t("diagnostics.refresh")
        iconName: "refresh-cw"
        compact: true
        enabled: App.connectionState === "connected"
        onClicked: App.listEvents()
    }
    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
    SectionTitle { text: App.t("events.monitoring"); iconName: "settings" }
    Text {
        Layout.fillWidth: true
        text: App.t("events.monitoring_disabled")
        color: Theme.textDisabled
        visible: false
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(18 * Theme.fontScale)
        wrapMode: Text.Wrap
    }
    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
    SectionTitle { text: App.t("overview.features"); iconName: "grid-3x3" }
    Repeater {
        model: App.pageFeatures
        delegate: RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Rectangle {
                width: 6; height: 6; radius: 3
                color: modelData.status === "available" ? Theme.ok
                       : modelData.status === "experimental" ? Theme.info
                       : modelData.status === "unsupported" ? Theme.textDisabled : Theme.warn
            }
            Text {
                text: modelData.featureId
                color: Theme.textSecondary
                font.family: Theme.fontMono
                font.pixelSize: Math.round(18 * Theme.fontScale)
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            Text {
                text: modelData.status
                color: Theme.textDisabled
                visible: false
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(18 * Theme.fontScale)
            }
        }
    }

    Item { Layout.fillHeight: true }
}
