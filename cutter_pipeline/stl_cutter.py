from __future__ import annotations
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient

def _sample_ring(coords, n: int):
    if coords[0] != coords[-1]:
        coords = list(coords) + [coords[0]]
    line = LineString(coords)
    return [line.interpolate(line.length * (i / n)).coords[0] for i in range(n)]


def _apply_outer_bevel(
    mesh: trimesh.Trimesh,
    inner_poly: Polygon,
    centroid_xy: np.ndarray,
    bevel_h_mm: float,
    bevel_out_mm: float,
    safety_mm: float = 0.35,
):
    """
    Taper the outer wall over the bottom bevel_h_mm by shifting vertices radially outward.
    Inner wall stays vertical so the cutting edge remains on the outer face only.
    """
    if bevel_h_mm <= 0 or bevel_out_mm <= 0:
        return mesh

    verts = mesh.vertices.copy()
    z0 = verts[:, 2].min()
    inner_boundary = inner_poly.boundary

    for idx, (x, y, z) in enumerate(verts):
        z_rel = z - z0
        if z_rel > bevel_h_mm + 1e-6:
            continue

        pt = Point(x, y)
        # Avoid tapering the inner wall; focus on the outward cutting edge.
        if inner_poly.contains(pt):
            continue

        dist_to_inner = inner_boundary.distance(pt)
        max_shift = max(0.0, dist_to_inner - safety_mm)
        if max_shift <= 1e-6:
            continue

        t = (bevel_h_mm - z_rel) / bevel_h_mm  # 1 at base, 0 at bevel top.
        shift = min(bevel_out_mm * t, max_shift)

        direction = np.array([x, y]) - centroid_xy
        norm = np.linalg.norm(direction)
        if norm < 1e-9:
            continue
        delta = direction / norm * shift
        verts[idx, 0] += delta[0]
        verts[idx, 1] += delta[1]

    mesh.vertices = verts
    return mesh


def _tapered_wall_segment(
    outer_bottom: Polygon,
    outer_top: Polygon,
    inner: Polygon,
    height_mm: float,
    samples: int,
) -> trimesh.Trimesh:
    """
    Build a hollow frustum: outer ring widens/shrinks between bottom and top,
    inner ring stays vertical (same coords bottom/top). No caps.
    """
    if height_mm <= 0:
        raise ValueError("height_mm must be positive for tapered wall segment")

    ob = np.array(_sample_ring(outer_bottom.exterior.coords, samples))
    ot = np.array(_sample_ring(outer_top.exterior.coords, samples))
    ib = np.array(_sample_ring(inner.exterior.coords, samples))
    it = ib.copy()

    z0 = np.zeros((samples, 1))
    z1 = np.ones((samples, 1)) * height_mm

    verts = np.vstack(
        [
            np.hstack([ob, z0]),  # 0 .. n-1 bottom outer
            np.hstack([ot, z1]),  # n .. 2n-1 top outer
            np.hstack([ib, z0]),  # 2n .. 3n-1 bottom inner
            np.hstack([it, z1]),  # 3n .. 4n-1 top inner
        ]
    )

    faces = []
    n = samples
    # Outer wall (ccw outward)
    for i in range(n):
        j = (i + 1) % n
        b_i, b_j = i, j
        t_i, t_j = n + i, n + j
        faces.append([b_i, b_j, t_i])
        faces.append([t_i, b_j, t_j])

    # Inner wall (reverse winding so normals point inward toward cavity)
    for i in range(n):
        j = (i + 1) % n
        b_i, b_j = 2 * n + i, 2 * n + j
        t_i, t_j = 3 * n + i, 3 * n + j
        faces.append([t_i, b_j, b_i])
        faces.append([t_j, b_j, t_i])

    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)

def polygon_to_cookie_cutter_stl(
    polygon: Polygon,
    out_path: str,
    target_width_mm: float = 95.0,
    wall_mm: float = 1.0,
    total_h_mm: float = 25.0,
    flange_h_mm: float = 7.226,
    flange_out_mm: float = 5.0,
    samples: int = 520,
    cleanup_mm: float = 0.5,
    drop_holes: bool = True,
    min_component_area_mm2: float = 25.0,
    tip_smooth_mm: float = 0.6,
    bevel_h_mm: float = 3.0,
    bevel_out_mm: float = 0.6,
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

    bevel_h_mm = max(0.0, min(bevel_h_mm, total_h_mm))
    straight_h_mm = total_h_mm - bevel_h_mm

    # Build beveled segment: outer face shrinks toward the top edge (z = total_h_mm).
    safe_bevel = min(bevel_out_mm, max(0.0, wall_mm * 0.9))  # avoid inverting wall
    outer_bottom = scaled
    outer_top = scaled.buffer(-safe_bevel, join_style=1, cap_style=2)
    bevel_segment = (
        _tapered_wall_segment(
            outer_bottom=outer_bottom,
            outer_top=outer_top,
            inner=inner,
            height_mm=bevel_h_mm,
            samples=samples,
        )
        if bevel_h_mm > 0 and safe_bevel > 0
        else None
    )

    # Straight wall below the bevel
    body_poly = Polygon(scaled.exterior.coords, holes=[inner.exterior.coords])
    straight_body = None
    if straight_h_mm > 0:
        straight_body = trimesh.creation.extrude_polygon(body_poly, straight_h_mm, **extrude_kwargs)
        # straight wall starts at z=0; bevel sits on top
    if bevel_segment is not None:
        bevel_segment.apply_translation((0, 0, straight_h_mm))
    flange_poly = Polygon(outer_flange.exterior.coords, holes=[scaled.exterior.coords])
    flange = trimesh.creation.extrude_polygon(flange_poly, flange_h_mm, **extrude_kwargs)
    # Flange stays at base (z=0)

    def drop_caps(m):
        nz = m.face_normals[:, 2]
        keep = np.abs(nz) < 0.99
        return m.submesh([keep], append=True)

    parts = []
    if bevel_segment is not None:
        parts.append(bevel_segment)
    if straight_body is not None:
        parts.append(drop_caps(straight_body))
    parts.append(drop_caps(flange))

    mesh = trimesh.util.concatenate(parts)
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
