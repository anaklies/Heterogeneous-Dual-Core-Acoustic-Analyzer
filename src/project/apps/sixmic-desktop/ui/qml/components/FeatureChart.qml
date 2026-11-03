// FeatureChart - routes App.featureWorkspace.chart to the professional Qt Quick
// chart for its payload kind. The header keeps the page's title/icon on the left
// and compact view-only operations on the right: fit, log/linear (spectrum kinds),
// A/B cursor, legend, 2D/3D (STFT waterfall / DAS polar-rect) and save image.
// None of those operations starts a PL measurement: they only change local
// display state (and optionally persist a display preference through
// App.setFeatureViewOption). Saving uses grabToImage and the AppViewModel-provided
// path (App.saveFeatureChart). All labels/units/validity text come from the
// payload/page - no UI text is hardcoded inside the chart layer.
import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "charts"
import "charts/FeaturePayload.js" as F

Item {
    id: root
    objectName: "featureChart"
    clip: true

    // ------------------------------------------------------------ page inputs
    property var chart: {
        if (typeof App !== "undefined" && App && App.featureWorkspace
                && App.featureWorkspace.chart !== undefined) {
            return App.featureWorkspace.chart
        }
        return null
    }
    // Owning page can inject the workspace it already read so each chart
    // update does not convert the whole read model again per binding.
    property var workspaceOverride: null
    property string iconSource: ""
    property string titleOverride: ""
    property string subtitleOverride: ""
    property string emptyText: ""
    property string framesUnavailableText: ""
    property string sourceKindOverride: ""
    property string sourceLabelOverride: ""
    property string validityOverride: ""
    property var notesOverride: []
    property bool showSourceBanner: true
    property var bandRampFallback: ["#6A5ACD", "#4E6BD6", "#3E8FC9", "#37AFAF", "#72D6C9", "#A9D96C", "#E2E649"]
    property string fitTooltip: ""
    property string logTooltip: ""
    property string cursorTooltip: ""
    property string legendTooltip: ""
    property string threeDTooltip: ""
    property string saveTooltip: ""

    // ----------------------------------------------- display state (view only)
    property bool cursorEnabled: false
    property bool legendVisible: true
    property bool threeDActive: false
    property bool dasRect: false
    property bool logScaleEnabled: true
    property var lineCursorA: null
    property var lineCursorB: null
    property var heatCursor: null
    property var waveCursorA: null
    property var waveCursorB: null
    property int fitCounter: 0

    // ------------------------------------------------------------- page signals
    signal imageCaptured(string path)
    signal saveFailed(string reason)
    signal eventActivated(int index)

    // ------------------------------------------------------------- payload view
    readonly property var payload: (root.chart && typeof root.chart === "object") ? root.chart : ({})
    readonly property string kind: root.payload.kind !== undefined && root.payload.kind !== null
                                     ? String(root.payload.kind) : ""
    readonly property string featureId: {
        var w = root.workspaceData
        if (w && w.featureId !== undefined) return String(w.featureId)
        return ""
    }
    readonly property var workspaceData: {
        var injected = root.workspaceOverride
        if (injected !== null && injected !== undefined) return injected
        if (typeof App !== "undefined" && App && App.featureWorkspace !== undefined) return App.featureWorkspace
        return null
    }
    readonly property bool unavailable: root.workspaceData && root.workspaceData.available === false
    readonly property bool chartBusy: root.payload.busy === true
    // STIPA measurement mode from the workspace (quick = 15 stages, complete = 101).
    readonly property bool stipaQuickMode: {
        var w = root.workspaceData
        return !!(w && String(w.measurementMode || "") === "quick")
    }
    // A job is in flight. An earlier retained result stays in the workspace while
    // a re-run is active, so running state wins over hasResult for progress.
    readonly property bool workspaceRunning: {
        var w = root.workspaceData
        if (!w) return false
        var state = String(w.state === undefined || w.state === null ? "" : w.state)
        return ["running", "starting", "accepted", "queued", "stopping"].indexOf(state) >= 0
    }
    // The page already presents a result (valid, or completed-but-invalid): the
    // STIPA chart hides its run progress then and keeps the index/readouts/caption.
    readonly property bool resultPresented: {
        if (root.workspaceRunning) return false
        var w = root.workspaceData
        if (!w) return false
        var state = String(w.state === undefined || w.state === null ? "" : w.state)
        if (state === "completed" || state === "stopped") return true
        return w.hasResult === true
    }
    // STIPA stage shown by the chart. While a job is active the chart payload may
    // still be the previous result (its stage reports every stage done); the live
    // job progress in the workspace is authoritative then, so a re-run keeps a
    // real progress display instead of hiding it as "finished".
    readonly property var stipaStage: {
        var w = root.workspaceData
        if (w && root.workspaceRunning) {
            var progress = w.measurementProgress
            if (progress && F.isNum(progress.totalStages) && progress.totalStages > 0) {
                var total = Math.round(progress.totalStages)
                var completed = F.isNum(progress.completedStages) ? Math.round(progress.completedStages) : 0
                var current = F.isNum(progress.currentStageIndex) ? Math.round(progress.currentStageIndex) : completed
                var label = root.payload.stage && root.payload.stage.label !== undefined
                        ? String(root.payload.stage.label) : ""
                return {completed: Math.max(0, Math.min(completed, total)),
                        total: total,
                        current: Math.max(0, Math.min(current, total)),
                        label: label}
            }
        }
        return root.payload.stage
    }
    readonly property int dataRevision: {
        var r = root.payload.chartRevision
        return F.isNum(r) ? Math.round(r) : (parseInt(String(r || "0").slice(0,7),16)||0)
    }
    readonly property var seriesList: F.normalizeSeries(root.payload.series)
    readonly property var markerList: F.normalizeMarkers(root.payload.markers)
    readonly property var refLines: F.normalizeReferenceLines(root.payload.referenceLines)
    readonly property var refBands: F.normalizeReferenceBands(root.payload.referenceBands)
    readonly property var categoryList: F.normalizeCategories(root.payload.categories)
    readonly property var scalarList: F.normalizeScalarRows(root.payload.scalarRows)
    readonly property var imageUrl: root.payload.imageUrl !== undefined && root.payload.imageUrl !== null
                                   ? String(root.payload.imageUrl) : ""
    readonly property string emptyReasonText: {
        if (root.payload.emptyReason !== undefined && String(root.payload.emptyReason).length)
            return String(root.payload.emptyReason)
        if (root.workspaceData && root.workspaceData.disabledReason !== undefined
                && String(root.workspaceData.disabledReason).length)
            return String(root.workspaceData.disabledReason)
        return ""
    }
    readonly property bool chartLogDefault: root.payload.xAxis !== undefined && root.payload.xAxis !== null
                                            && String(root.payload.xAxis.scale === undefined ? "" : root.payload.xAxis.scale) === "log"
    readonly property var frameInfo: F.frames(root.payload)
    readonly property var waveData: F.waveformDisplay(root.payload, root.seriesList, 4096)
    readonly property var levelMeterList: F.levelMeters(root.payload, root.categoryList)
    readonly property var stipaInfo: F.stipaIndex(root.payload, root.scalarList)
    readonly property var panelsResolved: {
        var explicit = F.normalizePanels(root.payload.panels)
        if (explicit.length) return explicit
        var k = root.kind
        if (k === "coherence-phase") return F.coherencePanels(root.seriesList, root.payload.yAxis)
        if (k === "weighting") return F.weightingPanels(root.seriesList, null)
        if (k === "statistics") return F.statisticsPanels(root.seriesList)
        return []
    }
    readonly property var abParts: F.abSplit(root.seriesList)

    readonly property var effectiveXAxis: {
        var ax = root.payload.xAxis
        if (!root.showLogButton || !ax) return ax
        var copy = {}
        for (var k in ax) copy[k] = ax[k]
        copy.scale = root.logScaleEnabled ? "log" : "linear"
        return copy
    }
    readonly property var resolvedBandRamp: F.bandRamp(root.payload, root.bandRampFallback)
    readonly property var bandScale: F.bandColorScale(root.payload, root.categoryList, root.payload.yAxis, root.resolvedBandRamp)
    readonly property string barsXMode: (function () {
        for (var i = 0; i < root.categoryList.length; i++) {
            if (!F.isNum(root.categoryList[i].centerFrequency)) return "category"
        }
        return root.categoryList.length ? "centerFrequency" : "category"
    })()
    readonly property var barReferenceValues: {
        var explicit = F.asList(root.payload.referenceValues)
        if (explicit.length) return explicit
        if (root.kind === "insulation-bars") {
            var hasNegative = false
            for (var i = 0; i < root.categoryList.length; i++) {
                if (F.isNum(root.categoryList[i].value) && root.categoryList[i].value < 0) { hasNegative = true; break }
            }
            if (hasNegative) return [{ value: 0, label: "" }]
        }
        return []
    }

    // ------------------------------------------------------ toolbar / header text
    readonly property string titleText: {
        if (root.titleOverride.length) return root.titleOverride
        if (root.payload.title !== undefined && String(root.payload.title).length) return String(root.payload.title)
        var w = root.workspaceData
        if (w) {
            if (w.shortName !== undefined && String(w.shortName).length) return String(w.shortName)
            if (w.name !== undefined && String(w.name).length) return String(w.name)
        }
        return ""
    }
    readonly property string subtitleText: {
        if (root.subtitleOverride.length) return root.subtitleOverride
        if (root.payload.subtitle !== undefined && String(root.payload.subtitle).length) return String(root.payload.subtitle)
        return ""
    }
    readonly property string resolvedIconSource: {
        if (root.iconSource.length) return root.iconSource
        var w = root.workspaceData
        if (!w || w.icon === undefined || !String(w.icon).length) return ""
        if (typeof App !== "undefined" && App && typeof App.iconSource === "function") {
            try { return String(App.iconSource(String(w.icon), Theme.textPrimary)) } catch (e) { return "" }
        }
        return ""
    }
    readonly property string sourceKind: {
        if (root.sourceKindOverride.length) return root.sourceKindOverride
        var w = root.workspaceData
        if (w && w.sourceKind !== undefined && String(w.sourceKind).length) return String(w.sourceKind)
        if (root.payload.sourceKind !== undefined && String(root.payload.sourceKind).length) return String(root.payload.sourceKind)
        return ""
    }
    readonly property string sourceLabel: {
        if (root.sourceLabelOverride.length) return root.sourceLabelOverride
        var w = root.workspaceData
        if (w && w.sourceLabel !== undefined && String(w.sourceLabel).length) return String(w.sourceLabel)
        return ""
    }
    readonly property string validityText: {
        if (root.validityOverride.length) return root.validityOverride
        var w = root.workspaceData
        if (w && w.validity !== undefined) return String(w.validity)
        if (root.payload.validity !== undefined) return String(root.payload.validity)
        return ""
    }
    readonly property var sourceNotes: {
        if (root.notesOverride && root.notesOverride.length) return root.notesOverride
        var w = root.workspaceData
        if (w && w.notes && w.notes.length) return w.notes
        if (root.payload.notes && root.payload.notes.length) return root.payload.notes
        return []
    }
    readonly property bool hasSource: root.sourceKind.length > 0 || root.sourceLabel.length > 0

    // ------------------------------------------------------ operation availability
    readonly property string routeToken: root.contentToken()
    readonly property bool isPlotKind: {
        var t = root.routeToken
        return t === "line" || t === "bars-readout" || t === "stft" || t === "das"
            || t === "panel" || t === "readout-line" || t === "ab" || t === "noise" || t === "waveform"
    }
    readonly property bool showFitButton: root.isPlotKind
    readonly property bool showLogButton: root.kind === "spectrum" || root.kind === "zoom-spectrum"
    readonly property bool showCursorButton: {
        var t = root.routeToken
        var k = root.kind
        if (k === "stft") return !root.threeDActive
        if (k === "das-map") return root.dasRect
        if (k === "waveform") return true
        return t === "line" || t === "panel" || t === "readout-line" || t === "ab" || t === "noise"
    }
    readonly property bool showLegendButton: {
        if(root.seriesList.length>1)return true;
        var panels=root.panelsResolved;
        for(var i=0;i<panels.length;i++)if((panels[i].series||[]).length>1)return true;
        return false;
    }
    readonly property bool show3DButton: root.kind === "stft" || root.kind === "das-map"
    readonly property var contentItem: contentLoader.item
    // The waterfall only exists in 3D mode; computing its axes/frames while the
    // 2D heat map is visible wasted several ms per live STFT update.
    readonly property var waterfallFrequencyAxis: root.threeDActive
        ? F.frequencyAxisFor(root.payload, root.frameInfo.frames, root.payload.yAxis) : ({})
    readonly property var waterfallTimeAxis: {
        if (!root.threeDActive) return ({});
        var a=F.timeAxisFor(root.payload, root.frameInfo.frames, root.payload.xAxis);
        if(a && !root.payload.timeAxis && typeof App !== "undefined")a.label=App.t("studio.relative_time");
        return a;
    }

    // ----------------------------------------------------------------- lifecycle
    property string viewIdentity: ""
    Component.onCompleted: Qt.callLater(root.resetViewState)
    onChartChanged: {
        var identity = root.featureId + ":" + root.kind;
        if (identity !== root.viewIdentity) {
            root.viewIdentity = identity;
            Qt.callLater(root.resetViewState);
        }
    }
    function resetViewState() {
        // Deferred so the payload bindings have re-evaluated before the display
        // state is reset (log-axis default, 2D/3D, cursors).
        root.logScaleEnabled = root.chartLogDefault
        root.threeDActive = false
        root.dasRect = root.kind === "das-map"
        root.heatCursor = null
        root.lineCursorA = null
        root.lineCursorB = null
        root.waveCursorA = null
        root.waveCursorB = null
        root.cursorEnabled = false
    }
    readonly property var stftDisplay: {
        var d=F.stftDisplay(root.payload);
        if((root.payload.raster || {}).yUnit === "frame" && typeof App !== "undefined") {
            d.xAxis.label=App.t("studio.retained_frames");
            d.yAxis.label=App.t("studio.frequency");
        }
        return d;
    }
    onRouteTokenChanged: contentLoader.sourceComponent = root.routeComponent()

    function contentToken() {
        if (!root.chart || root.unavailable) return "empty"
        if (!root.kind.length) return "empty"
        var token = F.routeToken(root.kind)
        if (token === "panel" && root.panelsResolved.length === 0) return "line"
        if ((token === "line" || token === "panel") && root.scalarList.length > 0) return "readout-line"
        if (token === "readout-line" && root.kind === "room-clarity"
                && root.categoryList.length > 0 && root.seriesList.length === 0) return "bars-readout"
        return token
    }

    function routeComponent() {
        var t = root.routeToken
        if (t === "line") return lineComponent
        if (t === "bars-readout") return barsReadoutComponent
        if (t === "stft") return stftComponent
        if (t === "das") return dasComponent
        if (t === "panel") return panelComponent
        if (t === "readout-line") return readoutLineComponent
        if (t === "ab") return abComponent
        if (t === "stipa") return stipaComponent
        if (t === "waveform") return waveformComponent
        if (t === "level") return levelComponent
        if (t === "scalars") return scalarsComponent
        if (t === "capability") return capabilityComponent
        if (t === "events") return eventsComponent
        if (t === "noise") return noiseComponent
        return emptyComponent
    }

    // ------------------------------------------------------------- display helpers
    function xAxisUnit() {
        var ax = root.payload.xAxis
        return ax && ax.unit !== undefined ? String(ax.unit) : ""
    }
    function yAxisUnit() {
        var ax = root.payload.yAxis
        if (ax && ax.unit !== undefined) return String(ax.unit)
        return root.payload.units !== undefined ? String(root.payload.units) : ""
    }
    // Scientific colormap policy per chart family: STFT heat map = Inferno,
    // DAS spatial power = Viridis, 3D surface/waterfall = Magma, signed A/B = Diverging.
    function forcedPalette(scale, name) {
        var out = ({ min: 0, max: 1, label: "", unit: "" })
        if (scale) {
            for (var key in scale) out[key] = scale[key]
            if (F.isNum(scale.min)) out.min = scale.min
            if (F.isNum(scale.max)) out.max = scale.max
        }
        out.palette = name
        return out
    }
    function waterfallColorScale() {
        var cs = root.payload.colorScale
        if (cs && F.isNum(cs.min) && F.isNum(cs.max) && cs.max > cs.min) return root.forcedPalette(cs, "magma")
        var lo = Infinity
        var hi = -Infinity
        var rows = root.frameInfo.frames
        for (var r = 0; r < rows.length; r++) {
            var pts = rows[r].points
            for (var p = 0; p < pts.length; p++) {
                var v = pts[p][1]
                if (!F.isNum(v)) continue
                if (v < lo) lo = v
                if (v > hi) hi = v
            }
        }
        if (lo === Infinity) return { min: 0, max: 1, palette: "magma", label: "", unit: "" }
        if (lo === hi) { lo -= 1; hi += 1 }
        return { min: lo, max: hi, palette: "magma",
                 label: root.payload.yAxis && root.payload.yAxis.label !== undefined ? String(root.payload.yAxis.label) : "",
                 unit: root.yAxisUnit() }
    }
    function threeDReason() {
        if (root.frameInfo.supported) return root.emptyReasonText
        if (root.framesUnavailableText.length) return root.framesUnavailableText
        return root.emptyReasonText
    }
    function levelScaleData() {
        if (root.payload.scale) return root.payload.scale
        var ax = root.payload.yAxis
        if (ax && F.isNum(ax.min) && F.isNum(ax.max)) {
            return { min: ax.min, max: ax.max,
                     label: ax.label === undefined ? "" : String(ax.label),
                     unit: ax.unit === undefined ? "" : String(ax.unit) }
        }
        return null
    }
    function panelTitle(index) {
        var p = root.panelsResolved
        if (index < p.length) return p[index].title === undefined ? "" : String(p[index].title)
        return ""
    }
    function panelSubtitle(index) {
        var p = root.panelsResolved
        if (index < p.length) return p[index].subtitle === undefined ? "" : String(p[index].subtitle)
        return ""
    }

    // ------------------------------------------------------------- view actions
    function persistOption(key, value) {
        if (typeof App === "undefined" || !App || typeof App.setFeatureViewOption !== "function") return
        if (!root.featureId.length) return
        try { App.setFeatureViewOption(root.featureId, String(key), String(value)) } catch (e) { }
    }

    function seriesXValues() {
        var out = []
        for (var s = 0; s < root.seriesList.length; s++) {
            var pts = root.seriesList[s].points
            for (var i = 0; i < pts.length; i += Math.max(1, Math.floor(pts.length / 64))) {
                if (F.isNum(pts[i][0])) out.push(pts[i][0])
            }
            if (out.length) break
        }
        out.sort(function (a, b) { return a - b })
        return out
    }

    function applyCursorDefaults() {
        if(root.kind === "stft") {var xa=root.stftDisplay.xAxis||{},ya=root.stftDisplay.yAxis||{};if(F.isNum(xa.min)&&F.isNum(xa.max)&&F.isNum(ya.min)&&F.isNum(ya.max))root.heatCursor={x:(xa.min+xa.max)/2,y:(ya.min+ya.max)/2};return;}
        if(root.kind === "das-map") {var az=root.payload.azimuthRange||{min:0,max:360},el=root.payload.elevationRange||{min:-90,max:90};root.heatCursor={x:(az.min+az.max)/2,y:(el.min+el.max)/2};return;}
        var xs = seriesXValues()
        if (xs.length >= 2) {
            root.lineCursorA = xs[Math.floor((xs.length - 1) / 3)]
            root.lineCursorB = xs[Math.floor((xs.length - 1) * 2 / 3)]
        } else if (root.kind === "waveform") {
            root.waveCursorA = 0.33
            root.waveCursorB = 0.66
        } else if (root.show3DButton || root.kind === "stft") {
            var xa = root.payload.xAxis || {}
            var ya = root.payload.yAxis || {}
            if (F.isNum(xa.min) && F.isNum(xa.max) && F.isNum(ya.min) && F.isNum(ya.max)) {
                root.heatCursor = { x: (xa.min + xa.max) / 2, y: (ya.min + ya.max) / 2 }
            }
        }
    }

    function onLinePointClicked(x, y) {
        if (!root.cursorEnabled) return
        if (root.lineCursorA === null || (root.lineCursorA !== null && root.lineCursorB !== null)) {
            root.lineCursorA = x
            root.lineCursorB = null
        } else {
            root.lineCursorB = x
        }
        root.persistOption("cursor", root.lineCursorA + "," + (root.lineCursorB === null ? "" : root.lineCursorB))
    }
    function onLineCursorChanged(a, b) {
        root.lineCursorA = isFinite(a) ? a : null
        root.lineCursorB = isFinite(b) ? b : null
    }
    function onWaveCursorChanged(a, b) {
        root.waveCursorA = a >= 0 ? a : null
        root.waveCursorB = b >= 0 ? b : null
    }
    function onHeatPointClicked(x, y) {
        if(root.cursorEnabled)root.heatCursor = { x: x, y: y }
    }

    function resetViewRecursive(item) {
        if (!item) return
        if (item.resetScale !== undefined) item.resetScale()
        if (item.viewStart !== undefined && item.viewEnd !== undefined) {
            item.viewStart = 0
            item.viewEnd = 1
        }
        if (item.depth !== undefined && item.rise !== undefined) {
            item.depth = 0.24
            item.rise = 0.22
        }
        var kids = item.children || []
        for (var i = 0; i < kids.length; i++) root.resetViewRecursive(kids[i])
    }
    function fitView() {
        root.resetViewRecursive(contentLoader.item)
        root.fitCounter = root.fitCounter + 1
    }

    function notifySaved(path) {
        if (typeof App === "undefined" || !App || typeof App.notifyFeatureSaved !== "function") return
        try { App.notifyFeatureSaved(String(path)) } catch (e) { }
    }
    function saveImage() {
        var target = root
        if (!target || !target.grabToImage) { root.saveFailed("no-target"); return }
        var path = ""
        if (typeof App !== "undefined" && App && typeof App.saveFeatureChart === "function"
                && root.featureId.length) {
            try { path = String(App.saveFeatureChart(root.featureId) || "") } catch (e) { path = "" }
        }
        var nativeScale = Math.max(1, Screen.devicePixelRatio)
        var w = Math.max(1, Math.round(target.width * nativeScale))
        var h = Math.max(1, Math.round(target.height * nativeScale))
        target.grabToImage(function (result) {
            if (!result) { root.saveFailed("grab-failed"); return }
            var tempUrl = ""
            try { tempUrl = String(result.url) } catch (e2) { tempUrl = "" }
            var saved = false
            if (path.length) {
                try { saved = result.saveToFile(path) } catch (e3) { saved = false }
            }
            if (saved) {
                root.imageCaptured(path)
                root.notifySaved(path)
            } else {
                root.imageCaptured(tempUrl)
                root.saveFailed(path.length ? path : "no-path")
            }
        }, Qt.size(w, h))
    }

    // ---------------------------------------------------------------- layout
    ColumnLayout {
        anchors.fill: parent
        spacing: 6

        ChartToolbar {
            id: toolbar
            Layout.fillWidth: true
            title: root.titleText
            subtitle: ""
            iconSource: root.resolvedIconSource
            showFit: root.showFitButton
            showLog: root.showLogButton
            showCursor: root.showCursorButton
            showLegend: root.showLegendButton
            show3D: root.show3DButton
            showSave: true
            logActive: root.logScaleEnabled
            cursorActive: root.cursorEnabled
            legendActive: root.legendVisible
            threeDActive: root.threeDActive
            fitTooltip: root.fitTooltip
            logTooltip: root.logTooltip
            cursorTooltip: root.cursorTooltip
            legendTooltip: root.legendTooltip
            threeDTooltip: root.kind === "das-map" && typeof App !== "undefined" ? App.t("studio.map_projection") : root.threeDTooltip
            saveTooltip: root.saveTooltip
            onFitRequested: root.fitView()
            onLogToggled: function (active) { root.logScaleEnabled = active; root.persistOption("logX", active) }
            onCursorToggled: function (active) {
                root.cursorEnabled = active
                if (active) root.applyCursorDefaults()
                else { root.lineCursorA = null; root.lineCursorB = null; root.heatCursor = null
                       root.waveCursorA = null; root.waveCursorB = null }
                root.persistOption("cursor", active)
            }
            onLegendToggled: function (active) { root.legendVisible = active; root.persistOption("legend", active) }
            onThreeDToggled: function (active) {
                root.threeDActive = active
                if (root.kind === "das-map") root.dasRect = !active
                root.persistOption("2D3D", active)
            }
            onSaveRequested: root.saveImage()
        }

        SourceBanner {
            Layout.fillWidth: true
            visible: root.showSourceBanner && root.hasSource
            sourceKind: root.sourceKind
            sourceLabel: root.sourceLabel
            validity: root.validityText
            notes: root.sourceNotes
        }

        Loader {
            id: contentLoader
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: 1
            Layout.minimumHeight: 80
            sourceComponent: root.routeComponent()
        }
    }

    // ------------------------------------------------------------ chart routes
    Component {
        id: lineComponent
        LineChart {
            anchors.fill: parent
            objectName: "chartLine"
            dataRevision: root.dataRevision
            busy: root.chartBusy
            series: root.seriesList
            xAxis: root.effectiveXAxis
            yAxis: root.payload.yAxis
            markers: root.markerList
            referenceLines: root.refLines
            referenceBands: root.refBands
            showLegend: root.legendVisible
            inspectionEnabled: root.cursorEnabled
            cursorAX: root.cursorEnabled ? root.lineCursorA : null
            cursorBX: root.cursorEnabled ? root.lineCursorB : null
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
            onPointClicked: function (x, y) { root.onLinePointClicked(x, y) }
            onCursorChanged: function (a, b) { root.onLineCursorChanged(a, b) }
        }
    }

    Component {
        id: panelComponent
        PanelChart {
            anchors.fill: parent
            objectName: "chartPanel"
            inspectionEnabled: root.cursorEnabled
            dataRevision: root.dataRevision
            busy: root.chartBusy
            panels: root.panelsResolved
            showLegend:root.legendVisible
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
        }
    }

    Component {
        id: barsReadoutComponent
        ReadoutChart {
            anchors.fill: parent
            objectName: "chartBarsReadout"
            dataRevision: root.dataRevision
            busy: root.chartBusy
            render: "bars"
            readoutRows: root.scalarList
            wrapReadouts: ["room-decay","room-clarity","spectral-decay","scalar-trend"].indexOf(root.kind)>=0
            categories: root.categoryList
            xMode: root.barsXMode
            yAxis: root.payload.yAxis
            limitLine: root.payload.limitLine
            referenceValues: root.barReferenceValues
            bandRamp: root.resolvedBandRamp
            colorScale: root.bandScale
            valueFormat: root.payload.valueFormat !== undefined ? String(root.payload.valueFormat) : ""
            xLabel: root.payload.xAxis && root.payload.xAxis.label !== undefined ? String(root.payload.xAxis.label) : ""
            xUnit: root.xAxisUnit()
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
        }
    }

    Component {
        id: readoutLineComponent
        ReadoutChart {
            anchors.fill: parent
            objectName: "chartReadoutLine"
            dataRevision: root.dataRevision
            busy: root.chartBusy
            render: "line"
            readoutRows: root.scalarList
            wrapReadouts: ["room-decay","room-clarity","spectral-decay","scalar-trend"].indexOf(root.kind)>=0
            showReadout: true
            panels: root.panelsResolved
            series: root.seriesList
            xAxis: root.effectiveXAxis
            yAxis: root.payload.yAxis
            markers: root.markerList
            referenceLines: root.refLines
            referenceBands: root.refBands
            showLegend: root.legendVisible
            inspectionEnabled: root.cursorEnabled
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
        }
    }

    Component {
        id: abComponent
        AbSpectrumChart {
            anchors.fill: parent
            objectName: "chartAbSpectrum"
            dataRevision: root.dataRevision
            busy: root.chartBusy
            series: root.seriesList
            referenceLines: root.refLines
            referenceBands: root.refBands
            xAxis: root.effectiveXAxis
            yAxis: root.payload.yAxis
            deltaYAxis: root.payload.deltaYAxis
            topTitle: root.panelTitle(0)
            topSubtitle: root.panelSubtitle(0)
            deltaTitle: root.panelTitle(1)
            deltaSubtitle: root.panelSubtitle(1)
            showLegend: root.legendVisible
            inspectionEnabled: root.cursorEnabled
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
        }
    }

    Component {
        id: stftComponent
        Item {
            anchors.fill: parent
            objectName: "chartStftHost"
            HeatmapChart {
                anchors.fill: parent
                objectName: "chartHeatmap"
                visible: !root.threeDActive
                dataRevision: root.dataRevision
                busy: root.chartBusy
                imageUrl: root.imageUrl
                raster: root.stftDisplay.raster
                xAxis: root.stftDisplay.xAxis
                yAxis: root.stftDisplay.yAxis
                colorScale: root.forcedPalette(root.stftDisplay.colorScale, "inferno")
                cursor: root.cursorEnabled ? root.heatCursor : null
                emptyText: root.emptyText
                emptyReason: root.emptyReasonText
                onPointClicked: function (x, y) { root.onHeatPointClicked(x, y) }
            }
            WaterfallChart {
                anchors.fill: parent
                objectName: "chartWaterfall"
                visible: root.threeDActive
                dataRevision: root.dataRevision
                busy: root.chartBusy
                frames: root.threeDActive ? root.frameInfo.frames : []
                frequencyAxis: root.waterfallFrequencyAxis
                timeAxis: root.waterfallTimeAxis
                colorScale: root.threeDActive ? root.waterfallColorScale() : ({})
                emptyText: root.emptyText
                emptyReason: root.threeDReason()
                interactive: true
            }
        }
    }

    Component {
        id: dasComponent
        Item {
          anchors.fill: parent
          ReadoutStrip {id:powerReadouts;anchors.top:parent.top;anchors.left:parent.left;anchors.right:parent.right;rows:root.scalarList;wrapRows:true;visible:root.scalarList.length>0}
          PolarChart {
            anchors.top: powerReadouts.visible ? powerReadouts.bottom : parent.top
            anchors.bottom:parent.bottom;anchors.left:parent.left;anchors.right:parent.right
            objectName: "chartPolar"
            dataRevision: root.dataRevision
            busy: root.chartBusy
            imageUrl: root.imageUrl
            raster: root.payload.raster
            azimuthRange: root.payload.azimuthRange
            elevationRange: root.payload.elevationRange
            colorScale: root.forcedPalette(root.payload.colorScale, "viridis")
            projection: root.dasRect ? "rect" : "polar"
            cursor:root.cursorEnabled?root.heatCursor:null
            onPointClicked:function(x,y){root.onHeatPointClicked(x,y)}
            markers: root.markerList
            caption: root.payload.caption !== undefined ? String(root.payload.caption) : ""
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
          }
        }
    }

    Component {
        id: stipaComponent
        StipaChart {
            anchors.fill: parent
            objectName: "chartStipa"
            dataRevision: root.dataRevision
            busy: root.chartBusy
            finished: root.resultPresented
            stage: root.stipaStage
            quickMode: root.stipaQuickMode
            scalarRows: root.scalarList
            indexLabel: root.stipaInfo.label
            indexValue: root.stipaInfo.value
            indexUnit: root.stipaInfo.unit
            indexValid: root.stipaInfo.valid
            caption: root.payload.caption !== undefined ? String(root.payload.caption) : ""
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
        }
    }

    Component {
        id: waveformComponent
        WaveformChart {
            anchors.fill: parent
            objectName: "chartWaveform"
            dataRevision: root.dataRevision
            busy: root.chartBusy
            channels: root.waveData.channels
            sampleRate: root.waveData.sampleRate
            startSampleIndex: root.waveData.startSampleIndex
            gaps: root.waveData.gaps
            xMode: root.waveData.sampleRate > 0 ? "time" : "samples"
            yRange: root.payload.yRange !== undefined ? root.payload.yRange : null
            stacked: root.payload.stacked === undefined ? true : root.payload.stacked !== false
            cursorA: root.cursorEnabled ? root.waveCursorA : null
            cursorB: root.cursorEnabled ? root.waveCursorB : null
            yUnit: root.yAxisUnit()
            xUnit: root.xAxisUnit()
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
            onCursorChanged: function (a, b) { root.onWaveCursorChanged(a, b) }
        }
    }

    Component {
        id: levelComponent
        LevelMeter {
            anchors.fill: parent
            objectName: "chartLevelMeter"
            dataRevision: root.dataRevision
            busy: root.chartBusy
            meters: root.levelMeterList
            scale: root.levelScaleData()
            orientation: root.payload.orientation === "horizontal" ? "horizontal" : "vertical"
            clipText: root.payload.clipText !== undefined ? String(root.payload.clipText) : ""
            valueFormat: root.payload.valueFormat !== undefined ? String(root.payload.valueFormat) : "%.1f"
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
        }
    }

    Component {
        id: scalarsComponent
        ScalarReadout {
            anchors.fill: parent
            objectName: "chartScalars"
            rows: root.scalarList
            columns: root.payload.columns !== undefined ? Number(root.payload.columns) : 0
            valueFormat: root.payload.valueFormat !== undefined ? String(root.payload.valueFormat) : ""
            busy: root.chartBusy
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
        }
    }

    Component {
        id: capabilityComponent
        CapabilityPanel {
            anchors.fill: parent
            objectName: "chartCapability"
            text: root.payload.text !== undefined ? String(root.payload.text) : ""
            rows: root.scalarList
            caption: root.payload.caption !== undefined ? String(root.payload.caption) : ""
            busy: root.chartBusy
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
        }
    }

    Component {
        id: eventsComponent
        EventTimeline {
            anchors.fill: parent
            objectName: "chartEvents"
            dataRevision: root.dataRevision
            busy: root.chartBusy
            events: F.eventsFor(root.payload)
            timeAxis: root.payload.timeAxis !== undefined ? root.payload.timeAxis : null
            durationSeconds: F.isNum(root.payload.durationSeconds) ? root.payload.durationSeconds : 0
            downloadLabels: root.payload.downloadLabels !== undefined ? root.payload.downloadLabels : ({})
            emptyText: root.payload.emptyReason || root.emptyText
            emptyReason: root.emptyReasonText
            onEventActivated: function (index) { root.eventActivated(index) }
        }
    }

    Component {
        id: noiseComponent
        NoiseRatingChart {
            anchors.fill: parent
            objectName: "chartNoiseRating"
            dataRevision: root.dataRevision
            busy: root.chartBusy
            series: root.seriesList
            referenceFamilies: root.payload.referenceFamilies !== undefined ? root.payload.referenceFamilies : []
            markers: root.markerList
            referenceLines: root.refLines
            referenceBands: root.refBands
            readoutRows: root.scalarList
            xAxis: root.effectiveXAxis
            yAxis: root.payload.yAxis
            note: root.payload.note !== undefined ? String(root.payload.note)
                  : (root.payload.text !== undefined ? String(root.payload.text) : "")
            family: root.payload.family !== undefined ? String(root.payload.family) : ""
            showLegend: root.legendVisible
            inspectionEnabled: root.cursorEnabled
            emptyText: root.emptyText
            emptyReason: root.emptyReasonText
        }
    }

    Component {
        id: emptyComponent
        ChartEmptyState {
            anchors.fill: parent
            objectName: "chartEmptyState"
            text: root.emptyText
            reason: root.emptyReasonText
            busy: root.chartBusy
            busyText: root.payload.busyText !== undefined ? String(root.payload.busyText) : ""
        }
    }
}