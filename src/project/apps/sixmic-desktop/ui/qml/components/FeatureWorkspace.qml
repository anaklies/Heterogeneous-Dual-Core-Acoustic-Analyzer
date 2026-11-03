import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
Item {
    id: root
    objectName: "featureWorkspace"
    property string pageScope: ""
    property var workspace: {
        var w=App.featureWorkspace || ({});
        return pageScope.length && w.page && w.page !== pageScope ? ({}) : w;
    }
    property var status: App.featureStatus || ({})
    property int variantIndex: Number(workspace.selectedVariant || 0)
    readonly property bool isOpen: workspace.open === true
    readonly property string featureId: String(workspace.featureId || "")
    readonly property bool featureAvailable: workspace.available === true
    readonly property var flow: workspace.flow || ({})
    readonly property var flowActions: {
        var source=flow.actions || [], out=[];
        for(var i=0;i<source.length;i++) {
            if(source[i].id === "save") continue; // Chart toolbar owns image save.
            if(source[i].id === "refresh") continue; // Runtime already polls job state.
            // Keep the stop control in place while its enabled state changes.
            out.push(source[i]);
        } return out;
    }
    // Device progress numbers: completed stages and total stages. chart.stage is
    // the decoded display copy of the same fields; the legacy stage.index value is
    // intentionally never used here (completedStages is the completed count).
    readonly property int progressTotal: {
        var total = measurement.totalStages
        if (total === undefined || total === null) total = (currentChart.stage || {}).total
        if (total === undefined || total === null) total = typeof flow.steps === "number" ? flow.steps : (flow.steps || []).length
        var n = Number(total)
        return isFinite(n) && n > 0 ? Math.round(n) : 0
    }
    readonly property int progressStep: {
        var done = measurement.completedStages
        if (done === undefined || done === null) done = (currentChart.stage || {}).completed
        if (done === undefined || done === null) done = flow.step
        var n = Number(done)
        return isFinite(n) && n > 0 ? Math.round(n) : 0
    }
    readonly property int progressCurrent: {
        var current = measurement.currentStageIndex
        if (current === undefined || current === null) current = (currentChart.stage || {}).current
        var n = Number(current)
        return isFinite(n) ? Math.round(n) : root.progressStep
    }
    // A result (valid, or completed-but-invalid) is presented: the status line
    // keeps its tone and message but drops the run-progress digits, which belong
    // to a run. An active job keeps them so a re-run still shows progress.
    readonly property bool resultPresent: {
        var state = String(root.workspace.state || "")
        if (["running","starting","accepted","queued","stopping"].indexOf(state) >= 0) return false
        return state === "completed" || state === "stopped" || root.workspace.hasResult === true
    }
    readonly property var flowConfirmations: flow.confirmations || []
    readonly property var variants: workspace.variants || []
    readonly property var references: workspace.references || ({})
    readonly property var freshness: workspace.freshness || ({})
    function sanitized(chart) {
        var out={};
        for(var key in chart || {}) {
            if(key === "words" || key === "jobId" || key === "schema" || key === "resultSummary" || key === "params" || key === "paramForm")continue;
            out[key]=chart[key];
        }
        return out;
    }
    readonly property var currentChart: {
        if(variants.length>1){var v=variants[Math.min(variantIndex,variants.length-1)] || ({});if(v.chart)return sanitized(v.chart);return {kind:"capability",available:true,title:App.language === "en" ? v.labelEn : v.labelZh,text:root.tr("等待本项PL结果，期间可查看其他已完成项。","Waiting for this PL result; other completed views remain available."),emptyReason:root.tr("等待本项计算","Waiting for this variant")};}
        return sanitized(workspace.chart || ({}));
    }
    // Restored history (or a paused retained result) must stay visible even when
    // the device is disconnected and the feature is therefore not "available".
    readonly property bool chartHasContent: {
        var c = root.currentChart || ({});
        return (c.series && c.series.length > 0)
            || (c.frames && c.frames.length > 0)
            || (c.scalarRows && c.scalarRows.length > 0)
            || (c.categories && c.categories.length > 0)
            || (c.channels && c.channels.length > 0)
            || (c.raster && c.raster.matrix && c.raster.matrix.length > 0)
            || (c.imageUrl && String(c.imageUrl).length > 0)
            || String(c.text || "").length > 0
    }
    implicitHeight: 560
    readonly property bool roomGuided: ["room_decay","room_clarity","spectral_decay"].indexOf(featureId)>=0
    readonly property bool referenceGuided: featureId === "relative_insulation" || featureId === "stipa_experimental"
    property int clapCountdown: 0
    readonly property var measurement: workspace.measurementProgress || ({})
    Timer { id: clapTimer; interval: 1000; repeat: true
        onTriggered: {root.clapCountdown--;if(root.clapCountdown<=0){stop();App.featureConfirm(root.featureId,"stimulus","clap");App.featureAction(root.featureId,"run");}}
    }
    onFeatureIdChanged: {clapTimer.stop();clapCountdown=0;}
    onVisibleChanged: if(!visible && clapCountdown>0){clapTimer.stop();clapCountdown=0;}
    function tr(zh,en){return App.language === "en" ? en : zh;}
    function actionText(a) {
        if(roomGuided && a.id === "run")return workspace.hasResult===true ? tr("重新测试","Repeat test") : tr("准备脉冲/拍手","Prepare pulse / clap");
        if(referenceGuided && a.id === "reference")return featureId === "stipa_experimental" ? (workspace.measurementMode==="quick"?tr("①录制8秒参考","1. Record 8s reference"):tr("①录制15秒参考","1. Record 15s reference")) : tr("①建立参考A","1. Capture reference A");
        if(referenceGuided && a.id === "measure")return featureId === "stipa_experimental" ? tr("②录制测试并计算","2. Record test and calculate") : tr("②测量B并比较","2. Capture B and compare");
        if(featureId === "event_trigger" && a.id === "run")return tr("学习背景并监测","Learn background and monitor");
        return a.id === "run" ? App.t(featureId === "event_trigger" ? "studio.run_monitor" : "studio.run") : a.id === "export" ? App.t("studio.export") : String(a.label || "");
    }
    function guidance() {
        if(roomGuided){
            if(clapCountdown>0)return App.language === "en" ? "Starting in "+clapCountdown+"s. Wait for the clap prompt." : "准备好，"+clapCountdown+"秒后启动；看到拍手提示再拍。";
            if(workspace.state === "failed")return tr("本次检测/测量未成功，请准备后重新测试。","This attempt did not succeed. Prepare and retry.");
            if(measurement.phase === "capturing" && Number(measurement.capturedSamples)<Number(measurement.requiredSamples))return tr("现在播放一次测试脉冲或拍手，然后保持安静！","Play the test pulse or clap once, then stay quiet!");
            if(measurement.excitationDetected && workspace.state !== "completed")return tr("已捕获瞬态，正在检查衰减。","Transient captured. Checking decay.");
            if(["running","starting","accepted"].indexOf(workspace.state)>=0)return tr("正在准备或确认脉冲，请看采集提示。","Preparing or validating the impulse. Follow the capture prompt.");
            if(workspace.hasResult || workspace.state === "completed")return tr("本次测量结束，可查看结果或重新测试。无效指标显示为—。","Measurement finished. View results or retry. Invalid metrics show a dash.");
            return featureId === "room_clarity" ? tr("测早到/晚到能量比例（C50/C80/D50），与混响时间不同。","Compare early and late energy (C50/C80/D50), not decay time.") : featureId === "spectral_decay" ? tr("测1000Hz倍频带衰减；单次拍手后保持安静。","Measure 1000Hz octave-band decay. Clap once, then stay quiet.") : tr("测声音衰减时间（EDT/T20/T30）；单次拍手后保持安静。","Measure decay time (EDT/T20/T30). Clap once, then stay quiet.");
        }
        if(featureId === "stipa_experimental"){
            if(measurement.phase === "capturing")return "正在录音："+Number(measurement.capturedSamples||0)+" / "+Number(measurement.requiredSamples||0)+" 样本，请保持测试音播放。";
            if(measurement.phase === "computing" && Number(measurement.totalStages)>1){
                var computing = "录音已完成 · 已完成"+root.progressStep+"/"+root.progressTotal+"阶段";
                if(measurement.currentStageIndex !== undefined && measurement.currentStageIndex !== null)
                    computing += " · 当前第"+(Number(measurement.currentStageIndex)+1)+"阶段";
                return computing+" · 已用时"+Math.floor(Number(workspace.elapsedMs||0)/1000)+"秒 · 当前阶段已执行"+Number(measurement.executedInstructions||0)+"条指令；可停止。";
            }
            if(["running","starting","accepted"].indexOf(workspace.state)>=0)return tr("正在准备录音或恢复调度，请保持测试音播放。","Preparing capture or restoring scheduling. Keep the test track playing.");
            if(workspace.state === "completed" && workspace.resultValid === false)return tr("处理完成，但测量无效；请查看原因并重新录制。","Processing finished, but the measurement is invalid; check the reason and record again.");
            if(workspace.state === "completed" && workspace.hasResult===true)return tr("本次处理结束，请查看结果有效性；也可重新录制。","Processing ended. Check result validity, or record again.");
            return references.hasReference ? tr("参考已保存；重新播放同一STIPA音轨，保持同一测试音轨，再开始②。","Reference saved. Restart the same STIPA track, keep the same test track, then start step 2.") : tr("先播放配套STIPA研究音轨，再点击①录制参考；不是普通语音。","Play the supplied research STIPA track, then record reference. Do not use ordinary speech.");
        }
        if(workspace.jobRole === "reference")return ["running","starting","accepted"].indexOf(workspace.state)>=0 ? tr("正在建立参考A；不会自动开始B。请保持激励稳定。","Capturing reference A; B will not start automatically.") : tr("参考A已保存，尚未测量B。改变测量条件后确认并点击②。","Reference A saved; B has not been measured. Change conditions, confirm and press step 2.");
        if(["running","starting","accepted"].indexOf(workspace.state)>=0)return tr("正在取得频带数据并比较，请保持激励稳定。","Acquiring band data and comparing. Keep excitation steady.");
        if(workspace.state === "completed" && workspace.hasResult===true)return tr("比较完成。修改被测条件后可再次测量B，参考A保持不变。","Comparison complete. Change the test condition and measure B again; reference A is retained.");
        return references.hasReference ? tr("参考A已保存。保持声源与音量不变，改变被测条件，确认测量链后点击②。","Reference A saved. Keep source and volume unchanged, change the test condition, confirm the chain and start step 2.") : tr("先保持稳定激励，点击①保存参考A；之后才测量B。","Keep the excitation steady and capture reference A before measuring B.");
    }
    function runAction(id) {
        if(id === "stop"){clapTimer.stop();clapCountdown=0;}
        if(roomGuided && id === "run"){App.featureConfirm(featureId,"stimulus","clap");clapCountdown=3;clapTimer.start();return;}
        if (id === "save") chartItem.saveImage();
        else if (id === "export") App.exportFeatureRaw(featureId);
        else App.featureAction(featureId, id);
    }
    function qualification() {
        if(featureId === "stft")return App.t("studio.retained_note");
        if(featureId === "stipa_experimental")return App.t("studio.experimental");
        if(featureId === "noise_rating")return App.t("studio.noise_estimate");
        if(["room_decay","room_clarity","spectral_decay"].indexOf(featureId)>=0)return App.t("studio.room_approximate");
        if(featureId === "relative_insulation")return App.t("studio.relative_only");
        return String(flow.note || "");
    }
    function tone() {
        if (workspace.state === "failed") return Theme.error;
        if (workspace.state === "completed")
            return workspace.resultValid === false ? Theme.warn : Theme.ok;
        return Theme.textSecondary;
    }
    function actionIcon(id) { return id === "stop" ? "square" : id === "export" ? "download" : id === "save" ? "camera" : id === "reference" ? "target" : id === "compare" ? "git-compare" : id === "refresh" ? "refresh-cw" : "play"; }
    ColumnLayout {
        anchors.fill: parent; spacing: 6
        Rectangle {
            Layout.fillWidth: true; Layout.minimumHeight:82;Layout.preferredHeight:82;Layout.maximumHeight:82
            visible: root.roomGuided || root.referenceGuided
            color: Theme.panelBg; border.color: Theme.border; radius: 5
            Text {id:guideText;anchors.fill:parent;anchors.margins:14;text:root.guidance();maximumLineCount:2;elide:Text.ElideRight;wrapMode:Text.Wrap;color:Theme.textPrimary;font.family:Theme.fontFamily;font.pixelSize:18}
        }
        Text {
            Layout.fillWidth: true;visible:root.roomGuided
            Layout.minimumHeight:24;Layout.preferredHeight:24;Layout.maximumHeight:24
            text:String(root.currentChart.resultHint || "");maximumLineCount:1;elide:Text.ElideRight;wrapMode:Text.NoWrap;color:Theme.textSecondary;font.family:Theme.fontFamily;font.pixelSize:14
        }
        Text {
            Layout.fillWidth:true
            visible: false
            text: visible ? root.tr("测量通道 MIC", "Measurement MIC")+(Number(root.workspace.inputSelection.channel)+1)+root.tr(" · 自动选路，本次测量保持不变", " · auto-selected, locked for this measurement") : ""
            color:Theme.textSecondary;font.family:Theme.fontFamily;font.pixelSize:15
        }
        Flow {
            id: controls
            Layout.fillWidth: true; spacing: 6
            Repeater {
                model: root.flowActions.length
                delegate: AppButton {
                    required property int index
                    readonly property var modelData:root.flowActions[index] || ({})
                    objectName: root.roomGuided && modelData.id === "run" ? "roomPrepareButton" : ""
                    text: root.actionText(modelData)
                    iconName: root.actionIcon(modelData.id)
                    compact: true
                    variant: modelData.id === "run" || modelData.id === "measure" ? "primary" : modelData.id === "stop" ? "danger" : "secondary"
                    enabled: root.clapCountdown === 0 && root.featureAvailable && (root.roomGuided && modelData.id === "run" ? ["starting","accepted","running","queued","stopping"].indexOf(root.workspace.state)<0 : modelData.enabled !== false) && (modelData.id !== "export" || !App.exportBusy)
                    tooltip: String(modelData.reason || "")
                    onClicked: root.runAction(modelData.id)
                }
            }
            AppButton {objectName:"roomCancelPreparation";visible:root.clapCountdown>0;text:root.tr("取消准备","Cancel");compact:true;onClicked:{clapTimer.stop();root.clapCountdown=0;}}
            ComboBox {
                objectName:"measurementVariantSelector"
                visible: root.variants.length > 1; width: 230; height: 40
                id:variantSelector
                model:root.variants.length
                currentIndex:root.variantIndex
                displayText:{var v=root.variants[currentIndex]||({});return App.language==="en"?(v.labelEn||v.id||""):(v.labelZh||v.id||"");}
                delegate:ItemDelegate {required property int index;width:variantSelector.width;text:{var v=root.variants[index]||({});return App.language==="en"?(v.labelEn||v.id||""):(v.labelZh||v.id||"");}}
                font.family: Theme.fontFamily; font.pixelSize: 13
                onActivated: function(index) { App.featureConfirm(root.featureId,"variantIndex",index); }
            }
            ComboBox {
                objectName:"stipaMeasurementMode"
                visible:root.featureId==="stipa_experimental"
                enabled:!root.flow.running
                width:260;height:40
                model:[root.tr("完整测量 · 101阶段","Complete · 101 stages"),root.tr("快速体验 · 15阶段","Quick · 15 stages")]
                currentIndex:root.workspace.measurementMode==="quick"?1:0
                onActivated:function(index){App.featureConfirm(root.featureId,"measurementMode",index===1?"quick":"complete")}
                font.family:Theme.fontFamily;font.pixelSize:15
            }
            Text {visible:!!(root.workspace.inputSelection||{}).auto;text:"MIC"+(Number((root.workspace.inputSelection||{}).channel)+1)+root.tr(" · 自动"," · auto");font.pixelSize:14;color:Theme.textSecondary;height:32;verticalAlignment:Text.AlignVCenter}
            IconButton { iconName: "info"; tooltip: App.t("studio.measurement_notes"); onClicked: notes.open() }
        }
        RowLayout {
            visible:root.featureId==="noise_rating"
            Layout.fillWidth:true;Layout.minimumHeight:40;Layout.maximumHeight:40
            Text {text:root.tr("名义参考偏移 dB","Nominal reference offset dB");font.pixelSize:15;color:Theme.textPrimary}
            SpinBox {from:-20000;to:20000;value:Math.round(Number(root.workspace.noiseReferenceOffsetDb || 0)*100);stepSize:100;editable:true;enabled:!root.flow.running
                textFromValue:function(v){return (v/100).toFixed(2)}
                valueFromText:function(t){return Math.round(Number(t)*100)}
                onValueModified:App.featureConfirm(root.featureId,"noiseReferenceOffsetDb",value/100)}
            Text {text:root.tr("INMP441标称换算，可按参考调整","Nominal INMP441 conversion; adjustable");font.pixelSize:13;color:Theme.textSecondary}
        }
        Flow {
            Layout.fillWidth: true; spacing: 10; visible: false
            Repeater {
                model: root.flowConfirmations
                delegate: Row {
                    required property var modelData
                    spacing: 7
                    CheckBox {
                        visible: !modelData.options || modelData.options.length === 0
                        text: modelData.label || ""; checked: modelData.value === true
                        font.family: Theme.fontFamily; font.pixelSize: 13
                        onToggled: App.featureConfirm(root.featureId, modelData.id, checked)
                    }
                    Text { visible: !!modelData.options && modelData.options.length > 0; text: modelData.label || ""
                        color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 13; height: 32; verticalAlignment: Text.AlignVCenter }
                    ComboBox {
                        visible: !!modelData.options && modelData.options.length > 0
                        width: 160; height: 32; model: modelData.options || []; textRole: "label"; valueRole: "value"
                        font.family: Theme.fontFamily; font.pixelSize: 13
                        Component.onCompleted: { var i=indexOfValue(modelData.value); if(i>=0)currentIndex=i; }
                        onActivated: App.featureConfirm(root.featureId, modelData.id, currentValue)
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            visible:root.isOpen
            Layout.minimumHeight:32;Layout.preferredHeight:32;Layout.maximumHeight:32
            Rectangle { width: 5; height: 5; radius: 12; color: root.tone() }
            Text {
                objectName: "workspaceStatusText"
                Layout.fillWidth: true; Layout.minimumWidth: 0
                text: String((root.workspace.error || {}).reason || root.workspace.message || root.workspace.stateLabel || "")
                color: root.tone(); font.family: Theme.fontFamily; font.pixelSize: 12
                maximumLineCount: 1; wrapMode: Text.NoWrap; elide: Text.ElideRight
            }
            Text { objectName: "workspaceProgressValue"
                visible: root.progressTotal > 1 && !root.resultPresent
                text: String(root.progressStep) + " / " + String(root.progressTotal)
                color: Theme.textSecondary; font.family: Theme.fontMono; font.pixelSize: 12 }
        }
        Rectangle {
            id: chartSurface
            objectName: "analysisChartSurface"
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 200
            color: Theme.plotBg; border.color: Theme.border; border.width: 1; radius: 12
            FeatureChart {
                id: chartItem
                anchors.fill: parent; anchors.margins: 8
                chart: root.currentChart
                workspaceOverride: root.workspace
                visible: root.featureAvailable || root.chartHasContent
                titleOverride: String(root.workspace.shortName || root.workspace.name || "")
                showSourceBanner: false
                onSaveFailed: function(reason) { App.notifyFeatureSaveFailed(reason); }
            }
            EmptyState {
                anchors.fill: parent; anchors.margins: 48
                visible: !root.featureAvailable && !root.chartHasContent
                title: App.connectionState === "connected" ? App.t("studio.not_ready") : App.t("studio.connect_title")
                reason: App.connectionState === "connected" ? App.t(root.status.featureApiEnabled === false ? "studio.update_device" : "studio.unavailable_hint") : App.t("studio.connect_hint")
                hint: ""; iconName: "audio-waveform"
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: false
            Text { Layout.fillWidth: true; Layout.minimumWidth: 0
                text: root.qualification()
                color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 12
                elide: Text.ElideRight; maximumLineCount: 2; wrapMode: Text.Wrap }
        }
    }
    Popup {
        id: notes
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(620, parent ? parent.width-48 : 620)
        height: Math.min(400, parent ? parent.height-80 : 400)
        modal: true; padding: 20; closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: Theme.panelBg; border.color: Theme.border; radius: 6 }
        ScrollView {
            anchors.fill: parent
            Text {
                width: notes.availableWidth
                text: String(root.flow.note || "") + "\n\n" + String(root.workspace.validity || "") + "\n\n" + (root.workspace.notes || []).join("\n\n") + "\n\n" + String(root.references.note || "")
                color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 14; wrapMode: Text.Wrap
            }
        }
    }
}