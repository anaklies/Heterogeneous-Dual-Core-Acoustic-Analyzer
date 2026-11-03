import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
Item {
    id: page
    property string selectedEvent: ""
    property bool isMonitor: App.featureWorkspace.featureId === "event_trigger"
    Dialog {
        id:clearDialog;parent:Overlay.overlay;modal:true;width:Math.min(520,parent.width-32)
        x:(parent.width-width)/2;y:(parent.height-height)/2;title:"清空事件记录"
        onOpened:{deviceChoice.checked=App.connectionState==="connected";localChoice.checked=false;}
        contentItem:ColumnLayout {
            spacing:12
            Label { Layout.fillWidth:true;wrapMode:Text.WordWrap;text:"将先停止监测。请确认清理范围；删除后不可恢复，已导出的文件保留。" }
            CheckBox { id:deviceChoice;text:"清空板端 SD 事件缓存";enabled:App.connectionState==="connected" }
            CheckBox { id:localChoice;text:"同时删除本机下载的事件录音" }
        }
        footer:DialogButtonBox {
            Button { text:"取消";DialogButtonBox.buttonRole:DialogButtonBox.RejectRole }
            Button { text:"确认清空";enabled:deviceChoice.checked||localChoice.checked;DialogButtonBox.buttonRole:DialogButtonBox.AcceptRole }
        }
        onAccepted:App.clearAllEvents(deviceChoice.checked,localChoice.checked)
    }
    Component.onCompleted: Qt.callLater(function() { App.openFeatureEntry("event_trigger"); })
    Flickable {
        id: viewport
        anchors.fill: parent; contentWidth: width
        contentHeight: Math.max(height,width>=1008 ? 430 : 650)
        clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; active: true }
    ColumnLayout {
        width: viewport.width-28; x:14; height: viewport.contentHeight; spacing: 8
        FeatureEntryRow { Layout.fillWidth: true; pageId: "events" }
        GridLayout {
            id: body; Layout.fillWidth: true; Layout.fillHeight: true; columns: width >= 980 ? 2 : 1; columnSpacing: 12; rowSpacing: 8
            Panel {
                visible:page.isMonitor
                Layout.fillWidth:true;Layout.fillHeight:true;Layout.minimumHeight:340
                ColumnLayout {
                    anchors.fill:parent;spacing:14
                    Text { text:App.language==="en"?"Background change recorder":"环境变化记录仪";color:Theme.textPrimary;font.pixelSize:24;font.family:Theme.fontFamily }
                    Text { Layout.fillWidth:true;wrapMode:Text.WordWrap;color:Theme.textSecondary;font.pixelSize:15
                        text:App.eventsData.monitoring.active ? (App.eventsData.monitoring.phase==="learning"?"正在准备背景 · 请保持平常的环境声音":"正在监测 · 发现变化后自动保存前后音频") : "点击开始：准备背景 → 监测变化 → 保存事件" }
                    ProgressBar { Layout.fillWidth:true;visible:App.eventsData.monitoring.active;from:0;to:1
                        value:Math.min(1,Number(App.eventsData.monitoring.progress.observedBackgroundFrames||0)/Math.max(1,Number(App.eventsData.monitoring.progress.expectedBackgroundFrames||24))) }
                    Text { visible:App.eventsData.monitoring.active;Layout.fillWidth:true;wrapMode:Text.WordWrap;color:Theme.textSecondary;font.pixelSize:13
                        text:"背景准备按采集帧估算；当前固件没有独立的学习完成回读。" }
                    RowLayout {
                        AppButton { text:App.eventsData.monitoring.active?"停止监测":"开始并学习背景";iconName:App.eventsData.monitoring.active?"square":"play";enabled:App.connectionState==="connected"
                            onClicked:{if(App.eventsData.monitoring.active)App.stopFeature("event_trigger");else App.runFeature("event_trigger");} }
                        AppButton { text:"刷新记录";iconName:"refresh-cw";onClicked:App.refreshFeatureEvents() }
                    }
                    Text { Layout.fillWidth:true;wrapMode:Text.WordWrap;color:Theme.textSecondary;font.pixelSize:14
                        text:(App.eventsData.storage.eventLoopRecording?"SD循环录音 · ":"事件缓存 · ")+(Number(App.eventsData.storage.eventSpoolBytes||0)/1048576).toFixed(1)+" / "+(Number(App.eventsData.storage.eventSpoolLimitBytes||0)/1048576).toFixed(0)+" MiB · "+(App.eventsData.storage.eventLoopRecording?"到上限自动淘汰最早记录":"请检查SD卡循环存储状态") }
                    FeatureChart { Layout.fillWidth:true;Layout.fillHeight:true;Layout.minimumHeight:140;chart:App.featureWorkspace.chart }
                }
            }
            FeatureWorkspace { visible:!page.isMonitor;Layout.fillWidth:true;Layout.fillHeight:true;Layout.minimumHeight:300;pageScope:"events" }
            Panel {
                visible:page.isMonitor
                Layout.preferredWidth: body.columns === 2 ? 294 : -1
                Layout.fillWidth: body.columns === 1; Layout.fillHeight: body.columns === 2
                Layout.preferredHeight: body.columns === 1 ? 196 : -1
                ColumnLayout {
                    anchors.fill: parent; spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        SectionTitle { text: App.t("studio.events"); iconName: "bell-ringing" }
                        IconButton { iconName: "refresh-cw"; tooltip: App.t("studio.refresh"); enabled: App.connectionState === "connected"; onClicked: App.refreshFeatureEvents() }
                    }
                    ListView {
                        id: eventList
                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 2
                        model: App.eventsData.events || []
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; active: true }
                        delegate: ItemDelegate {
                            id: eventRow
                            required property var modelData
                            width: eventList.width; height: 76
                            onClicked: { page.selectedEvent=String(modelData.eventId); App.selectEvent(page.selectedEvent); }
                            background: Rectangle { radius: 3; color: page.selectedEvent === String(eventRow.modelData.eventId) ? Theme.accentSoft : eventRow.hovered ? Theme.hover : "transparent" }
                            contentItem: ColumnLayout {
                                spacing: 3
                                Text { Layout.fillWidth: true; text: eventRow.modelData.displayName || (App.t("studio.event") + " " + String(eventRow.modelData.eventId || "").slice(-8))
                                    font.family: Theme.fontFamily; font.pixelSize: 15; color: Theme.textPrimary; elide: Text.ElideRight }
                                Text { Layout.fillWidth: true; text: (eventRow.modelData.category || "") + " · " + (eventRow.modelData.fileState === "stored" || ["stored","verified"].indexOf((eventRow.modelData.file || {}).state)>=0 ? App.t("studio.downloaded") : App.t("studio.ready_download"))
                                    font.family: Theme.fontFamily; font.pixelSize: 12; color: Theme.textSecondary; elide: Text.ElideRight }
                                Text { text:eventRow.modelData.timeText||"";font.pixelSize:12;color:Theme.textSecondary }
                            }
                        }
                        Text { anchors.centerIn: parent; visible: eventList.count === 0; text: App.t("studio.no_events"); color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 13 }
                    }
                    AppButton { Layout.fillWidth:true;text:App.eventsData.downloading?"正在下载并生成WAV…":"下载所选事件";iconName:"download";enabled:page.selectedEvent.length>0&&!App.eventsData.downloading
                        onClicked:App.downloadEvent(page.selectedEvent) }
                    AppButton { Layout.fillWidth: true; text: "导出音频、数据与元数据"; iconName: "download"; compact: true
                        enabled: page.selectedEvent.length > 0 && !App.exportBusy; onClicked: App.exportEventData(page.selectedEvent) }
                    RowLayout {
                        Layout.fillWidth:true
                        AppButton { Layout.fillWidth:true;text:"打开下载文件夹";iconName:"folder-open";compact:true;onClicked:App.openEventDownloads() }
                        AppButton { text:App.eventsData.clearing?"正在清空…":"清空全部";iconName:"trash";compact:true;enabled:!App.eventsData.downloading&&!App.eventsData.clearing;onClicked:clearDialog.open() }
                    }
                }
            }
        }
        Item { Layout.preferredHeight: 4 }
    }
    }
}
