"""Design tokens for the SixMic3D acoustic analyzer UI (single source of truth).

Spec source: docs/handoffs/PC_FRONTEND_AGENT_BRIEF_20261024.md section 4.
Light shell + dark professional plot area is the default; complete dark theme
and system-follow mode are provided. Channel colors are fixed for the whole app.
No decorative gradients, neon or decorative gauges. Scalar plot gradients encode level.
"""
from __future__ import annotations

CHANNEL_COLORS = ["#57C8FF", "#FFC86B", "#CB9CFF", "#44DBC0", "#A5D970", "#FF8295"]
CHANNEL_NAMES = ["CH1", "CH2", "CH3", "CH4", "CH5", "CH6"]

LIGHT = {
    "appBg": "#EEF2F8",
    "chromeBg": "#ECEFF3",
    "panelBg": "#FAFCFF",
    "panelAlt": "#F7F9FB",
    "border": "#E2E7EE",
    "borderStrong": "#CED6DF",
    "textPrimary": "#111A24",
    "textSecondary": "#47586A",
    "textDisabled": "#9AA6B4",
    "accent": "#007AFF",
    "accentPressed": "#0062CC",
    "accentSoft": "#E6F1FF",
    "selection": "#D6E9FF",
    "plotBg": "#000000",
    "plotGrid": "#303942",
    "plotGridMinor": "#303639",
    "plotText": "#E9F1F9",
    "plotTextDim": "#9BAAB8",
    "plotCursorA": "#FFD166",
    "plotCursorB": "#14B8A6",
    "ok": "#1F9D55",
    "warn": "#C47F17",
    "error": "#C9372C",
    "info": "#0B6BCB",
    "shadow": "#1A2430",
    "hover": "#E3E8EE",
    "pressed": "#D8DEE6",
    "focusRing": "#007AFF",
    "scrollbar": "#B9C2CD",
}

# Midnight Scientific — Aurora Edition (frozen design system, 2026-10-26).
DARK = {
    "appBg": "#171C25",
    "chromeBg": "#202734",
    "panelBg": "#202734",
    "panelAlt": "#273140",
    "border": "#344154",
    "borderStrong": "#4B5C73",
    "textPrimary": "#F0F4FA",
    "textSecondary": "#B6C3D6",
    "textDisabled": "#63717B",
    "accent": "#63B9FF",
    "accentPressed": "#77B6C2",
    "accentSoft": "#1B3036",
    "selection": "#1C3047",
    "plotBg": "#131A24",
    "plotGrid": "#2C3A4C",
    "plotGridMinor": "#202C3B",
    "plotZero": "#586C83",
    "plotText": "#E2EBF6",
    "plotTextDim": "#ABBBD0",
    "plotCursorA": "#F2B85D",
    "plotCursorB": "#42D4AA",
    "tooltipBg": "#19283A",
    "tooltipBorder": "#36526B",
    "ok": "#42D4AA",
    "warn": "#F2B85D",
    "error": "#F36F83",
    "info": "#65A2F9",
    "shadow": "#131A24",
    "hover": "#1A2024",
    "pressed": "#222B30",
    "focusRing": "#63B9FF",
    "scrollbar": "#434C53",
}

RADIUS = {"control": 6, "panel": 14, "panelSmall": 8, "chip": 6}
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
FONT = {
    "family": "Noto Sans CJK SC",
    "familyCjk": "Microsoft YaHei UI",
    "mono": "Cascadia Mono",
    "sizeBody": 15,
    "sizeSmall": 13,
    "sizeTable": 12,
    "sizeLabel": 14,
    "sizeTitle": 17,
    "sizeReadout": 28,
    "sizeReadoutLarge": 32,
}
STATUS_COLORS = {"ok": "ok", "warn": "warn", "error": "error", "info": "info"}


def palette(mode: str, system_dark: bool) -> dict[str, str]:
    resolved = mode if mode in ("light", "dark") else ("dark" if system_dark else "light")
    base = dict(LIGHT if resolved == "light" else DARK)
    base["resolved"] = resolved
    return base
