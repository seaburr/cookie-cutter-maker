from pathlib import Path

import trimesh
from shapely.geometry import box

from cutter_pipeline.stl_cutter import polygon_to_cookie_cutter_stl


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
