from pathlib import Path
R=Path.cwd();A=R/'apps/sixmic-desktop'
p=A/'ui/qml/components/charts/ReadoutStrip.qml';s=p.read_text(encoding='utf-8');s=s.replace('    implicitHeight: wrapRows ? Math.max(40,wrapped.implicitHeight) : 40; height: implicitHeight','''    readonly property int gridColumns:Math.max(1,Math.floor(width/235))
    readonly property int gridRows:Math.ceil(Math.min(maxItems,(rows||[]).length)/gridColumns)
    implicitHeight: wrapRows ? Math.max(40,gridRows*40) : 40; height: implicitHeight''')
a=s.index('    Flow {');b=s.index('    Flickable {',a)
s=s[:a]+'''    Grid {
        id:wrapped;width:root.width;columns:root.gridColumns;columnSpacing:12;rowSpacing:4;visible:root.wrapRows
        Repeater {
            model:root.wrapRows ? (root.rows||[]).slice(0,root.maxItems) : []
            delegate:Item {
                required property var modelData
                width:Math.max(0,(root.width-12*(root.gridColumns-1))/root.gridColumns);height:36
                RowLayout {anchors.fill:parent;spacing:6
                    Text {Layout.maximumWidth:90;Layout.fillWidth:true;text:App.language!=="en" && modelData.displayLabel?modelData.displayLabel:(modelData.label||"");elide:Text.ElideRight;color:Theme.textSecondary;font.pixelSize:14}
                    Text {Layout.maximumWidth:110;text:root.valueText(modelData);elide:Text.ElideRight;color:modelData.valid===false?Theme.textDisabled:Theme.textPrimary;font.family:Theme.fontMono;font.pixelSize:17}
                    Text {text:modelData.unit||"";color:Theme.textSecondary;font.pixelSize:13}
                }
            }
        }
    }
'''+s[b:];p.write_text(s,encoding='utf-8')
p=A/'ui/features/decoder.py';s=p.read_text(encoding='utf-8');needle='    chart["xAxis"] = ctx.frequency_axis(delta_points)\n    chart["yAxis"] = _axis(*_y_range(delta_points), label="差值", unit="FS²/bin")';repl='''    chart["xAxis"] = ctx.frequency_axis(delta_points)
    top_series=[v for v in chart["series"] if v.get("role")!="delta"]
    top_points=[p for v in top_series for p in v.get("points",[])]
    chart["yAxis"] = _axis(*_y_range(top_points), label="功率谱", unit="FS²/bin")
    chart["deltaYAxis"] = _axis(*_y_range(delta_points), label="功率差值 B−A", unit="FS²/bin")
    chart["panels"]=[{"render":"line","title":"冻结参考 A 与当前 B","series":top_series},
                      {"render":"line","title":"差值 B−A","series":[chart["series"][0]]}]
    if ctx.feature_id=="relative_limit":
        db_offset=ctx.layout.get("change_db_offset")
        if db_offset is not None:
            db_values=[f32(v) for v in words[int(db_offset):int(db_offset)+count]]
            db_points,_,_=_make_points(xs,db_values)
            chart["deltaYAxis"]=_axis(-12,12,label="相对变化",unit="dB")
            change=ctx.series("变化 dB",db_points,role="delta",color=ctx.labels()[2])
            chart["series"]=[change]+top_series
            threshold=float(ctx.layout.get("threshold_db",6))
            summary=int(ctx.layout.get("summary_offset",3*count))
            chart["scalarRows"]=[_scalar_row("越限频点",sum(bool(_finite(v) and v!=0) for v in flag_ys),"个",True),_scalar_row("限值",threshold,"dB",True)]
            chart["referenceLines"]=[{"value":threshold,"label":"增加限值","unit":"dB"},{"value":-threshold,"label":"减小限值","unit":"dB"}]
        chart["kind"]="statistics"
        chart["panels"]=[{"render":"line","title":"相对参考的变化与限值","series":[v for v in chart["series"] if v.get("role")=="delta"],"xAxis":chart["xAxis"],"yAxis":chart.get("deltaYAxis"),"referenceLines":chart.get("referenceLines",[])},
                          {"render":"line","title":"越限标志  1=越限  0=正常","series":[ctx.series("PL越限标志",[[x,float(bool(_finite(y) and y!=0))] for x,y in zip(xs,flag_ys)])],"xAxis":chart["xAxis"],"yAxis":_axis(-.05,1.1,label="越限状态",unit="")}]
'''
assert needle in s;s=s.replace(needle,repl,1)
# Do not overwrite the dB limit lines with the freeze zero-line.
s=s.replace('    chart["referenceLines"] = [{"value": 0.0, "label": "无变化", "unit": "FS²/bin"}] \\\n        if delta_points else []','    if ctx.feature_id!="relative_limit":chart["referenceLines"] = [{"value":0.0,"label":"无变化","unit":"FS²/bin"}] if delta_points else []',1)
# Reuse the same conversion as the PL rating comparison; no rating is computed on PC.
s=s.replace('            levels.append(f32(words[position]))','            raw_level=f32(words[position])\n            offset=f32(words[31]) if len(words)>31 else 0.0\n            levels.append(raw_level+offset if _finite(raw_level) and _finite(offset) else float("nan"))',1)
s=s.replace('    chart["yAxis"] = _axis(*_y_range(level_points or []), label="电平", unit="dB")','    all_points=[p for row in series for p in row.get("points",[])]\n    chart["yAxis"] = _axis(*_y_range(all_points), label="名义参考电平", unit="dB")',1)
p.write_text(s,encoding='utf-8')
# Stable variant-specific time history makes the measured value visible beside the fixed A/C/Z coefficients.
p=A/'ui/features/runtime.py';s=p.read_text(encoding='utf-8').replace('        self._selected_variants: dict[str, int] = {}','        self._selected_variants: dict[str, int] = {}\n        self._weighting_history: dict[str, list[tuple[float,float]]] = {}')
needle='        variants = self._variants.setdefault(job.owner, [])\n        for variant in variants:'
s=s.replace(needle,'''        if job.owner=="frequency_time_weighting" and job.variant_id in {"A","C","Z"}:
            rows={r.get("label"):r for r in chart.get("scalarRows",[])}
            level=rows.get("计权电平",{})
            if level.get("valid") and isinstance(level.get("value"),(int,float)):
                key=job.variant_id+":"+str(job.params.get("channel",0))
                history=self._weighting_history.setdefault(key,[]);history.append((self._clock(),float(level["value"])));del history[:-120]
                start=history[0][0]
                trend={"render":"line","title":job.variant_id+"计权电平随时间变化","series":[{"name":job.variant_id+"电平","points":[[t-start,y] for t,y in history],"color":"#57C8FF"}],"xAxis":{"min":0,"max":max(1,self._clock()-start),"unit":"s","label":"接收时间"},"yAxis":{"min":-120,"max":0,"label":"数字电平","unit":"dBFS"}}
                chart=dict(chart);chart["panels"]=[trend]+list(chart.get("panels",[]))[:1]
        variants = self._variants.setdefault(job.owner, [])
        for variant in variants:''',1)
p.write_text(s,encoding='utf-8')
print('Fixed readout geometry and A/B units; dedicated limit flags; weighted histories')
