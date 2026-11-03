"""Generate the deterministic synthetic demo rasters used ONLY by ChartGallery.qml.

These are clearly labelled synthetic display data for component QA; they are not
measurements and are not used by any product page. Run with the app venv python.

    .venv/Scripts/python.exe ui/qml/components/charts/_selftest/make_demo_rasters.py
"""
from __future__ import annotations

import math
import os
import sys

from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "demo"))

# Same 10-anchor viridis as ChartUtil.js (keeps the gallery colour bar honest).
VIRIDIS = [
    (68, 1, 84), (72, 40, 120), (62, 74, 137), (49, 104, 142), (38, 130, 142),
    (31, 158, 137), (53, 183, 121), (109, 205, 89), (180, 222, 44), (253, 231, 37),
]
CIVIDIS = [
    (0, 32, 76), (0, 42, 102), (45, 64, 110), (71, 85, 104), (92, 102, 97),
    (111, 120, 91), (135, 140, 84), (168, 160, 76), (206, 182, 67), (253, 232, 56),
]


def cmap(stops, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    x = t * (len(stops) - 1)
    i = min(int(x), len(stops) - 2)
    f = x - i
    a, b = stops[i], stops[i + 1]
    return QColor(
        round(a[0] + (b[0] - a[0]) * f),
        round(a[1] + (b[1] - a[1]) * f),
        round(a[2] + (b[2] - a[2]) * f),
    )


def det(t: int) -> float:
    """Deterministic pseudo-noise in [0,1) (no random module, reproducible)."""
    v = math.sin(t * 12.9898 + 78.233) * 43758.5453
    return v - math.floor(v)


def make_heatmap(width: int = 320, height: int = 180) -> QImage:
    img = QImage(width, height, QImage.Format_RGBA8888)
    img.fill(QColor("#440154"))
    for y in range(height):
        # log frequency axis 20 Hz .. 20 kHz (matches the gallery axes)
        frac = 1.0 - (y + 0.5) / height
        f = 20.0 * (20000.0 / 20.0) ** frac
        for x in range(width):
            t = (x + 0.5) / width * 10.0  # 0..10 s
            db = -86.0
            # a few stationary tones with slow amplitude drift
            for f0, amp, drift in ((1000.0, 34.0, 0.5), (2000.0, 22.0, 0.8), (500.0, 16.0, 0.3)):
                db += amp * math.exp(-((math.log(f / f0)) ** 2) / 0.02) * (0.75 + 0.25 * math.sin(2 * math.pi * drift * t))
            # two time-localised bursts
            for tc, fc, amp in ((3.2, 4000.0, 20.0), (6.8, 8000.0, 16.0)):
                db += amp * math.exp(-((t - tc) ** 2) / 0.25) * math.exp(-((math.log(f / fc)) ** 2) / 0.05)
            db += 4.0 * (det(x * 131 + y * 17) - 0.5)
            tnorm = (db + 86.0) / 76.0  # colorScale min -86 .. max -10
            img.setPixelColor(x, y, cmap(VIRIDIS, tnorm))
    return img


def make_polar(size: int = 256) -> QImage:
    img = QImage(size, size, QImage.Format_RGBA8888)
    img.fill(QColor(0, 0, 0, 0))
    c = size / 2.0
    for y in range(size):
        for x in range(size):
            dx = x + 0.5 - c
            dy = y + 0.5 - c
            r = math.hypot(dx, dy) / c  # 0 center .. 1 circle edge
            if r > 1.0:
                continue
            az = math.degrees(math.atan2(dx, -dy)) % 360.0  # 0 at top, clockwise
            el = r * 90.0  # center = 0 deg elevation, edge = 90 deg
            db = -38.0
            for az0, el0, amp, width in ((45.0, 55.0, 26.0, 22.0), (200.0, 40.0, 19.0, 26.0), (300.0, 70.0, 11.0, 18.0)):
                daz = min(abs(az - az0), 360.0 - abs(az - az0))
                db += amp * math.exp(-(daz ** 2) / (2 * width ** 2)) * math.exp(-((el - el0) ** 2) / (2 * 24.0 ** 2))
            db += 3.0 * (det(x * 37 + y * 91) - 0.5)
            t = (db + 40.0) / 40.0  # colorScale min -40 .. max 0
            color = cmap(CIVIDIS, t)
            color.setAlpha(255)
            img.setPixelColor(x, y, color)
    return img


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    heatmap = make_heatmap()
    polar = make_polar()
    if not heatmap.save(os.path.join(OUT, "heatmap_demo.png"), "PNG"):
        print("ERROR: could not save heatmap", file=sys.stderr)
        return 1
    if not polar.save(os.path.join(OUT, "polar_demo.png"), "PNG"):
        print("ERROR: could not save polar", file=sys.stderr)
        return 1
    print("wrote", os.path.join(OUT, "heatmap_demo.png"), heatmap.width(), heatmap.height())
    print("wrote", os.path.join(OUT, "polar_demo.png"), polar.width(), polar.height())
    return 0


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)  # QImage works without QGuiApplication but keep Qt happy
    raise SystemExit(main())
