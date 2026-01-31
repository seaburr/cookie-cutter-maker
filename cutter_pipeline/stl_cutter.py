from __future__ import annotations
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

def _sample_ring(coords, n: int):
    if coords[0] != coords[-1]:
        coords = list(coords) + [coords[0]]
    line = LineString(coords)
    return [line.interpolate(line.length * (i / n)).coords[0] for i in range(n)]

def polygon_to_cookie_cutter_stl(
    polygon: Polygon,
    out_path: str,
    target_width_mm: float = 95.0,
    wall_mm: float = 1.0,
    total_h_mm: float = 28.0,
    flange_h_mm: float = 7.226,
    flange_out_mm: float = 6.0,
    samples: int = 520,
    cleanup_mm: float = 0.5,
    drop_holes: bool = True,
    min_component_area_mm2: float = 25.0,
    tip_smooth_mm: float = 0.6,
) -> str:
    # Normalise orientation so exterior is CCW (helps keep triangle winding consistent)
    poly = orient(polygon.buffer(0), sign=1.0)
    if poly.is_empty:
        raise ValueError("Empty polygon")

    minx, miny, maxx, maxy = poly.bounds
    w = maxx - minx
    if w <= 0:
        raise ValueError("Invalid polygon bounds")
    scale = target_width_mm / w

    scaled = Polygon([(x * scale, y * scale) for x, y in poly.exterior.coords]).buffer(0)
    if drop_holes:
        scaled = Polygon(scaled.exterior)
    if cleanup_mm > 0:
        scaled = scaled.buffer(cleanup_mm, join_style=1, cap_style=2).buffer(
            -cleanup_mm, join_style=1, cap_style=2
        )
    if tip_smooth_mm > 0:
        # Smooth high-curvature tips so the inner offset doesn't collapse to nothing
        scaled = scaled.buffer(tip_smooth_mm, join_style=1, cap_style=1).buffer(
            -tip_smooth_mm, join_style=1, cap_style=1
        )
    if scaled.geom_type == "MultiPolygon":
        parts = [g for g in scaled.geoms if g.area >= min_component_area_mm2]
        if not parts:
            parts = [max(scaled.geoms, key=lambda g: g.area)]
        scaled = parts[0]

    inner = scaled.buffer(-wall_mm, join_style=1, cap_style=2).buffer(0)
    if inner.is_empty:
        raise ValueError("Inner offset collapsed. Increase target_width_mm or reduce wall_mm.")

    outer_flange = scaled.buffer(flange_out_mm, join_style=1, cap_style=2).buffer(0)

    # Build solid shells with caps, then drop caps to keep ends open.
    extrude_kwargs = {"engine": "earcut"}
    body_poly = Polygon(scaled.exterior.coords, holes=[inner.exterior.coords])
    body = trimesh.creation.extrude_polygon(body_poly, total_h_mm, **extrude_kwargs)
    flange_poly = Polygon(outer_flange.exterior.coords, holes=[scaled.exterior.coords])
    flange = trimesh.creation.extrude_polygon(flange_poly, flange_h_mm, **extrude_kwargs)

    def drop_caps(m):
        nz = m.face_normals[:, 2]
        keep = np.abs(nz) < 0.99
        return m.submesh([keep], append=True)

    body = drop_caps(body)
    flange = drop_caps(flange)

    mesh = trimesh.util.concatenate([body, flange])
    mesh.merge_vertices()

    # Fix normals and enforce outward-facing winding so slicers don't see the mesh inside-out
    if not mesh.is_winding_consistent:
        mesh.fix_normals()
    if mesh.volume < 0:
        mesh.invert()

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(out))
    return str(out)
