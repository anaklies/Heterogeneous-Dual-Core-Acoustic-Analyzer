// Capability-status row: backend feature status rendered explicitly (available/experimental/not_ready/unsupported).
import QtQuick
import QtQuick.Layouts
import "../../components"

ColumnLayout {
    id: root
    property var feature: null
    property bool showFeatureId: true
    Layout.fillWidth: true
    spacing: 3

    readonly property string featureStatus: root.feature ? String(root.feature.status || "not_ready") : "not_ready"

    function statusLabel() {
        if (root.featureStatus === "available") return App.t("overview.available")
        if (root.featureStatus === "experimental") return App.t("overview.experimental")
        if (root.featureStatus === "unsupported") return App.t("overview.unsupported")
        return App.t("overview.not_ready")
    }
    function statusTone() {
        if (root.featureStatus === "available") return Theme.ok
        if (root.featureStatus === "experimental") return Theme.warn
        if (root.featureStatus === "unsupported") return Theme.error
        return Theme.textSecondary
    }
    function statusIconName() {
        if (root.featureStatus === "available") return "circle-check"
        if (root.featureStatus === "experimental") return "triangle-alert"
        if (root.featureStatus === "unsupported") return "ban"
        return "circle-slash"
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        Icon {
            name: root.statusIconName()
            size: 14
            color: root.statusTone()
        }
        Text {
            Layout.fillWidth: true
            text: root.feature ? String(root.feature.displayName || root.feature.featureId || "") : ""
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
            elide: Text.ElideRight
        }
        Rectangle {
            implicitHeight: 18
            implicitWidth: badgeText.implicitWidth + 12
            radius: 9
            color: Qt.rgba(root.statusTone().r, root.statusTone().g, root.statusTone().b, 0.12)
            border.width: 1
            border.color: Qt.rgba(root.statusTone().r, root.statusTone().g, root.statusTone().b, 0.45)
            Text {
                id: badgeText
                anchors.centerIn: parent
                text: root.statusLabel()
                color: root.statusTone()
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(18 * Theme.fontScale)
            }
        }
    }
    Text {
        Layout.fillWidth: true
        visible: false
        text: root.feature
              ? String(root.feature.featureId || "")
                + (root.feature.units ? " · " + String(root.feature.units) : "")
                + (root.feature.tier ? " · " + String(root.feature.tier) : "")
              : ""
        color: Theme.textDisabled
        font.family: Theme.fontMono
        font.pixelSize: Math.round(18 * Theme.fontScale)
        elide: Text.ElideRight
    }
    Text {
        Layout.fillWidth: true
        visible: text.length > 0
        text: root.feature ? String(root.feature.reason || root.feature.qualityNote || "") : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(18 * Theme.fontScale)
        wrapMode: Text.Wrap
    }
}
