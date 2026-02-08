from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import box

from cutter_pipeline.stl_cutter import polygon_to_cookie_cutter_stl


def _radial_band_stats(mesh: trimesh.Trimesh, z_min: float, z_max: float) -> tuple[float, float]:
    verts = mesh.vertices
    band = verts[(verts[:, 2] >= z_min) & (verts[:, 2] <= z_max)]
    if len(band) == 0:
        return 0.0, 0.0
    center = band[:, :2].mean(axis=0)
    d = np.linalg.norm(band[:, :2] - center, axis=1)
    outer_r = float(np.percentile(d, 95))
    inner_r = float(np.percentile(d, 5))
    return outer_r, inner_r


def test_polygon_to_cookie_cutter_stl(tmp_path: Path) -> None:
    square = box(0, 0, 1, 1)
    out_path = tmp_path / "cutter.stl"

    polygon_to_cookie_cutter_stl(
        square,
        str(out_path),
        target_width_mm=80.0,
        wall_mm=1.2,
        total_h_mm=20.0,
        flange_h_mm=6.0,
        flange_out_mm=5.0,
        cleanup_mm=0.4,
        tip_smooth_mm=0.5,
        drop_holes=True,
        min_component_area_mm2=10.0,
    )

    assert out_path.exists()
    mesh = trimesh.load(out_path, force="mesh")

    assert mesh.vertices.shape[0] > 0
    # X extent should at least match target width (flange grows it further).
    assert mesh.extents[0] >= 80.0


def test_taper_reduces_top_wall_thickness(tmp_path: Path) -> None:
    square = box(0, 0, 1, 1)
    out_path = tmp_path / "taper.stl"

    polygon_to_cookie_cutter_stl(
        square,
        str(out_path),
        target_width_mm=60.0,
        wall_mm=1.0,
        total_h_mm=20.0,
        flange_h_mm=6.0,
        flange_out_mm=5.0,
        cleanup_mm=0.0,
        tip_smooth_mm=0.0,
        drop_holes=True,
        min_component_area_mm2=1.0,
        bevel_h_mm=2.0,
        bevel_top_wall_mm=0.5,
    )

    mesh = trimesh.load(out_path, force="mesh")
    zmax = mesh.vertices[:, 2].max()
    bevel_h = 2.0
    top_outer, top_inner = _radial_band_stats(mesh, zmax - 0.2, zmax + 1e-6)
    mid_outer, mid_inner = _radial_band_stats(mesh, zmax - bevel_h - 0.1, zmax - bevel_h + 0.1)

    assert top_outer < mid_outer - 0.3, f"Taper too small (top {top_outer:.3f}, mid {mid_outer:.3f})"
    assert abs(top_inner - mid_inner) < 0.2, (
        f"Inner wall drifted (top {top_inner:.3f}, mid {mid_inner:.3f})"
    )
