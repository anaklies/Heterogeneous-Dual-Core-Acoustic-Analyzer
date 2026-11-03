from pathlib import Path
import json
R=Path.cwd();p=R/'apps/sixmic-desktop/ui/features/runtime.py';s=p.read_text(encoding='utf-8')
needle='        values = self._ensure_confirmations(feature_id)\n        if kind == "room_stimulus":'
s=s.replace(needle,'''        values = self._ensure_confirmations(feature_id)
        if kind == "staged_stipa":
            selected = values.get("measurementMode", "complete")
            samples = 144000 if selected == "quick" else 720000
            plan[0]["params"]["samples"] = samples
            plan[1]["params"].update(samples=samples, measurementMode=selected)
        if kind == "room_stimulus":''',1)
needle='        if feature_id=="directed_das" and confirmation_id in ("azimuth_deg","elevation_deg"):'
s=s.replace(needle,'''        if feature_id == "stipa_experimental" and confirmation_id == "measurementMode":
            if value not in ("complete", "quick") or self._active_feature_job(feature_id):
                return
            values = self._ensure_confirmations(feature_id)
            if values.get("measurementMode", "complete") != value:
                values["measurementMode"] = value
                self._references.pop(feature_id, None)
                self._drop_raw(feature_id)
                self._results.pop(feature_id, None)
                for key, old in list(self._jobs.items()):
                    if old.owner == feature_id and not old.active(): self._jobs.pop(key, None)
                self._messages.pop(feature_id, None)
                self._changed()
            return
        if feature_id=="directed_das" and confirmation_id in ("azimuth_deg","elevation_deg"):''',1)
s=s.replace('            "manualDirection": dict(self._manual_direction)', '            "measurementMode": self._ensure_confirmations(fid).get("measurementMode", "complete") if fid=="stipa_experimental" else "",\n            "manualDirection": dict(self._manual_direction)',1)
p.write_text(s,encoding='utf-8')
p=R/'apps/sixmic-desktop/ui/features/decoder.py';s=p.read_text(encoding='utf-8');s=s.replace('    chart["indexLabel"]="实验STIPA指数"','''    quick = (ctx.variant.get("params") or {}).get("measurementMode") == "quick"
    chart["indexLabel"]="快速调制保持指数" if quick else "实验STIPA指数"
    if quick: chart["title"]="快速语音传输评估"''',1)
s=s.replace('"total": int(ctx.decode.get("stagesTotal") or 101)', '"total": 15 if quick else int(ctx.decode.get("stagesTotal") or 101)',1)
s=s.replace('    chart["text"] = "实验性 STIPA：101 阶段真实进度；不是认证 STIPA，不得宣传为无源 STIPA。"','    chart["text"] = "快速体验 · 500/1000/2000 Hz三频带估计" if quick else "完整实验STIPA · 101阶段"',1);p.write_text(s,encoding='utf-8')
p=R/'apps/sixmic-desktop/ui/qml/components/FeatureWorkspace.qml';s=p.read_text(encoding='utf-8');needle='            Text {visible:!!(root.workspace.inputSelection||{}).auto;'
s=s.replace(needle,'''            ComboBox {
                objectName:"stipaMeasurementMode"
                visible:root.featureId==="stipa_experimental"
                enabled:!root.flow.running
                width:260;height:40
                model:[root.tr("完整测量 · 101阶段","Complete · 101 stages"),root.tr("快速体验 · 15阶段","Quick · 15 stages")]
                currentIndex:root.workspace.measurementMode==="quick"?1:0
                onActivated:function(index){App.featureConfirm(root.featureId,"measurementMode",index===1?"quick":"complete")}
                font.family:Theme.fontFamily;font.pixelSize:15
            }
''' +needle,1);p.write_text(s,encoding='utf-8')
p=R/'apps/sixmic-desktop/ui/qml/components/charts/BarChart.qml';s=p.read_text(encoding='utf-8').replace('    property bool inspectionEnabled: false','    property bool inspectionEnabled: false\n    property bool showValueLabels: true',1).replace('if (vw < bw2 + 8 && cx - vw / 2 > lastValueRight + 8)', 'if (showValueLabels && vw < bw2 + 8 && cx - vw / 2 > lastValueRight + 8)').replace('Math.max(pr.y + 10, barTop - 4)','Math.max(pr.y + st.fsSmall + 4, barTop - 4)');p.write_text(s,encoding='utf-8')
p=R/'apps/sixmic-desktop/ui/qml/pages/OverviewPage.qml';s=p.read_text(encoding='utf-8');needle='                    BarChart {Layout.fillWidth:true;Layout.fillHeight:true;categories:page.d.levels||[];';s=s.replace(needle,'''                    GridLayout {
                        Layout.fillWidth:true;Layout.minimumHeight:100;Layout.maximumHeight:100
                        columns:3;columnSpacing:8;rowSpacing:6
                        Repeater {
                            model:6
                            delegate:Column {
                                required property int index
                                readonly property var level:(page.d.levels||[])[index]||({})
                                Layout.fillWidth:true;spacing:2
                                Row {spacing:5
                                    Rectangle {width:7;height:7;radius:3.5;color:Theme.channelColors[index];anchors.verticalCenter:parent.verticalCenter}
                                    Text {text:"MIC"+(index+1);font.pixelSize:12;color:Theme.textSecondary}
                                }
                                Text {
                                    objectName:"overviewMicValue"+index
                                    text:level.valid!==false && typeof level.value==="number" && isFinite(level.value)?Number(level.value).toFixed(1):"—"
                                    font.family:Theme.fontMono;font.pixelSize:18;font.weight:Font.DemiBold;color:Theme.textPrimary
                                }
                            }
                        }
                    }
                    BarChart {showValueLabels:false;Layout.fillWidth:true;Layout.fillHeight:true;categories:page.d.levels||[];''',1);p.write_text(s,encoding='utf-8')
# Additive device plan selection. Full graph/files remain unchanged.
O=R/'deployment/echo_stipa_quick_20261030';j=json.loads((O/'before/DEVICE_INTERFACE_REGISTRY.json').read_text(encoding='utf-8'));f=next(v for v in j['features'] if v['featureId']=='stipa_experimental');f['params']['measurementMode']={'default':'complete','enum':['complete','quick']};f.setdefault('variants',[]).append({'completeParams':{'samples':144000,'measurementMode':'quick'},'file':'plans/stipa_quick.json','kind':'stage_graph','noCpuDSP':True});f['quickMode']={'samples':144000,'stages':15,'bandsHz':[500,1000,2000],'indexLabel':'rapid modulation-transfer estimate'}
(O/'registry/INTERFACE_REGISTRY.json').write_text(json.dumps(j,ensure_ascii=False,indent=2),encoding='utf-8')
print('PC mode flow, stable six-channel readouts, additive registry patched')
