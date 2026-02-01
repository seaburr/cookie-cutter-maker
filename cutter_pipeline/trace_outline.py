from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from shapely.geometry import LineString, Polygon
from skimage import measure

@dataclass
class TraceResult:
    polygon: Polygon
    svg_path: str
    svg_file: str

def _svg_from_coords(coords: list[tuple[float, float]]) -> str:
    d = f"M {coords[0][0]:.6f},{coords[0][1]:.6f} "
    for x, y in coords[1:]:
        d += f"L {x:.6f},{y:.6f} "
    d += "Z"
    return d

def trace_png_to_polygon(
    png_path: str,
    svg_out_path: str,
    threshold: int = 200,
    simplify_epsilon: float = 0.002,
    smooth_radius: float = 0.0,
) -> TraceResult:
    img = Image.open(png_path).convert("L")
    if smooth_radius > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=smooth_radius))
    arr = np.array(img)
    binary = (arr < threshold).astype(float)

    contours = measure.find_contours(binary, 0.5)
    if not contours:
        raise ValueError("No contours found. Try adjusting threshold.")

    contour = max(contours, key=lambda c: c.shape[0])
    h, w = arr.shape

    pts = np.array(contour)
    y = h - pts[:, 0]
    x = pts[:, 1]
    pts_xy = np.column_stack([x / w, y / h])

    line = LineString(pts_xy)
    simple = line.simplify(simplify_epsilon, preserve_topology=True)

    coords = list(simple.coords)
    poly = Polygon(coords).buffer(0)
    if poly.is_empty or not poly.is_valid:
        raise ValueError("Tracing produced invalid polygon. Try different simplify_epsilon/threshold.")

    svg_path_d = _svg_from_coords(coords)
    # Flip Y for on-screen preview (SVG y-axis is down). Geometry itself is unchanged.
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">
  <g transform="translate(0,1) scale(1,-1)">
    <path d="{svg_path_d}" fill="black"/>
  </g>
</svg>
'''
    out = Path(svg_out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")

    return TraceResult(polygon=poly, svg_path=svg_path_d, svg_file=str(out))
