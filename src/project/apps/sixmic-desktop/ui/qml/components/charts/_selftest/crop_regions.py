"""Crop regions out of the gallery screenshot for close-up QA (dev helper)."""
import os
import sys

from PySide6.QtGui import QGuiApplication, QImage

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SRC = os.path.join(OUT, "chart_gallery_light.png")

app = QGuiApplication(sys.argv)
img = QImage(SRC)
print("source:", img.width(), "x", img.height())
CROPS = {
    "crop_waveform.png": (8, 74, 1584, 264),
    "crop_linechart.png": (8, 344, 980, 236),
    "crop_barchart.png": (990, 344, 602, 236),
    "crop_heatmap.png": (8, 590, 980, 276),
    "crop_polar.png": (990, 590, 602, 276),
    "crop_meters.png": (8, 878, 1584, 154),
    "crop_timeline.png": (8, 1042, 1584, 154),
}
for name, (x, y, w, h) in CROPS.items():
    crop = img.copy(x, y, w, h)
    crop = crop.scaled(w * 2, h * 2)
    path = os.path.join(OUT, name)
    print(name, crop.save(path), crop.width(), crop.height())
