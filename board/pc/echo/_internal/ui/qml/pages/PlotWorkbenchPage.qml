import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../components/charts"

Item {
    id: page
    property var link: App.plInterface
    Flickable {
        id: scroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; active: true }
        ColumnLayout {
            id: content
            width: scroll.width
            spacing: 12
            Panel {
                Layout.fillWidth: true
                Layout.preferredHeight: connectionColumn.implicitHeight + 20
                padding: 10
                ColumnLayout {
                    id: connectionColumn
                    anchors.fill: parent
                    spacing: 8
                    SectionTitle { text: App.t("pl.interface") }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        AppButton {
                            text: page.link.controlHeld ? App.t("pl.release") : App.t("pl.claim")
                            compact: true; enabled: page.link.connected
                            onClicked: page.link.controlHeld ? App.releaseControl() : App.claimControl()
                        }
                        AppButton {
                            text: App.t("pl.subscribe")
                            compact: true; enabled: page.link.canSubscribe
                            onClicked: App.subscribeLive()
                        }
                        AppButton {
                            text: App.t("pl.start_p1")
                            compact: true; enabled: page.link.canStartTask
                            onClicked: App.startJob("p1Carousel")
                        }
                        AppButton {
                            text: App.t("pl.start_p2")
                            compact: true; enabled: page.link.canStartTask
                            onClicked: App.startJob("p2OneShot")
                        }
                    }
                    LabeledValue { Layout.fillWidth: true; label: App.t("pl.service"); value: String(page.link.serviceId || "—") }
                    LabeledValue { Layout.fillWidth: true; label: App.t("pl.raw_words"); value: page.link.wordCount == null ? "—" : String(page.link.wordCount) }
                    LabeledValue { Layout.fillWidth: true; label: App.t("pl.sample_index"); value: String(page.link.sampleIndex || "—") }
                    Text {
                        Layout.fillWidth: true
                        text: page.link.wordCount && !page.link.decodedReady ? App.t("pl.metadata_missing") : App.t("pl.data_note")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily; font.pixelSize: Math.round(18 * Theme.fontScale)
                        wrapMode: Text.Wrap
                    }
                }
            }
            GridLayout {
                id: grid
                objectName: "plWorkbenchGrid"
                Layout.fillWidth: true
                columns: width >= 1120 ? 3 : (width >= 740 ? 2 : 1)
                rowSpacing: 12; columnSpacing: 12
                Repeater {
                    model: App.plPlotCards
                    delegate: AnalysisPlotPanel {
                        id: card
                        required property var modelData
                        property var plotData: modelData.data
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.round(414 * Theme.fontScale)
                        Layout.columnSpan: modelData.kind === "waterfall" ? Math.min(2, grid.columns) : 1
                        title: modelData.title
                        Loader {
                            anchors.fill: parent
                            sourceComponent: card.modelData.kind === "bands" ? bandsPlot
                                : card.modelData.kind === "heatmap" ? heatPlot
                                : card.modelData.kind === "polar" ? polarPlot
                                : card.modelData.kind === "waterfall" ? waterfallPlot : linePlot
                        }
                        Component {
                            id: linePlot
                            LineChart { series: card.plotData.series || []; xAxis: card.plotData.xAxis || null; yAxis: card.plotData.yAxis || null }
                        }
                        Component {
                            id: bandsPlot
                            BarChart { categories: card.plotData.categories || []; xMode: "centerFrequency"; yAxis: card.plotData.yAxis || null }
                        }
                        Component {
                            id: heatPlot
                            HeatmapChart { imageUrl: card.plotData.imageUrl || ""; xAxis: card.plotData.xAxis || null; yAxis: card.plotData.yAxis || null; colorScale: card.plotData.colorScale || null }
                        }
                        Component {
                            id: polarPlot
                            PolarChart {
                                imageUrl: card.plotData.imageUrl
                                azimuthRange: card.plotData.azimuthRange
                                elevationRange: card.plotData.elevationRange
                                colorScale: card.plotData.colorScale
                                projection: card.plotData.projection || "polar"
                                caption: card.plotData.caption || ""
                            }
                        }
                        Component {
                            id: waterfallPlot
                            WaterfallChart { frames: card.plotData.frames || []; frequencyAxis: card.plotData.yAxis; timeAxis: card.plotData.xAxis; colorScale: card.plotData.colorScale }
                        }
                    }
                }
            }
            Panel {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.round(299 * Theme.fontScale)
                visible: App.plPlotCards.length === 0
                EmptyState {
                    anchors.fill: parent
                    title: App.t("pl.wait_data")
                    reason: App.t("pl.metadata_missing")
                    hint: App.t("pl.data_note")
                    iconName: "activity"
                }
            }
        }
    }
}
