// StipaChart - experimental STIPA run: a fixed-height stage progress bar plus the
// result readouts supplied by the device. The certified index is always 0 for this
// experimental feature (payload value is shown as-is; no certification claim is
// fabricated here). All text/unit/label strings come from the payload/page.
//
// The progress display is a standard QtQuick.Controls ProgressBar with a fixed
// height: no bitmap painting and no hand-painted text. The progress digits live in
// one elided Text; the stage label has its own elided Text. The progress area
// clips its content and all layout minimum widths are 0 so a narrow window can
// never make the digits/label overlap other rows.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "ChartUtil.js" as U

Item {
    id: root
    clip: true
    // {completed:int, total:int, current:int, label:string}; legacy payloads only
    // carried {index:int, total:int, label:string} and are still accepted.
    property var stage: null
    property var scalarRows: []         // result readouts (index/validity/certified ...)
    property string indexLabel: ""
    property real indexValue: NaN
    property string indexUnit: ""
    property bool indexValid: false
    property string caption: ""
    property string emptyText: ""
    property string emptyReason: ""
    property bool busy: false
    property string busyText: ""
    // Set by the page once a result is presented (valid, or completed but
    // invalid). The index/readouts/reason/caption stay; the run progress is
    // hidden because it belongs to a run, not to a finished measurement.
    property bool finished: false
    property int dataRevision: 0
    // Selected measurement mode: quick = 15 stages, complete = 101 stages. Used
    // only when no stage payload exists yet (idle / reference capture), so the
    // progress always reflects the mode the operator selected instead of a
    // hardcoded 101.
    property bool quickMode: false

    readonly property int stageTotal: {
        var t = stage && U.isNum(stage.total) && stage.total > 0
                ? Math.round(stage.total)
                : (root.quickMode ? 15 : 101)
        return U.clamp(t, 1, 100000)
    }
    // Completed stage count: payload `completed`; legacy payloads only have `index`.
    readonly property int completedStages: {
        if (!stage) return 0
        var c = U.isNum(stage.completed) ? stage.completed
              : (U.isNum(stage.index) ? stage.index : 0)
        return U.clamp(Math.round(c), 0, stageTotal)
    }
    // 0-based index of the stage currently executing: payload `current`; when a
    // payload does not carry it, fall back to the completed count.
    readonly property int stageIndex: {
        if (!stage) return 0
        var i = U.isNum(stage.current) ? stage.current : completedStages
        return U.clamp(Math.round(i), 0, stageTotal)
    }
    readonly property real progressValue: stageTotal > 0 ? completedStages / stageTotal : 0
    readonly property string stageLabel: stage && stage.label !== undefined ? String(stage.label) : ""
    // The only place the progress digits are formatted.
    readonly property string progressText: String(root.completedStages) + " / " + String(root.stageTotal)
    // Progress is displayed only while the run is in flight. It hides as soon as
    // the page presents a result (valid or completed-but-invalid) or the stage
    // payload itself reports every stage done while nothing is busy.
    readonly property bool progressComplete: root.stageTotal > 0 && root.completedStages >= root.stageTotal
    readonly property bool progressVisible: !root.finished && !(root.progressComplete && !root.busy)
    readonly property var st: ({
        bg: Theme.plotBg,
        text: Theme.plotText,
        dim: Theme.plotTextDim,
        grid: Theme.plotGrid,
        minor: Theme.plotGridMinor,
        accent: Theme.accent,
        ok: Theme.ok,
        warn: Theme.warn,
        error: Theme.error,
        font: Theme.fontFamily,
        mono: Theme.fontMono
    })

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: 16
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 0
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: root.indexLabel
                    visible: text.length > 0
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }
                Row {
                    spacing: 6
                    Text {
                        id: stipaIndex
                        objectName: "stipaIndexValue"
                        text: root.indexValid && U.isNum(root.indexValue)
                              ? String(Math.round(root.indexValue * 1000) / 1000) : "\u2014"
                        color: root.indexValid ? Theme.textPrimary : Theme.textDisabled
                        font.family: Theme.fontMono
                        font.pixelSize: Math.round(30 * Theme.fontScale)
                        font.weight: Font.DemiBold
                    }
                    Text {
                        anchors.baseline: stipaIndex.baseline
                        text: root.indexUnit
                        visible: text.length > 0
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
                    }
                }
            }
            ColumnLayout {
                id: progressArea
                objectName: "stipaProgressArea"
                visible: root.progressVisible
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 2
                clip: true
                RowLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 8
                    Text {
                        objectName: "stipaStageLabel"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: root.stageLabel
                        visible: text.length > 0
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
                        elide: Text.ElideRight
                        maximumLineCount: 1
                    }
                    Text {
                        objectName: "stipaProgressValue"
                        Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                        Layout.minimumWidth: 0
                        text: root.progressText
                        color: Theme.textSecondary
                        font.family: Theme.fontMono
                        font.pixelSize: Math.max(11, Math.round(12 * Theme.fontScale))
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        horizontalAlignment: Text.AlignRight
                    }
                }
                ProgressBar {
                    id: progressBar
                    objectName: "stipaProgressBar"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredHeight: 8
                    Layout.minimumHeight: 8
                    Layout.maximumHeight: 8
                    from: 0
                    to: root.stageTotal
                    value: root.completedStages
                    padding: 0
                    background: Rectangle {
                        implicitHeight: 8
                        radius: 4
                        color: U.rgba(root.st.minor, 0.9)
                    }
                    contentItem: Item {
                        Rectangle {
                            width: progressBar.visualPosition * parent.width
                            height: parent.height
                            radius: 4
                            color: root.st.accent
                        }
                    }
                }
            }
        }

        ScalarReadout {
            objectName: "stipaReadout"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 40
            rows: root.scalarRows
            columns: 3
            busy: root.busy
            emptyText: root.emptyText
            emptyReason: root.emptyReason
        }

        Text {
            objectName: "stipaCaption"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: root.caption
            visible: text.length > 0
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(13, Math.round(15 * Theme.fontScale))
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
    }
}