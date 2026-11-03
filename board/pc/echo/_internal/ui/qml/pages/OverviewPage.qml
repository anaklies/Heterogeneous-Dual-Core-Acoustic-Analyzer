import QtQuick
import QtQuick.Layouts
import "../components"
import "../components/charts"
Item {
    id:page
    property var d:App.instrumentDashboard
    property var wave:App.timeDomainData
    function localizedSpectrum(){
        if(!page.d.spectrum)return null;
        var result=Object.assign({},page.d.spectrum);result.xAxis=Object.assign({},result.xAxis,{label:App.t("instrument.frequency")});result.yAxis=Object.assign({},result.yAxis,{label:App.t("instrument.amplitude")});return result;
    }
    ColumnLayout {
        anchors.fill:parent;anchors.margins:16;spacing:14
        RowLayout {
            Layout.fillWidth:true
            Text {text:App.t("instrument.overview");font.family:Theme.fontFamily;font.pixelSize:25;font.weight:Font.DemiBold;color:Theme.textPrimary}
            Item {Layout.fillWidth:true}
            Text {text:page.d.connected?(page.d.fresh?App.t("instrument.live"):App.t("instrument.waiting")):App.t("instrument.disconnected");color:page.d.fresh?Theme.ok:Theme.textSecondary;font.pixelSize:15}
            AppButton {text:App.t("instrument.device");iconName:"settings";compact:true;onClicked:App.setCurrentPage("settings")}
        }
        GridLayout {
            Layout.fillWidth:true;Layout.minimumHeight:width>760?88:186;Layout.maximumHeight:Layout.minimumHeight;columns:width>760?4:2;columnSpacing:12;rowSpacing:10
            Repeater {
                model:4
                delegate:Rectangle {
                    required property int index
                    readonly property var names:[App.t("instrument.sample_rate"),App.t("instrument.inputs"),App.t("instrument.receive_rate"),App.t("instrument.event_records")]
                    readonly property var values:[page.d.sampleRateHz?Number(page.d.sampleRateHz).toFixed(0):"—",page.d.levels?"6":"—",page.d.refreshHz?Number(page.d.refreshHz).toFixed(1):"—",String(page.d.eventCount||0)]
                    readonly property var units:["Hz",App.t("instrument.channels"),App.t("instrument.fps"),App.t("instrument.events")]
                    objectName:"overviewMetric"+index
                    Layout.fillWidth:true;Layout.preferredHeight:88;radius:14;color:Theme.panelBg
                    Column {anchors.fill:parent;anchors.margins:14;spacing:6
                        Text {text:names[index];color:Theme.textSecondary;font.pixelSize:14;font.family:Theme.fontFamily}
                        Row {spacing:8
                            Text {text:values[index];color:Theme.textPrimary;font.pixelSize:29;font.family:Theme.fontFamily;font.weight:Font.Medium}
                            Text {text:units[index];color:Theme.textSecondary;font.pixelSize:14;anchors.bottom:parent.bottom;anchors.bottomMargin:4}
                        }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth:true;Layout.fillHeight:true;Layout.preferredHeight:300;spacing:14
            Panel {
                Layout.fillWidth:true;Layout.fillHeight:true;Layout.minimumHeight:200
                FeatureChart {
                    anchors.fill:parent;showSourceBanner:false;titleOverride:App.t("instrument.spectrum");workspaceOverride:({featureId:"dashboard_spectrum"})
                    chart:page.localizedSpectrum()||({kind:"spectrum",title:App.t("instrument.spectrum"),series:[],emptyReason:App.t("instrument.waiting_input"),xAxis:{label:App.t("instrument.frequency"),unit:"Hz"},yAxis:{label:App.t("instrument.amplitude"),unit:"FS"}})
                }
            }
            Panel {
                Layout.preferredWidth:Math.max(240,Math.min(360,page.width*.3));Layout.fillHeight:true
                ColumnLayout {anchors.fill:parent;spacing:8
                    Text {text:App.t("instrument.rms");font.pixelSize:17;font.weight:Font.DemiBold;color:Theme.textPrimary}
                    GridLayout {
                        Layout.fillWidth:true;Layout.minimumHeight:100;Layout.maximumHeight:100
                        columns:3;columnSpacing:8;rowSpacing:6
                        Repeater {
                            model:6
                            delegate:Column {
                                required property int index
                                readonly property var level:(page.d.levels||[])[index]||({})
                                Layout.fillWidth:true;Layout.preferredWidth:0;Layout.minimumWidth:0;spacing:2
                                Row {spacing:5
                                    Rectangle {width:7;height:7;radius:3.5;color:Theme.channelColors[index];anchors.verticalCenter:parent.verticalCenter}
                                    Text {text:"MIC"+(index+1);font.pixelSize:12;color:Theme.textSecondary}
                                }
                                Text {
                                    objectName:"overviewMicValue"+index
                                    width:parent.width;elide:Text.ElideRight
                                    text:level.valid!==false && typeof level.value==="number" && isFinite(level.value)?Number(level.value).toFixed(1):"—"
                                    font.family:Theme.fontMono;font.pixelSize:18;font.weight:Font.DemiBold;color:Theme.textPrimary
                                }
                            }
                        }
                    }
                    BarChart {showValueLabels:false;Layout.fillWidth:true;Layout.fillHeight:true;categories:page.d.levels||[];yAxis:({min:-120,max:0,label:App.t("instrument.level"),unit:"dBFS"});xLabel:App.t("instrument.microphone");emptyText:App.t("instrument.waiting_input")}
                }
            }
        }
        Panel {
            Layout.fillWidth:true;Layout.fillHeight:true;Layout.preferredHeight:200;Layout.minimumHeight:180
            ColumnLayout {anchors.fill:parent;spacing:4
                Text {text:App.t("instrument.waveform");font.pixelSize:17;font.weight:Font.DemiBold;color:Theme.textPrimary}
                WaveformChart {Layout.fillWidth:true;Layout.fillHeight:true;channels:page.wave.channels||[];sampleRate:page.wave.sampleRate||0;stacked:true;gaps:page.wave.gaps||[];emptyText:App.t("instrument.waiting_input");emptyReason:""}
            }
        }
    }
}
