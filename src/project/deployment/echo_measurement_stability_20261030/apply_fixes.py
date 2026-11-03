from pathlib import Path
import json
R=Path.cwd();A=R/'apps/sixmic-desktop';O=R/'deployment/echo_measurement_stability_20261030'
p=A/'ui/qml/components/Panel.qml';s=p.read_text(encoding='utf-8');a=s.index('    // Use intrinsic');b=s.index('    Item { id: inner',a);s=s[:a]+'''    // Explicit hint only: a fill-anchored child's implicit size may depend on us.
    property real preferredContentHeight: 160
    implicitHeight: preferredContentHeight + padding * 2
'''+s[b:];p.write_text(s,encoding='utf-8')
p=A/'ui/qml/components/FeatureWorkspace.qml';s=p.read_text(encoding='utf-8').replace('            if(source[i].id === "stop" && source[i].enabled === false) continue;','            // Keep the stop control in place while its enabled state changes.')
s=s.replace('Layout.fillWidth: true; Layout.preferredHeight: guideText.implicitHeight+28','Layout.fillWidth: true; Layout.minimumHeight:82;Layout.preferredHeight:82;Layout.maximumHeight:82')
s=s.replace('property int variantIndex: 0','property int variantIndex: Number(workspace.selectedVariant || 0)').replace(';variantIndex=0;',';')
s=s.replace('onActivated: function(index) { root.variantIndex=index; }','onActivated: function(index) { App.featureConfirm(root.featureId,"variantIndex",index); }')
s=s.replace('visible: !!root.workspace.error || root.progressTotal > 1 || ["starting","queued","stopping"].indexOf(root.workspace.state)>=0 || /采集|捕获|计算|处理/.test(String(root.workspace.message||""))','visible:root.isOpen\n            Layout.minimumHeight:32;Layout.preferredHeight:32;Layout.maximumHeight:32')
s=s.replace('maximumLineCount: 2; wrapMode: Text.Wrap; elide: Text.ElideRight','maximumLineCount: 1; wrapMode: Text.NoWrap; elide: Text.ElideRight')
# Explicit nominal reference setting; the PL performs the conversion/curve test.
needle='        Flow {\n            Layout.fillWidth: true; spacing: 10; visible: false'
s=s.replace(needle,'''        RowLayout {
            visible:root.featureId==="noise_rating"
            Layout.fillWidth:true;Layout.minimumHeight:40;Layout.maximumHeight:40
            Text {text:root.tr("名义参考偏移 dB","Nominal reference offset dB");font.pixelSize:15;color:Theme.textPrimary}
            SpinBox {from:-20000;to:20000;value:Math.round(Number(root.workspace.noiseReferenceOffsetDb || 0)*100);stepSize:100;editable:true;enabled:!root.flow.running
                textFromValue:function(v){return (v/100).toFixed(2)}
                valueFromText:function(t){return Math.round(Number(t)*100)}
                onValueModified:App.featureConfirm(root.featureId,"noiseReferenceOffsetDb",value/100)}
            Text {text:root.tr("INMP441标称换算，可按参考调整","Nominal INMP441 conversion; adjustable");font.pixelSize:13;color:Theme.textSecondary}
        }
'''+needle)
p.write_text(s,encoding='utf-8')
p=A/'ui/features/runtime.py';s=p.read_text(encoding='utf-8').replace('        self._variant_pending: dict[str, list[dict[str, Any]]] = {}','        self._variant_pending: dict[str, list[dict[str, Any]]] = {}\n        self._selected_variants: dict[str, int] = {}')
# Initialize choices on opening, not only after starting all choices.
s=s.replace('        self._open_feature = feature_id','''        if flow_specs.flow_kind(self.catalog.feature(feature_id)) == "dual_variant" and feature_id not in self._variants:
            self._variants[feature_id] = [flow_specs.variant_definition(self.catalog.feature(feature_id), r) for r in flow_specs.run_plan(self.catalog.feature(feature_id))]
        self._open_feature = feature_id''',1)
needle='        if feature_id == "stipa_experimental" and confirmation_id == "measurementMode":'
s=s.replace(needle,'''        if feature_id in {"frequency_time_weighting", "noise_rating"} and confirmation_id == "variantIndex":
            try: selected = int(value)
            except (TypeError, ValueError): return
            runs=flow_specs.run_plan(feature)
            if not 0<=selected<len(runs):return
            was_live=feature_id in self._live_requested
            if self._active_feature_job(feature_id):self.stop(feature_id)
            self._variant_pending[feature_id]=[]
            self._selected_variants[feature_id]=selected
            self._errors.pop(feature_id,None)
            if was_live:
                self._live_requested.add(feature_id);self._live_due[feature_id]=self._clock()+.1;self._auto_stopped.discard(feature_id)
            self._changed();return
        if feature_id=="noise_rating" and confirmation_id=="noiseReferenceOffsetDb":
            try:offset=float(value)
            except (TypeError,ValueError):return
            if math.isfinite(offset) and -200<=offset<=200 and not self._active_feature_job(feature_id):
                self._ensure_confirmations(feature_id)[confirmation_id]=offset;self._changed()
            return
'''+needle,1)
# Execute a single selected variant in the actual instrument; leave historical test harness batching intact.
s=s.replace('        self._variant_pending[owner] = [dict(run) for run in plan]','''        selected=self._selected_variants.get(owner,0) if self._instrument_mode and owner in {"frequency_time_weighting","noise_rating"} else None
        runs=[plan[min(selected,len(plan)-1)]] if selected is not None and plan else plan
        self._variant_pending[owner] = [dict(run) for run in runs]''',1)
s=s.replace('        variants[0]["state"] = "running"\n        for variant in variants[1:]:\n            variant["state"] = "idle"','''        for variant in variants:
            variant["state"]="running" if variant["id"]==first.get("variantId") else "idle"''',1)
s=s.replace('        params = dict(job.params)\n        if job.owner=="directed_das":','''        params = dict(job.params)
        if job.owner=="noise_rating":
            params["referenceOffsetDb"]=self._ensure_confirmations(job.owner).get("noiseReferenceOffsetDb",123.01)
            params["calibrationSource"]="INMP441 nominal sensitivity conversion, editable reference"
        if job.owner=="directed_das":''',1)
s=s.replace('            "measurementMode": self._ensure_confirmations(fid)', '            "selectedVariant": self._selected_variants.get(fid,0),\n            "noiseReferenceOffsetDb": self._ensure_confirmations(fid).get("noiseReferenceOffsetDb",123.01) if fid=="noise_rating" else 0,\n            "measurementMode": self._ensure_confirmations(fid)',1)
# The explicit reference button must use the same selected STIPA sample count as run().
needle='        plan = flow_specs.run_plan(feature)\n        run = plan[0]'
s=s.replace(needle,'''        plan = flow_specs.run_plan(feature)
        if kind=="staged_stipa":
            plan[0]["params"]["samples"]=144000 if self._ensure_confirmations(feature_id).get("measurementMode")=="quick" else 720000
        run = plan[0]''',1)
# Pending updates retain the last measured chart, never relabel it as a fresh frame.
s=s.replace('        if result is not None and job is None:', '''        if result is not None and job is not None and job.active():
            chart=dict(result.get("chart") or {});chart["pendingUpdate"]=True
            return chart
        if result is not None and job is None:''',1)
# A catalog that is still being fetched is a loading state, not unsupported functionality.
s=s.replace('            self._notify_safe("warn", "功能不可用", reason.get("zh", ""))','''            if self._connected and self._api_enabled and not self.catalog.device_catalog_complete:
                self.refresh_catalog()
                self._messages[feature_id]=_bilingual("正在同步功能目录，请稍候","Synchronizing feature catalog")
            else:self._notify_safe("warn", "功能暂不可用", reason.get("zh", ""))''')
p.write_text(s,encoding='utf-8')
p=A/'ui/viewmodels/app_view_model.py';s=p.read_text(encoding='utf-8');needle='        if not connected:\n            self._feature_api_retry_count = 0';s=s.replace(needle,'''        if connected and "enabled" not in info:
            # Missing capability data during refresh is unknown, not disabled.
            if not self._feature_api_retry_pending:
                self._feature_api_retry_pending=True
                QTimer.singleShot(300,self._retry_refresh_feature_api)
            return
'''+needle,1);p.write_text(s,encoding='utf-8')
print('Stable controls / selected-only variants / nominal reference / quick reference path patched')
