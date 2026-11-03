"""QML-exposed theme palette with live switching (light / dark / system)."""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal
from PySide6.QtGui import QGuiApplication

from themes.tokens import FONT, RADIUS, SPACING, palette


class ThemeSource(QObject):
    changed = Signal()

    def __init__(self, mode: str = "light", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mode = mode if mode in ("light", "dark", "system") else "light"
        self._system_dark = self._detect_system_dark()
        self._colors = palette(self._mode, self._system_dark)
        self._font_scale = 1.0

    @staticmethod
    def _detect_system_dark() -> bool:
        try:
            hints = QGuiApplication.styleHints()
            scheme = hints.colorScheme()
            return str(scheme).endswith("Dark") or "Dark" in str(scheme)
        except Exception:
            return False

    @Property(float, notify=changed)
    def fontScale(self) -> float:  # noqa: N802
        return self._font_scale

    def set_font_scale(self, value: float) -> None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        value = max(0.95, min(1.15, value))
        if abs(value - self._font_scale) > 1e-6:
            self._font_scale = value
            self.changed.emit()

    def _notify(self) -> None:
        self._colors = palette(self._mode, self._system_dark)
        self.changed.emit()

    @Property(str, notify=changed)
    def mode(self) -> str:
        return self._mode

    @Property(str, notify=changed)
    def resolved(self) -> str:
        return self._colors.get("resolved", "light")

    def set_mode(self, mode: str) -> None:
        if mode not in ("light", "dark", "system"):
            return
        if mode != self._mode:
            self._mode = mode
            self._notify()

    modeProperty = Property(str, mode, set_mode, notify=changed)

    @Property(int, notify=changed)
    def radiusControl(self) -> int:  # noqa: N802
        return RADIUS["control"]

    @Property(int, notify=changed)
    def radiusPanel(self) -> int:  # noqa: N802
        return RADIUS["panel"]

    @Property(int, notify=changed)
    def spacingSm(self) -> int:  # noqa: N802
        return SPACING["sm"]

    @Property(int, notify=changed)
    def spacingMd(self) -> int:  # noqa: N802
        return SPACING["md"]

    @Property(int, notify=changed)
    def spacingLg(self) -> int:  # noqa: N802
        return SPACING["lg"]

    @Property(str, notify=changed)
    def fontFamily(self) -> str:  # noqa: N802
        return FONT["family"]

    @Property(str, notify=changed)
    def fontFamilyCjk(self) -> str:  # noqa: N802
        return FONT["familyCjk"]

    @Property(str, notify=changed)
    def fontMono(self) -> str:  # noqa: N802
        return FONT["mono"]

    @Property(int, notify=changed)
    def sizeBody(self) -> int:  # noqa: N802
        return FONT["sizeBody"]

    @Property(int, notify=changed)
    def sizeSmall(self) -> int:  # noqa: N802
        return FONT["sizeSmall"]

    @Property(int, notify=changed)
    def sizeReadout(self) -> int:  # noqa: N802
        return FONT["sizeReadout"]

    def _color_prop(name: str, signal):
        def getter(self) -> str:
            return self._colors[name]
        return Property(str, getter, notify=signal)

    appBg = _color_prop("appBg", changed)
    chromeBg = _color_prop("chromeBg", changed)
    panelBg = _color_prop("panelBg", changed)
    panelAlt = _color_prop("panelAlt", changed)
    border = _color_prop("border", changed)
    borderStrong = _color_prop("borderStrong", changed)
    textPrimary = _color_prop("textPrimary", changed)
    textSecondary = _color_prop("textSecondary", changed)
    textDisabled = _color_prop("textDisabled", changed)
    accent = _color_prop("accent", changed)
    accentPressed = _color_prop("accentPressed", changed)
    accentSoft = _color_prop("accentSoft", changed)
    selection = _color_prop("selection", changed)
    plotBg = _color_prop("plotBg", changed)
    plotGrid = _color_prop("plotGrid", changed)
    plotGridMinor = _color_prop("plotGridMinor", changed)
    plotText = _color_prop("plotText", changed)
    plotTextDim = _color_prop("plotTextDim", changed)
    plotCursorA = _color_prop("plotCursorA", changed)
    plotCursorB = _color_prop("plotCursorB", changed)
    ok = _color_prop("ok", changed)
    warn = _color_prop("warn", changed)
    error = _color_prop("error", changed)
    info = _color_prop("info", changed)
    shadow = _color_prop("shadow", changed)
    hover = _color_prop("hover", changed)
    pressed = _color_prop("pressed", changed)
    focusRing = _color_prop("focusRing", changed)
    scrollbar = _color_prop("scrollbar", changed)

    @Property("QVariantList", notify=changed)
    def channelColors(self):  # noqa: N802
        from themes.tokens import CHANNEL_COLORS
        return list(CHANNEL_COLORS)

    @Property("QVariantList", notify=changed)
    def channelNames(self):  # noqa: N802
        from themes.tokens import CHANNEL_NAMES
        return list(CHANNEL_NAMES)
