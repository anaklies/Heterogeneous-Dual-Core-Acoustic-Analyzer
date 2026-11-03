"""QML image provider and display-raster builder for feature charts.

Display-only: converts already-computed reference matrices / frame grids into RGB
images for the Qt Quick chart layer. No acoustic computation happens here - no
FFT/Welch/coherence/DAS/room/STIPA algorithm, only palette lookup, display
resampling and bounded caching. Sequential palettes are viridis/cividis; the
diverging palette is only for difference maps centred at zero. Missing / invalid
cells stay pure black (no interpolation, no fake zero).

Existing API used by the facade is preserved:
    heatmap_image(matrix, palette=..., min_value=..., max_value=...)
    PlotImageProvider.set_image(key, image) -> revision
    PlotImageProvider.revision(key)
    requestImage("image://plots/<key>/<revision>", ...)
New additive API for feature rasters:
    FeatureRasterCache            bounded LRU cache with revisions
    stft_image(frames, ...)       frame grid -> raster (missing frames stay empty)
    stft_heatmap_image(matrix,..) retained-frame raster -> HeatmapChart screen raster
    das_image(points, ...)        azimuth/elevation map -> rect/polar raster
    peak_envelope(values, budget) waveform display extraction preserving peaks
    image_url(cache, key)         "image://plots/<key>/<revision>"
"""
from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlImageProviderBase
from PySide6.QtQuick import QQuickImageProvider

# Control points sampled from matplotlib's viridis / cividis (public data,
# CC0 by the matplotlib authors) - small, license-safe approximations.
_VIRIDIS = [
    (0.267, 0.005, 0.329), (0.283, 0.141, 0.458), (0.254, 0.265, 0.530),
    (0.207, 0.372, 0.553), (0.164, 0.471, 0.558), (0.128, 0.567, 0.551),
    (0.135, 0.659, 0.518), (0.267, 0.749, 0.441), (0.478, 0.821, 0.318),
    (0.741, 0.873, 0.150), (0.993, 0.906, 0.144),
]
_CIVIDIS = [
    (0.000, 0.135, 0.305), (0.055, 0.199, 0.383), (0.145, 0.268, 0.443),
    (0.250, 0.337, 0.482), (0.360, 0.408, 0.502), (0.478, 0.478, 0.512),
    (0.596, 0.548, 0.518), (0.714, 0.622, 0.520), (0.827, 0.706, 0.512),
    (0.936, 0.808, 0.447), (0.996, 0.953, 0.400),
]
_DIVERGING = [
    (0.230, 0.299, 0.754), (0.478, 0.647, 0.949), (0.780, 0.858, 0.953),
    (0.961, 0.961, 0.961), (0.984, 0.827, 0.729), (0.933, 0.537, 0.401),
    (0.706, 0.016, 0.150),
]

# The HeatmapChart Canvas colour bar builds a 256-level LUT from the anchors in
# ui/qml/components/charts/ChartUtil.js.  A display image painted by Python must
# use the same LUT or the surface and the colour bar disagree, so these anchors
# are an exact mirror of ChartUtil.js PALETTES (matplotlib viridis/inferno
# anchor tables, CC0 by the matplotlib authors).
_QML_VIRIDIS = [
    (68, 1, 84), (72, 26, 108), (70, 50, 126), (65, 68, 135), (59, 82, 139),
    (53, 95, 141), (47, 108, 142), (42, 120, 142), (36, 132, 141), (31, 145, 139),
    (34, 158, 134), (47, 170, 124), (65, 182, 113), (86, 193, 101), (111, 205, 90),
    (140, 215, 74), (172, 222, 60), (201, 226, 49), (222, 226, 41), (240, 229, 38),
    (253, 231, 37),
]
_QML_INFERNO = [
    (0, 0, 4), (12, 8, 38), (27, 12, 65), (49, 13, 91), (73, 13, 106),
    (96, 20, 116), (120, 28, 109), (142, 38, 99), (162, 47, 88), (181, 58, 76),
    (198, 74, 62), (214, 94, 48), (228, 116, 34), (240, 142, 20), (248, 170, 14),
    (251, 199, 24), (248, 227, 52), (240, 249, 106), (252, 255, 164),
]
_QML_PALETTES: dict[str, list[tuple[int, int, int]]] = {
    "viridis": _QML_VIRIDIS,
    "inferno": _QML_INFERNO,
}
_PALETTE_LUT_CACHE: dict[str, list[tuple[int, int, int]]] = {}


def _palette_lut(name: str) -> list[tuple[int, int, int]]:
    """256-level RGB LUT exactly matching ChartUtil.js buildLut().

    Unknown palette names fall back to viridis, same as ChartUtil.paletteColor.
    """
    key = name if name in _QML_PALETTES else "viridis"
    cached = _PALETTE_LUT_CACHE.get(key)
    if cached is not None:
        return cached
    anchors = _QML_PALETTES[key]
    segments = len(anchors) - 1
    lut: list[tuple[int, int, int]] = []
    for index in range(256):
        position = (index / 255.0) * segments
        lower = min(int(math.floor(position)), segments - 1)
        fraction = position - lower
        first, second = anchors[lower], anchors[lower + 1]
        lut.append((
            int(math.floor(first[0] + (second[0] - first[0]) * fraction + 0.5)),
            int(math.floor(first[1] + (second[1] - first[1]) * fraction + 0.5)),
            int(math.floor(first[2] + (second[2] - first[2]) * fraction + 0.5)),
        ))
    _PALETTE_LUT_CACHE[key] = lut
    return lut

# Pure black is the locked plot background (user hard constraint: pure black
# plot area). Missing/invalid raster cells use the same black - never a colour
# that could be mistaken for low-level data.
BLACK = 0xFF000000
DEFAULT_CACHE_ENTRIES = 128
MAX_RASTER_SIDE = 1024


def _interpolate(stops: list[tuple[float, float, float]], position: float) -> tuple[int, int, int]:
    position = max(0.0, min(1.0, float(position)))
    scaled = position * (len(stops) - 1)
    lower = int(scaled)
    upper = min(len(stops) - 1, lower + 1)
    fraction = scaled - lower
    low = stops[lower]
    high = stops[upper]
    return (
        int(255 * (low[0] + (high[0] - low[0]) * fraction)),
        int(255 * (low[1] + (high[1] - low[1]) * fraction)),
        int(255 * (low[2] + (high[2] - low[2]) * fraction)),
    )


def colormap(name: str, position: float) -> tuple[int, int, int]:
    if name == "cividis":
        return _interpolate(_CIVIDIS, position)
    if name == "diverging":
        return _interpolate(_DIVERGING, position)
    return _interpolate(_VIRIDIS, position)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


@dataclass(frozen=True)
class ColorRange:
    """Explicit colour-scale range; locked ranges are never autoscaled."""
    min: float
    max: float
    locked: bool = True

    def span(self) -> float:
        return max(1e-12, float(self.max) - float(self.min))


def resolve_range(values: Iterable[Any], *, locked_range: tuple[float, float] | None = None,
                  min_value: float | None = None,
                  max_value: float | None = None) -> ColorRange | None:
    """Resolve the display colour range from the data or an explicit/locked range."""
    if locked_range is not None:
        low, high = float(locked_range[0]), float(locked_range[1])
        if math.isfinite(low) and math.isfinite(high) and high > low:
            return ColorRange(low, high, True)
    if min_value is not None and max_value is not None and max_value > min_value:
        return ColorRange(float(min_value), float(max_value), True)
    finite = [float(value) for value in values if _is_number(value)]
    if not finite:
        return None
    low = min_value if min_value is not None else min(finite)
    high = max_value if max_value is not None else max(finite)
    if not math.isfinite(float(low)) or not math.isfinite(float(high)):
        return None
    if not (float(high) > float(low)):
        # A single-level frame is still valid data; keep a symmetric display span
        # rather than returning no image (which would read as "no data").
        return ColorRange(float(low) - 1.0, float(high) + 1.0, True)
    return ColorRange(float(low), float(high), True)


def _palette_pixel(name: str, value: Any, color_range: ColorRange | None) -> int:
    if not _is_number(value) or color_range is None:
        return BLACK
    position = (float(value) - color_range.min) / color_range.span()
    red, green, blue = colormap(name, position)
    return (0xFF << 24) | (red << 16) | (green << 8) | blue


def heatmap_image(matrix: Sequence[Sequence[Any]], *, palette: str = "viridis",
                  min_value: float | None = None,
                  max_value: float | None = None,
                  locked_range: tuple[float, float] | None = None,
                  invalid_color: int = BLACK,
                  background: int = BLACK) -> QImage:
    """Build a QImage from a row-major matrix (first row = bottom of the image).

    None / NaN / non-finite cells are missing data: they stay at invalid_color
    (pure black by default) and are never interpolated from their neighbours.
    locked_range pins the palette range from the payload so repeated frames keep
    one shared colour scale.
    """
    rows = len(matrix)
    if rows == 0:
        return QImage()
    columns = max(1, len(matrix[0]))
    for row in matrix:
        columns = max(columns, len(row))
    flat = [value for row in matrix for value in row]
    color_range = resolve_range(flat, locked_range=locked_range,
                                min_value=min_value, max_value=max_value)
    if color_range is None:
        return QImage()
    image = QImage(columns, rows, QImage.Format.Format_RGB32)
    image.fill(background)
    for row_index, row in enumerate(matrix):
        for column_index in range(columns):
            value = row[column_index] if column_index < len(row) else None
            pixel = _palette_pixel(palette, value, color_range)
            if not _is_number(value):
                pixel = invalid_color
            image.setPixel(column_index, rows - 1 - row_index, pixel)
    return image


# --------------------------------------------------------------------- STFT
def stft_image(frames: Sequence[Any], *, frequency_axis: dict[str, Any] | None = None,
               time_axis: dict[str, Any] | None = None,
               color_scale: dict[str, Any] | None = None,
               width: int = 0, height: int = 0) -> QImage:
    """Render ordered STFT frames as a display raster.

    Frames are {time: seconds, points: [[frequencyHz, level], ...]}. Only the real
    frames are rendered: times without a frame (missing frames / hop gaps) stay
    pure black, and bins absent from a frame stay black as well. Pixels are mapped
    through the supplied frequency/time axes (log geometry is rendered here, not
    resampled by the QML component) using nearest-cell selection; no value is
    interpolated or bridged. An empty / unusable payload returns a null QImage
    (the QML chart then shows its explicit empty state).
    """
    rows = [frame for frame in (frames or []) if isinstance(frame, dict)]
    if not rows:
        return QImage()
    first_points = [point for point in (rows[0].get("points") or [])
                    if isinstance(point, (list, tuple)) and len(point) >= 2 and _is_number(point[0])]
    if not first_points:
        return QImage()
    frequencies = [float(point[0]) for point in first_points]
    if not (frequencies[-1] > frequencies[0]):
        return QImage()
    times = [float(frame.get("time")) for frame in rows if _is_number(frame.get("time"))]
    if not times:
        return QImage()
    times.sort()
    if len(times) == 1:
        times = [times[0], times[0] + 1.0]

    freq = frequency_axis or {}
    f_min = float(freq.get("min", frequencies[0]))
    f_max = float(freq.get("max", frequencies[-1]))
    f_scale = str(freq.get("scale") or "linear")
    if f_scale == "log" and (f_min <= 0 or f_max <= f_min):
        f_scale = "linear"
    if not (f_max > f_min):
        return QImage()
    time_cfg = time_axis or {}
    t_min = float(time_cfg.get("min", times[0]))
    t_max = float(time_cfg.get("max", times[-1]))
    if not (t_max > t_min):
        t_max = t_min + 1.0
    color_cfg = color_scale or {}
    levels = [float(point[1]) for frame in rows for point in (frame.get("points") or [])
              if isinstance(point, (list, tuple)) and len(point) >= 2 and _is_number(point[1])]
    if not levels:
        return QImage()
    locked = None
    if _is_number(color_cfg.get("min")) and _is_number(color_cfg.get("max")):
        locked = (float(color_cfg["min"]), float(color_cfg["max"]))
    color_range = resolve_range(levels, locked_range=locked)
    if color_range is None:
        return QImage()
    palette = str(color_cfg.get("palette") or "viridis")

    pixel_w = int(width) if width else max(2, min(MAX_RASTER_SIDE, len(frequencies)))
    pixel_h = int(height) if height else max(2, min(MAX_RASTER_SIDE, len(rows)))
    pixel_w = max(1, min(MAX_RASTER_SIDE, pixel_w))
    pixel_h = max(1, min(MAX_RASTER_SIDE, pixel_h))
    image = QImage(pixel_w, pixel_h, QImage.Format.Format_RGB32)
    image.fill(BLACK)

    if len(times) > 1:
        gaps = sorted(times[index + 1] - times[index] for index in range(len(times) - 1))
        # The smallest retained-frame interval is the real hop; time rows farther
        # than half a hop from any retained frame stay empty (no frame invention).
        spacing = gaps[0] if gaps else 0.0
    else:
        spacing = 0.0
    tolerance = 0.5 * spacing if spacing > 0 else float("inf")

    def freq_index(value: float) -> int:
        if value <= frequencies[0]:
            return 0
        if value >= frequencies[-1]:
            return len(frequencies) - 1
        low, high = 0, len(frequencies) - 1
        while low + 1 < high:
            middle = (low + high) // 2
            if frequencies[middle] <= value:
                low = middle
            else:
                high = middle
        return low if (value - frequencies[low]) <= (frequencies[high] - value) else high

    for row in range(pixel_h):
        fraction = 1.0 - (row + 0.5) / pixel_h
        time_value = t_min + fraction * (t_max - t_min)
        frame = None
        best_distance = tolerance
        for candidate in rows:
            candidate_time = candidate.get("time")
            if not _is_number(candidate_time):
                continue
            distance = abs(float(candidate_time) - time_value)
            if distance <= best_distance:
                best_distance = distance
                frame = candidate
        if frame is None:
            continue
        values_by_bin: dict[int, float] = {}
        for point in frame.get("points") or []:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            if not _is_number(point[0]) or not _is_number(point[1]):
                continue
            values_by_bin[freq_index(float(point[0]))] = float(point[1])
        for column in range(pixel_w):
            column_fraction = (column + 0.5) / pixel_w
            if f_scale == "log":
                frequency_value = f_min * (f_max / f_min) ** column_fraction
            else:
                frequency_value = f_min + column_fraction * (f_max - f_min)
            value = values_by_bin.get(freq_index(frequency_value))
            if value is None:
                continue
            image.setPixel(column, row, _palette_pixel(palette, value, color_range))
    return image


# ----------------------------------------------------- STFT heat-map display
def stft_heatmap_image(matrix: Sequence[Sequence[Any]], *,
                       frequency_axis: dict[str, Any] | None = None,
                       color_scale: dict[str, Any] | None = None,
                       palette: str = "inferno",
                       width: int = 0, height: int = 0) -> QImage:
    """Render the decoder STFT raster in HeatmapChart *screen* orientation.

    'matrix' is the decoder contract raster (see ui/features/decoder.py
    '_recipe_stft'): row 0 is the newest retained frame and the last row is
    the oldest, each column a uniform linear FFT bin.  HeatmapChart paints
    retained frames on x (left = first frame) and the frequency axis on y
    (bottom = frequency_axis['min'], log or linear), so the image is built
    directly in that geometry instead of being resampled by QML:

    * frequency: every image row is mapped through the displayed axis
      (min/max/scale) and bilinearly sampled in the linear bin domain
      dataMin..dataMax (defaults to min/max), exactly like the old Canvas
      sampleMatrix bilinear sampler;
    * frames: columns are linearly interpolated between retained frames
      (left = first frame), like the old Canvas bilinear time sampler;
    * colour: 256-level LUT identical to ChartUtil.js, so the surface matches
      the colour bar.  Missing / NaN cells stay pure black (never a low
      value).

    frequency_axis carries the display axis (min, max, scale) plus the data
    domain (dataMin, dataMax) the raster columns span.  color_scale is the
    locked display range {min, max}; when it is absent/invalid the finite data
    range is used.  width/height are the small display raster size (the QML
    Image stretches it over the plot area).  Returns a null QImage when
    nothing displayable was supplied.
    """
    rows = [row for row in (matrix or [])
            if isinstance(row, (list, tuple)) and row]
    if not rows:
        return QImage()
    bins = max(len(row) for row in rows)
    frames = len(rows)
    if bins < 1:
        return QImage()

    freq = frequency_axis if isinstance(frequency_axis, dict) else {}
    display_min = freq.get("min")
    display_max = freq.get("max")
    if not (_is_number(display_min) and _is_number(display_max)):
        return QImage()
    display_min, display_max = float(display_min), float(display_max)
    if not (display_max > display_min):
        return QImage()
    data_min = freq.get("dataMin")
    data_max = freq.get("dataMax")
    data_min = float(data_min) if _is_number(data_min) else display_min
    data_max = float(data_max) if _is_number(data_max) else display_max
    if not (data_max > data_min):
        data_min, data_max = display_min, display_max
    log_axis = (str(freq.get("scale") or "") == "log"
                and display_min > 0 and display_max > display_min)

    scale_cfg = color_scale if isinstance(color_scale, dict) else {}
    low = scale_cfg.get("min")
    high = scale_cfg.get("max")
    if not (_is_number(low) and _is_number(high)
            and float(high) > float(low)):
        finite = [value for row in rows for value in row if _is_number(value)]
        if not finite:
            return QImage()
        low = min(finite)
        high = max(finite)
        if not float(high) > float(low):
            low = float(low) - 1.0
            high = float(high) + 1.0
    low, high = float(low), float(high)

    pixel_w = int(width) if width else min(128, max(2, frames * 8))
    pixel_h = int(height) if height else 160
    pixel_w = max(1, min(MAX_RASTER_SIDE, pixel_w))
    pixel_h = max(1, min(MAX_RASTER_SIDE, pixel_h))

    # frequency row -> bin pair + bilinear fraction (row 0 = top = axis max)
    row_bins: list[tuple[int, int, float]] = []
    domain_span = data_max - data_min
    for row in range(pixel_h):
        fraction = 1.0 - (row + 0.5) / pixel_h
        if log_axis:
            value = display_min * (display_max / display_min) ** fraction
        else:
            value = display_min + fraction * (display_max - display_min)
        position = (value - data_min) / domain_span * (bins - 1)
        if position <= 0.0:
            row_bins.append((0, 0, 0.0))
        elif position >= bins - 1:
            row_bins.append((bins - 1, bins - 1, 0.0))
        else:
            lower = int(position)
            row_bins.append((lower, lower + 1, position - lower))

    # column -> frame pair + fraction (column 0 = first retained frame)
    col_frames: list[tuple[int, int, float]] = []
    for column in range(pixel_w):
        if frames > 1:
            position = ((column + 0.5) / pixel_w) * (frames - 1)
            lower = int(position)
            if lower >= frames - 1:
                col_frames.append((frames - 1, frames - 1, 0.0))
            else:
                col_frames.append((lower, lower + 1, position - lower))
        else:
            col_frames.append((0, 0, 0.0))

    frame_rows = [rows[frames - 1 - index] for index in range(frames)]
    lut = _palette_lut(palette)
    packed = [((0xFF << 24) | (red << 16) | (green << 8) | blue)
              for red, green, blue in lut]
    color_scale_factor = 255.0 / (high - low)
    buffer = bytearray(pixel_w * pixel_h * 4)
    offset = 0
    for row in range(pixel_h):
        lower_bin, upper_bin, bin_fraction = row_bins[row]
        values: list[float | None] = []
        for frame_row in frame_rows:
            lower_value = (frame_row[lower_bin]
                           if lower_bin < len(frame_row) else None)
            upper_value = (frame_row[upper_bin]
                           if upper_bin < len(frame_row) else None)
            if lower_value is None:
                values.append(upper_value)
            elif upper_value is None or upper_bin == lower_bin:
                values.append(lower_value)
            else:
                values.append(lower_value
                              + (upper_value - lower_value) * bin_fraction)
        for column in range(pixel_w):
            first, second, frame_fraction = col_frames[column]
            value = values[first]
            if second != first and frame_fraction != 0.0:
                other = values[second]
                if value is None:
                    value = other
                elif other is not None:
                    value = value + (other - value) * frame_fraction
            if value is None:
                packed_color = BLACK
            else:
                level = int((value - low) * color_scale_factor + 0.5)
                if level < 0:
                    level = 0
                elif level > 255:
                    level = 255
                packed_color = packed[level]
            buffer[offset] = packed_color & 0xFF
            buffer[offset + 1] = (packed_color >> 8) & 0xFF
            buffer[offset + 2] = (packed_color >> 16) & 0xFF
            buffer[offset + 3] = 0xFF
            offset += 4
    # copy(): the QImage must not alias the transient Python buffer.
    return QImage(bytes(buffer), pixel_w, pixel_h,
                  QImage.Format.Format_RGB32).copy()


# ---------------------------------------------------------------------- DAS
def das_image(points: Sequence[Any], *, azimuth_axis: dict[str, Any] | None = None,
              elevation_axis: dict[str, Any] | None = None,
              color_scale: dict[str, Any] | None = None,
              projection: str = "rect", size: int = 256,
              width: int = 0, height: int = 0) -> QImage:
    """Render directional-power points (azimuth, elevation, power) as a raster.

    rect maps azimuth to x / elevation to y. polar renders a square polar raster
    (azimuth 0 at the top, clockwise; elevation min at the centre, max at the
    outer edge) matching PolarChart's frame. Only supplied points are drawn -
    other cells stay pure black, and the raster is never used to derive an
    automatic DOA. Returns a null image when nothing usable was supplied.
    """
    valid: list[tuple[float, float, float]] = []
    for point in points or []:
        if isinstance(point, dict):
            azimuth, elevation, power = (point.get("azimuth"), point.get("elevation"),
                                         point.get("power"))
        elif isinstance(point, (list, tuple)) and len(point) >= 3:
            azimuth, elevation, power = point[0], point[1], point[2]
        else:
            continue
        if _is_number(azimuth) and _is_number(elevation) and _is_number(power):
            valid.append((float(azimuth), float(elevation), float(power)))
    if not valid:
        return QImage()
    az_cfg = azimuth_axis or {}
    el_cfg = elevation_axis or {}
    az_min = float(az_cfg.get("min", min(p[0] for p in valid)))
    az_max = float(az_cfg.get("max", max(p[0] for p in valid)))
    el_min = float(el_cfg.get("min", min(p[1] for p in valid)))
    el_max = float(el_cfg.get("max", max(p[1] for p in valid)))
    if not (az_max > az_min):
        az_max = az_min + 1.0
    if not (el_max > el_min):
        el_max = el_min + 1.0
    color_cfg = color_scale or {}
    locked = None
    if _is_number(color_cfg.get("min")) and _is_number(color_cfg.get("max")):
        locked = (float(color_cfg["min"]), float(color_cfg["max"]))
    color_range = resolve_range((p[2] for p in valid), locked_range=locked)
    if color_range is None:
        return QImage()
    palette = str(color_cfg.get("palette") or "viridis")
    pixel_w = max(1, min(MAX_RASTER_SIDE, int(width) if width else int(size)))
    pixel_h = max(1, min(MAX_RASTER_SIDE, int(height) if height else int(size)))
    image = QImage(pixel_w, pixel_h, QImage.Format.Format_RGB32)
    image.fill(BLACK)

    nearest: dict[tuple[int, int], float] = {}
    if projection == "polar":
        side = min(pixel_w, pixel_h)
        radius = side / 2.0
        for azimuth, elevation, power in valid:
            angle = math.radians(azimuth - 90.0)
            elevation_fraction = ((elevation - el_min) / (el_max - el_min)) if el_max > el_min else 0.0
            distance = max(0.0, min(1.0, elevation_fraction)) * max(0.0, radius - 1)
            x = int(round(pixel_w / 2.0 + math.cos(angle) * distance))
            y = int(round(pixel_h / 2.0 + math.sin(angle) * distance))
            if 0 <= x < pixel_w and 0 <= y < pixel_h:
                nearest[(x, y)] = power
    else:
        for azimuth, elevation, power in valid:
            x = int(round((azimuth - az_min) / (az_max - az_min) * (pixel_w - 1)))
            y = int(round((1.0 - (elevation - el_min) / (el_max - el_min)) * (pixel_h - 1)))
            x = max(0, min(pixel_w - 1, x))
            y = max(0, min(pixel_h - 1, y))
            nearest[(x, y)] = power
    for (x, y), power in nearest.items():
        image.setPixel(x, y, _palette_pixel(palette, power, color_range))
    return image


# ------------------------------------------------------- display extraction
def peak_envelope(values: Sequence[Any], budget: int = 4096) -> list[float | None]:
    """Bounded waveform display extraction preserving transient peaks.

    Each bucket keeps its minimum then maximum sample (no averaging), so peaks
    survive downsampling. Invalid samples produce None (a real gap), never a
    synthetic zero. This is display extraction only, not acoustic processing.
    """
    limit = max(64, int(budget or 4096))
    count = len(values or [])
    if count <= limit:
        return list(values or [])
    buckets = max(1, limit // 2)
    stride = count / buckets
    out: list[float | None] = []
    for index in range(buckets):
        start = int(index * stride)
        end = min(count, int((index + 1) * stride))
        if end <= start:
            continue
        low: float | None = None
        high: float | None = None
        for position in range(start, end):
            value = values[position]
            if not _is_number(value):
                continue
            numeric = float(value)
            low = numeric if low is None else min(low, numeric)
            high = numeric if high is None else max(high, numeric)
        out.extend([low, high])
    return out


# ------------------------------------------------------------------- cache
class FeatureRasterCache:
    """Bounded LRU raster cache with revisions for image://plots/<key>/<rev>."""

    def __init__(self, max_entries: int = DEFAULT_CACHE_ENTRIES) -> None:
        self.max_entries = max(1, int(max_entries))
        self._images: OrderedDict[str, QImage] = OrderedDict()
        self._revisions: dict[str, int] = {}

    def put(self, key: str, image: QImage) -> int:
        key = str(key)
        self._images[key] = image
        self._images.move_to_end(key)
        self._revisions[key] = self._revisions.get(key, 0) + 1
        while len(self._images) > self.max_entries:
            evicted, _ = self._images.popitem(last=False)
            if evicted != key:
                self._revisions.pop(evicted, None)
        return self._revisions[key]

    def revision(self, key: str) -> int:
        return self._revisions.get(str(key), 0)

    def image(self, key: str) -> QImage | None:
        image = self._images.get(str(key))
        if image is None:
            return None
        self._images.move_to_end(str(key))
        return image

    def invalidate(self, key: str) -> None:
        self._images.pop(str(key), None)
        self._revisions.pop(str(key), None)

    def clear(self) -> None:
        self._images.clear()
        self._revisions.clear()

    def keys(self) -> list[str]:
        return list(self._images.keys())

    def __len__(self) -> int:
        return len(self._images)


def image_url(cache: FeatureRasterCache, key: str) -> str:
    revision = cache.revision(key)
    if not revision:
        return ""
    return "image://plots/" + str(key) + "/" + str(revision)


class PlotImageProvider(QQuickImageProvider):
    def __init__(self, max_entries: int = DEFAULT_CACHE_ENTRIES) -> None:
        super().__init__(QQmlImageProviderBase.ImageType.Image)
        self.cache = FeatureRasterCache(max_entries)

    def set_image(self, key: str, image: QImage) -> int:
        return self.cache.put(key, image)

    def revision(self, key: str) -> int:
        return self.cache.revision(key)

    def image(self, key: str) -> QImage | None:
        return self.cache.image(key)

    def requestImage(self, image_id: str, size: QSize,  # noqa: N802
                     requested_size: QSize | None = None) -> QImage:
        key = str(image_id).split("/")[0]
        image = self.cache.image(key)
        if image is None or image.isNull():
            empty = QImage(2, 2, QImage.Format.Format_RGB32)
            empty.fill(BLACK)
            return empty
        return image