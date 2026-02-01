import os
import uuid
import json
import logging
from typing import Any
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cutter_pipeline.trace_outline import trace_png_to_polygon
from cutter_pipeline.stl_cutter import polygon_to_cookie_cutter_stl
from shapely.geometry import shape, mapping
import trimesh
import zipfile
from openai import OpenAIError

# Optional: prompt->png requires OPENAI_API_KEY
try:
    from cutter_pipeline.outline_openai import generate_outline_png
    HAS_OPENAI = True
except Exception:
    HAS_OPENAI = False

app = FastAPI(title="Cookie Cutter Maker", version="0.2.0")

OUTPUT_DIR = Path(os.environ.get("PIPELINE_OUTPUT_DIR", "output")).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception):
    """Return the real error message to the client while logging the stack."""
    logging.exception("Unhandled error during %s %s", request.method, request.url, exc_info=exc)
    detail = str(exc).strip() or exc.__class__.__name__
    return JSONResponse(status_code=500, content={"detail": detail})

@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

@app.get("/health")
def health():
    return {"ok": True}

def _new_job_dir() -> Path:
    job_id = uuid.uuid4().hex
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def _write_zip(job_dir: Path, files: list[Path], base_name: str = "all") -> Path:
    zip_path = job_dir / f"{base_name}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f.exists():
                zf.write(f, arcname=f.name)
    return zip_path


def _save_polygon(job_dir: Path, polygon) -> Path:
    poly_path = job_dir / "polygon.json"
    poly_path.write_text(json.dumps(mapping(polygon)), encoding="utf-8")
    return poly_path


def _load_polygon(job_dir: Path):
    poly_path = job_dir / "polygon.json"
    if not poly_path.exists():
        raise HTTPException(status_code=404, detail="Polygon for this job not found. Trace or prompt again.")
    data = json.loads(poly_path.read_text(encoding="utf-8"))
    return shape(data)


def _find_png(job_dir: Path, name: str) -> Path:
    candidate = job_dir / f"{name}.png"
    if candidate.exists():
        return candidate
    matches = list(job_dir.glob("*.png"))
    if matches:
        return matches[0]
    raise HTTPException(status_code=404, detail="PNG not found for this job. Upload or generate first.")


def _openai_detail(exc: OpenAIError) -> str:
    """Prefer the nested OpenAI error message if available."""
    # Newer openai client exposes .body with {'error': {'message': ...}}
    body: Any = getattr(exc, "body", None)
    if isinstance(body, dict):
        msg = body.get("error", {}).get("message") or body.get("message")
        if msg:
            return str(msg)
    msg = getattr(exc, "message", None)
    if msg:
        return str(msg)
    return str(exc).strip() or exc.__class__.__name__

@app.post("/trace/from-png")
async def trace_from_png(
    file: UploadFile = File(...),
    name: str = Form("outline"),
    threshold: int = Form(200),
    simplify: float = Form(0.002),
    smooth_radius: float = Form(1.0),
):
    if not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Upload a PNG/JPG outline image")

    job_dir = _new_job_dir()
    png_path = job_dir / f"{name}.png"
    svg_path = job_dir / f"{name}.svg"

    png_path.write_bytes(await file.read())
    traced = trace_png_to_polygon(
        str(png_path),
        str(svg_path),
        threshold=threshold,
        simplify_epsilon=simplify,
        smooth_radius=smooth_radius,
    )
    _save_polygon(job_dir, traced.polygon)

    return {
        "job_id": job_dir.name,
        "svg": f"/files/{job_dir.name}/{name}.svg",
        "png": f"/files/{job_dir.name}/{name}.png",
    }

@app.post("/pipeline/from-png")
async def pipeline_from_png(
    file: UploadFile = File(...),
    name: str = Form("cookie_cutter"),
    width_mm: float = Form(95.0),
    wall_mm: float = Form(1.0),
    total_h_mm: float = Form(28.0),
    flange_h_mm: float = Form(7.226),
    flange_out_mm: float = Form(6.0),
    cleanup_mm: float = Form(0.5),
    tip_smooth_mm: float = Form(0.6),
    keep_holes: bool = Form(False),
    min_component_area_mm2: float = Form(25.0),
    threshold: int = Form(200),
    simplify: float = Form(0.002),
    smooth_radius: float = Form(1.0),
):
    if not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Upload a PNG/JPG outline image")

    job_dir = _new_job_dir()
    png_path = job_dir / f"{name}.png"
    svg_path = job_dir / f"{name}.svg"
    stl_path = job_dir / f"{name}.stl"

    png_path.write_bytes(await file.read())
    traced = trace_png_to_polygon(
        str(png_path),
        str(svg_path),
        threshold=threshold,
        simplify_epsilon=simplify,
        smooth_radius=smooth_radius,
    )
    _save_polygon(job_dir, traced.polygon)

    polygon_to_cookie_cutter_stl(
        traced.polygon,
        str(stl_path),
        target_width_mm=width_mm,
        wall_mm=wall_mm,
        total_h_mm=total_h_mm,
        flange_h_mm=flange_h_mm,
        flange_out_mm=flange_out_mm,
        cleanup_mm=cleanup_mm,
        tip_smooth_mm=tip_smooth_mm,
        drop_holes=not keep_holes,
        min_component_area_mm2=min_component_area_mm2,
    )

    zip_path = _write_zip(job_dir, [png_path, svg_path, stl_path], base_name=name)

    return {
        "job_id": job_dir.name,
        "png": f"/files/{job_dir.name}/{name}.png",
        "svg": f"/files/{job_dir.name}/{name}.svg",
        "stl": f"/files/{job_dir.name}/{name}.stl",
        "zip": f"/files/{job_dir.name}/{zip_path.name}",
    }

@app.post("/pipeline/from-prompt")
async def pipeline_from_prompt(
    prompt: str = Form(...),
    name: str = Form("cookie_cutter"),
    width_mm: float = Form(95.0),
    wall_mm: float = Form(1.0),
    total_h_mm: float = Form(28.0),
    flange_h_mm: float = Form(7.226),
    flange_out_mm: float = Form(6.0),
    cleanup_mm: float = Form(0.5),
    tip_smooth_mm: float = Form(0.6),
    keep_holes: bool = Form(False),
    min_component_area_mm2: float = Form(25.0),
    smooth_radius: float = Form(1.0),
):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=402, detail="OPENAI_API_KEY not set. Use /pipeline/from-png for offline mode.")
    if not HAS_OPENAI:
        raise HTTPException(status_code=500, detail="OpenAI image step unavailable.")

    job_dir = _new_job_dir()
    png_path = job_dir / f"{name}.png"
    svg_path = job_dir / f"{name}.svg"
    stl_path = job_dir / f"{name}.stl"

    try:
        generate_outline_png(prompt, str(png_path))
    except OpenAIError as e:
        status = getattr(e, "status_code", 500) or 500
        detail = _openai_detail(e)
        logging.warning(
            "OpenAI image generation failed (status=%s, prompt=%s): %s",
            status,
            prompt.strip()[:200],
            detail,
        )
        raise HTTPException(status_code=status, detail=detail)

    traced = trace_png_to_polygon(
        str(png_path),
        str(svg_path),
        smooth_radius=smooth_radius,
    )
    # Save prompt for reference
    (job_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    _save_polygon(job_dir, traced.polygon)

    polygon_to_cookie_cutter_stl(
        traced.polygon,
        str(stl_path),
        target_width_mm=width_mm,
        wall_mm=wall_mm,
        total_h_mm=total_h_mm,
        flange_h_mm=flange_h_mm,
        flange_out_mm=flange_out_mm,
        cleanup_mm=cleanup_mm,
        tip_smooth_mm=tip_smooth_mm,
        drop_holes=not keep_holes,
        min_component_area_mm2=min_component_area_mm2,
    )

    zip_path = _write_zip(job_dir, [png_path, svg_path, stl_path, job_dir / "prompt.txt"], base_name=name)

    return {
        "job_id": job_dir.name,
        "png": f"/files/{job_dir.name}/{name}.png",
        "svg": f"/files/{job_dir.name}/{name}.svg",
        "stl": f"/files/{job_dir.name}/{name}.stl",
        "zip": f"/files/{job_dir.name}/{zip_path.name}",
    }

@app.post("/outline/from-prompt")
async def outline_from_prompt(
    prompt: str = Form(...),
    name: str = Form("cookie_cutter"),
    smooth_radius: float = Form(1.0),
):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=402, detail="OPENAI_API_KEY not set. Cannot generate prompt image.")
    if not HAS_OPENAI:
        raise HTTPException(status_code=500, detail="OpenAI image step unavailable.")

    job_dir = _new_job_dir()
    png_path = job_dir / f"{name}.png"
    svg_path = job_dir / f"{name}.svg"

    try:
        generate_outline_png(prompt, str(png_path))
    except OpenAIError as e:
        status = getattr(e, "status_code", 500) or 500
        detail = _openai_detail(e)
        logging.warning(
            "OpenAI outline failed (status=%s, prompt=%s): %s",
            status,
            prompt.strip()[:200],
            detail,
        )
        raise HTTPException(status_code=status, detail=detail)

    traced = trace_png_to_polygon(
        str(png_path),
        str(svg_path),
        smooth_radius=smooth_radius,
    )
    (job_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    _save_polygon(job_dir, traced.polygon)

    return {
        "job_id": job_dir.name,
        "png": f"/files/{job_dir.name}/{name}.png",
        "svg": f"/files/{job_dir.name}/{name}.svg",
    }

@app.post("/trace/from-job")
async def trace_from_job(
    job_id: str = Form(...),
    name: str = Form("cookie_cutter"),
    threshold: int = Form(200),
    simplify: float = Form(0.002),
    smooth_radius: float = Form(1.0),
):
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="job_id not found")

    png_path = _find_png(job_dir, name)
    svg_path = job_dir / f"{Path(png_path).stem}.svg"

    traced = trace_png_to_polygon(
        str(png_path),
        str(svg_path),
        threshold=threshold,
        simplify_epsilon=simplify,
        smooth_radius=smooth_radius,
    )
    _save_polygon(job_dir, traced.polygon)

    return {
        "job_id": job_dir.name,
        "png": f"/files/{job_dir.name}/{png_path.name}",
        "svg": f"/files/{job_dir.name}/{svg_path.name}",
    }

@app.post("/stl/from-job")
async def stl_from_job(
    job_id: str = Form(...),
    name: str = Form("cookie_cutter"),
    width_mm: float = Form(95.0),
    wall_mm: float = Form(1.0),
    total_h_mm: float = Form(28.0),
    flange_h_mm: float = Form(7.226),
    flange_out_mm: float = Form(6.0),
    cleanup_mm: float = Form(0.5),
    tip_smooth_mm: float = Form(0.6),
    keep_holes: bool = Form(False),
    min_component_area_mm2: float = Form(25.0),
):
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="job_id not found")

    polygon = _load_polygon(job_dir)
    stl_path = job_dir / f"{name}.stl"

    polygon_to_cookie_cutter_stl(
        polygon,
        str(stl_path),
        target_width_mm=width_mm,
        wall_mm=wall_mm,
        total_h_mm=total_h_mm,
        flange_h_mm=flange_h_mm,
        flange_out_mm=flange_out_mm,
        cleanup_mm=cleanup_mm,
        tip_smooth_mm=tip_smooth_mm,
        drop_holes=not keep_holes,
        min_component_area_mm2=min_component_area_mm2,
    )

    files = [
        stl_path,
        job_dir / f"{name}.png",
        job_dir / f"{name}.svg",
        job_dir / "prompt.txt",
        job_dir / "polygon.json",
    ]
    zip_path = _write_zip(job_dir, files, base_name=name)

    return {
        "job_id": job_id,
        "png": f"/files/{job_id}/{name}.png" if (job_dir / f"{name}.png").exists() else None,
        "svg": f"/files/{job_id}/{name}.svg" if (job_dir / f"{name}.svg").exists() else None,
        "stl": f"/files/{job_id}/{name}.stl",
        "zip": f"/files/{job_id}/{zip_path.name}",
    }

@app.get("/files/{job_id}/{filename}")
def get_file(job_id: str, filename: str):
    path = OUTPUT_DIR / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)
