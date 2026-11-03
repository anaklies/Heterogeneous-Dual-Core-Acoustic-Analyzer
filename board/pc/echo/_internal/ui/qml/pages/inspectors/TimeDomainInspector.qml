// Time & level inspector (tab-aware): parameters / channels / cursors & measurements.
// Every persisted control goes through App.setSetting (frozen setting keys only).
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
        SectionTitle { text: App.t("inspector.params"); iconName: "sliders-horizontal" }
        ChannelChips {
            label: App.t("inspector.channel")
            current: App.settings.spectrumChannel
            onChannelSelected: function(value) { App.setSetting("spectrumChannel", value) }
        }
        Text {
            text: App.t("time.window")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
        }
        ChoiceChips {
            Layout.fillWidth: true
            options: [
                { value: 0.5, label: "0.5 s" }, { value: 1.0, label: "1 s" },
                { value: 2.0, label: "2 s" }, { value: 5.0, label: "5 s" },
                { value: 10.0, label: "10 s" }
            ]
            current: App.settings.timeWindowSeconds
            compact: true
            onSelected: function(value) { App.setSetting("timeWindowSeconds", value) }
        }
        AppSlider {
            Layout.fillWidth: true
            label: App.t("time.line_width")
            from: 0.5
            to: 3.0
            stepSize: 0.1
            value: App.settings.lineWidth
            onEdited: function(value) { App.setSetting("lineWidth", Math.round(value * 10) / 10) }
        }
        Text {
            text: App.t("time.grid")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
        }
        ChoiceChips {
            Layout.fillWidth: true
            options: [
                { value: "weak", label: App.t("settings.grid.weak") },
                { value: "normal", label: App.t("settings.grid.normal") },
                { value: "strong", label: App.t("settings.grid.strong") }
            ]
            current: App.settings.gridStrength
            compact: true
            onSelected: function(value) { App.setSetting("gridStrength", value) }
        }
        Text {
            text: App.t("time.display_mode")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
        }
        ChoiceChips {
            Layout.fillWidth: true
            options: [
                { value: true, label: App.t("time.stacked") },
                { value: false, label: App.t("time.overlay") }
            ]
            current: App.settings.stackedWaveform
            compact: true
            onSelected: function(value) { App.setSetting("stackedWaveform", value) }
        }
        Text {
            text: App.t("time.channel_labels")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
        }
        ChoiceChips {
            Layout.fillWidth: true
            options: [
                { value: true, label: App.t("time.on") },
                { value: false, label: App.t("time.off") }
            ]
            current: App.settings.showChannelLabels
            compact: true
            onSelected: function(value) { App.setSetting("showChannelLabels", value) }
        }
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
                    text: (modelData.name || "CH") +
                          (modelData.nameLabel && modelData.nameLabel !== modelData.name
                           ? " · " + modelData.nameLabel : "")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(18 * Theme.fontScale)
                    elide: Text.ElideRight
                }
                Text {
                    text: modelData.visible === false ? App.t("time.off") : App.t("time.on")
                    color: modelData.visible === false ? Theme.textDisabled : Theme.ok
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
        spacing: 8
        SectionTitle { text: App.t("inspector.cursors"); iconName: "crosshair" }
        Text {
            Layout.fillWidth: true
            text: App.t("time.cursor_hint")
            color: Theme.textDisabled
            visible: false
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
            wrapMode: Text.Wrap
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        LabeledValue { label: App.t("time.start_sample"); value: App.timeDomainData.startSampleIndex ? String(App.timeDomainData.startSampleIndex) : "—" }
        LabeledValue { label: App.t("time.sample_rate"); value: App.timeDomainData.sampleRate ? App.formatNumber(App.timeDomainData.sampleRate) + " Hz" : "—" }
        LabeledValue { label: App.t("time.frames"); value: App.formatNumber(App.streamMeta.frameCount || 0) }
        LabeledValue { label: App.t("time.gap_title"); value: String((App.streamMeta.gaps || []).length) }
        LabeledValue { label: App.t("inspector.source"); value: App.dataSourceLabel }
        Text {
            Layout.fillWidth: true
            text: App.t("display.extraction_note")
            color: Theme.textDisabled
            visible: false
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
            wrapMode: Text.Wrap
        }
    }

    Item { Layout.fillHeight: true }
}
