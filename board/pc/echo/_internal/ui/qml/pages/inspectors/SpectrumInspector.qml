import QtQuick
import QtQuick.Layouts
import "../../components"
ColumnLayout {
    width: 264; spacing: 10
    SectionTitle { text: App.t("pl.source_parameters"); iconName: "sliders-horizontal" }
    LabeledValue { Layout.fillWidth: true; label: App.t("inspector.nfft"); value: App.spectrumData.fftSize ? String(App.spectrumData.fftSize) : "—" }
    LabeledValue { Layout.fillWidth: true; label: App.t("status.sample_rate"); value: App.audioSampleRate ? String(App.audioSampleRate) + " Hz" : "—" }
    LabeledValue { Layout.fillWidth: true; label: App.t("inspector.source"); value: App.dataSourceLabel }
    SectionTitle { text: App.t("inspector.cursors"); iconName: "crosshair" }
    LabeledValue { Layout.fillWidth: true; label: App.t("inspector.cursorA"); value: App.spectrumData.cursorA !== undefined && App.spectrumData.cursorA !== null ? String(App.spectrumData.cursorA) + " Hz" : "—" }
    LabeledValue { Layout.fillWidth: true; label: App.t("inspector.cursorB"); value: App.spectrumData.cursorB !== undefined && App.spectrumData.cursorB !== null ? String(App.spectrumData.cursorB) + " Hz" : "—" }
    Item { Layout.fillHeight: true }
}
