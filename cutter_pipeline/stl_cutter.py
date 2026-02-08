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
    total_h_mm: float = 25.0,
    flange_h_mm: float = 7.226,
    flange_out_mm: float = 5.0,
    bevel_h_mm: float = 2.0,
    bevel_top_wall_mm: float = 0.5,
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

    # Ensure inner offset doesn't collapse; grow outline if needed to preserve minimum wall.
    grow = 0.0
    for _ in range(10):
        inner = scaled.buffer(-(wall_mm), join_style=1, cap_style=2).buffer(0)
        if not inner.is_empty and inner.area > 0:
            break
        grow += 0.5
        scaled = scaled.buffer(0.5, join_style=1, cap_style=2).buffer(0)
    else:
        raise ValueError("Inner offset collapsed. Increase target_width_mm or reduce wall_mm.")

    outer_flange = scaled.buffer(flange_out_mm, join_style=1, cap_style=2).buffer(0)

    bevel_h_mm = max(0.0, min(bevel_h_mm, total_h_mm))
    target_top_wall = max(0.1, min(bevel_top_wall_mm, wall_mm))
    bevel_start_z = total_h_mm - bevel_h_mm

    def _sample(coords):
        return np.array(_sample_ring(coords, samples))

    def _offset_outer(poly: Polygon, delta: float) -> Polygon | None:
        if delta <= 0:
            return poly
        out = poly.buffer(-delta, join_style=1, cap_style=2).buffer(0)
        if out.is_empty:
            return None
        if out.geom_type == "MultiPolygon":
            out = max(out.geoms, key=lambda g: g.area)
        if out.is_empty or out.area <= 0:
            return None
        return out

    use_taper = bevel_h_mm > 0 and target_top_wall < wall_mm
    top_outer = None
    if use_taper:
        top_outer = _offset_outer(scaled, wall_mm - target_top_wall)
        if top_outer is None or top_outer.area <= inner.area:
            use_taper = False

    if use_taper:
        outer = orient(scaled, sign=1.0)
        inner_oriented = orient(inner, sign=1.0)
        top_outer = orient(top_outer, sign=1.0)

        outer_ring = _sample(list(outer.exterior.coords))
        inner_ring = _sample(list(inner_oriented.exterior.coords))[::-1]
        top_outer_ring = _sample(list(top_outer.exterior.coords))

        rings: list[tuple[np.ndarray, float]] = []

        def add_ring(ring: np.ndarray, z: float) -> int:
            rings.append((ring, z))
            return (len(rings) - 1) * samples

        outer0 = add_ring(outer_ring, 0.0)
        inner0 = add_ring(inner_ring, 0.0)
        outer1 = outer0
        inner1 = inner0
        if bevel_start_z > 0:
            outer1 = add_ring(outer_ring, bevel_start_z)
            inner1 = add_ring(inner_ring, bevel_start_z)
        outer2 = add_ring(top_outer_ring, total_h_mm)
        inner2 = add_ring(inner_ring, total_h_mm)

        def strip(a_off: int, b_off: int, flip: bool = False):
            faces = []
            for i in range(samples):
                a0 = a_off + i
                a1 = a_off + ((i + 1) % samples)
                b0 = b_off + i
                b1 = b_off + ((i + 1) % samples)
                if not flip:
                    faces.append([a0, a1, b1])
                    faces.append([a0, b1, b0])
                else:
                    faces.append([a0, b1, a1])
                    faces.append([a0, b0, b1])
            return faces

        faces = []
        if bevel_start_z > 0:
            faces += strip(outer0, outer1, flip=False)
            faces += strip(inner1, inner0, flip=True)
        faces += strip(outer1, outer2, flip=False)
        faces += strip(inner2, inner1, flip=True)

        verts = np.vstack([np.column_stack([r, np.full((samples, 1), z)]) for r, z in rings])
        body = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    else:
        # Build solid shells with caps, then drop caps to keep ends open.
        extrude_kwargs = {"engine": "earcut"}
        body_poly = Polygon(scaled.exterior.coords, holes=[inner.exterior.coords])
        body = trimesh.creation.extrude_polygon(body_poly, total_h_mm, **extrude_kwargs)

    flange_poly = Polygon(outer_flange.exterior.coords, holes=[scaled.exterior.coords])
    flange = trimesh.creation.extrude_polygon(flange_poly, flange_h_mm, engine="earcut")

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
