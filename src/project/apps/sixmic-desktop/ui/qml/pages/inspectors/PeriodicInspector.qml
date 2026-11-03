import QtQuick
import QtQuick.Layouts
import "../../components"
ColumnLayout {
    width: 264; spacing: 10
    SectionTitle { text: App.t("pl.source_parameters"); iconName: "sliders-horizontal" }
    LabeledValue { Layout.fillWidth: true; label: App.t("inspector.source"); value: App.dataSourceLabel }
    LabeledValue { Layout.fillWidth: true; label: App.t("inspector.nfft"); value: App.periodicData.fftSize ? String(App.periodicData.fftSize) : "—" }
    Text {
        Layout.fillWidth: true
        text: App.t("pl.current_params_note")
        color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Math.round(18 * Theme.fontScale)
        wrapMode: Text.Wrap
    }
    Item { Layout.fillHeight: true }
}
