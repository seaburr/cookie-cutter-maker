"""
image_extractor.py
~~~~~~~~~~~~~~~~~~
Classifies an input image and extracts a binary foreground mask using the
best available strategy — no cloud services required.

Three paths:
  "binary"     – image is already a line-art / threshold-able outline.
                 Use simple luminance threshold (existing behaviour).
  "simple_bg"  – image has a roughly uniform background (e.g. product shot
                 on white, logo on solid colour). Use LAB colour-distance
                 from sampled corners.
  "complex"    – photographic / textured background.  Tries rembg (local
                 neural net, no API key) if installed, otherwise falls back
                 to Felzenszwalb graph-cut segmentation with a quality
                 warning.

All paths return a boolean NumPy array (True = foreground) of the same
shape as the input image, ready for skimage.measure.find_contours.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

import numpy as np
from PIL import Image
from skimage import measure, morphology
from skimage.color import rgb2lab
from skimage.segmentation import felzenszwalb

logger = logging.getLogger(__name__)

_rembg_enabled_raw = os.environ.get("REMBG_ENABLED", "true").strip().lower()
REMBG_ENABLED: bool = _rembg_enabled_raw not in ("false", "0", "no")
if not REMBG_ENABLED:
    logger.info("rembg is disabled via REMBG_ENABLED environment variable.")

# Pre-load the U2Net session once at startup so the model is not reloaded from
# disk on every request.  rembg.remove() creates a fresh session (and reloads
# the ~170 MB ONNX model) on each call when no session is supplied — this is a
# documented bottleneck acknowledged in the rembg README.
_rembg_session = None
if REMBG_ENABLED:
    try:
        from rembg import new_session as _rembg_new_session
        _rembg_session = _rembg_new_session("u2net")
        logger.info("rembg U2Net session initialised and model loaded into memory.")
    except Exception as _e:
        logger.warning("rembg session initialisation failed: %s", _e)

ImageMode = Literal["binary", "simple_bg", "complex"]

# ──────────────────────────────────────────────────────────────────────────────
# Classification
# ──────────────────────────────────────────────────────────────────────────────

def classify_image(img: Image.Image) -> ImageMode:
    """Analyse a PIL image and return the recommended extraction mode."""
    gray = np.array(img.convert("L"))
    rgb  = np.array(img.convert("RGB"))

    # 1. Bimodal / binary-outline check
    #    If most pixels are near 0 (dark) or 255 (light) the image is already
    #    a rendered outline — use the existing threshold path.
    hist, _ = np.histogram(gray.ravel(), bins=256, range=(0, 256))
    total   = gray.size
    low_pct  = hist[:50].sum()  / total   # very dark
    high_pct = hist[210:].sum() / total   # very light
    mid_pct  = 1.0 - low_pct - high_pct   # mid-tones

    if mid_pct < 0.12:
        logger.info(
            "Image classified as BINARY OUTLINE — %.1f%% mid-tone pixels "
            "(threshold: <12%%). Using luminance threshold extraction.",
            mid_pct * 100,
        )
        return "binary"

    # 2. Uniform-background check
    #    Sample the four corners (5 % of each side).  If their pixel values
    #    are consistent the background is uniform enough for colour-distance
    #    extraction.
    h, w    = gray.shape
    margin  = max(10, int(min(h, w) * 0.05))
    corners = np.vstack([
        gray[:margin,  :margin ].ravel(),
        gray[:margin,  -margin:].ravel(),
        gray[-margin:, :margin ].ravel(),
        gray[-margin:, -margin:].ravel(),
    ])
    corner_std = float(np.std(corners))

    if corner_std < 28:
        logger.info(
            "Image classified as UNIFORM BACKGROUND — corner pixel std=%.1f "
            "(threshold: <28). Using LAB colour-distance extraction.",
            corner_std,
        )
        return "simple_bg"

    logger.info(
        "Image classified as COMPLEX / PHOTOGRAPHIC — corner pixel std=%.1f, "
        "%.1f%% mid-tone pixels. Extraction method: %s.",
        corner_std,
        mid_pct * 100,
        "rembg (U2Net)" if REMBG_ENABLED else "graph-cut (rembg disabled)",
    )
    return "complex"


# ──────────────────────────────────────────────────────────────────────────────
# Mask extractors — each returns a bool array (True = foreground)
# ──────────────────────────────────────────────────────────────────────────────

def extract_mask_binary(gray: np.ndarray, threshold: int = 200) -> np.ndarray:
    """Existing behaviour: simple luminance threshold."""
    return gray < threshold


def extract_mask_simple_bg(
    rgb: np.ndarray,
    delta_e_threshold: float = 28.0,
    close_radius: int = 5,
    open_radius: int  = 2,
    min_object_px: int = 300,
    fill_hole_px:  int = 2000,
) -> np.ndarray:
    """
    Foreground extraction for images with a roughly uniform background.

    1.  Sample corner pixels → estimate background colour in LAB space.
    2.  Compute per-pixel ΔE (Euclidean distance in LAB).
    3.  Threshold → raw mask.
    4.  Morphological cleanup.
    """
    h, w   = rgb.shape[:2]
    margin = max(10, int(min(h, w) * 0.05))

    corner_pixels = np.vstack([
        rgb[:margin,  :margin ].reshape(-1, 3),
        rgb[:margin,  -margin:].reshape(-1, 3),
        rgb[-margin:, :margin ].reshape(-1, 3),
        rgb[-margin:, -margin:].reshape(-1, 3),
    ])
    # Median is robust to foreground objects that touch the corner edge
    bg_rgb = np.median(corner_pixels, axis=0).reshape(1, 1, 3).astype(np.float32) / 255.0

    lab_img = rgb2lab(rgb.astype(np.float32) / 255.0)
    bg_lab  = rgb2lab(bg_rgb)[0, 0]

    delta_e = np.sqrt(np.sum((lab_img - bg_lab) ** 2, axis=2))
    mask    = delta_e > delta_e_threshold

    # Morphological cleanup
    if close_radius > 0:
        mask = morphology.closing(mask, morphology.disk(close_radius))
    if open_radius > 0:
        mask = morphology.opening(mask, morphology.disk(open_radius))
    mask = morphology.remove_small_objects(mask, max_size=min_object_px)
    mask = morphology.remove_small_holes(mask, max_size=fill_hole_px)

    return mask


def extract_mask_complex(
    rgb: np.ndarray,
    *,
    scale: float  = 100.0,
    sigma: float  = 0.8,
    min_size: int = 200,
) -> tuple[np.ndarray, str]:
    """
    Foreground extraction for complex / photographic images.

    Tries rembg (local U2Net — no cloud, no API key) first.
    Falls back to Felzenszwalb graph-cut segmentation if rembg is not
    installed, returning a quality warning alongside the mask.

    Returns (mask, warning_message).  warning_message is empty string on
    success.
    """
    # ── Attempt rembg ──────────────────────────────────────────────────────
    if not REMBG_ENABLED:
        logger.info(
            "rembg is disabled (REMBG_ENABLED=false) — skipping to graph-cut fallback."
        )
        warning = (
            "rembg background removal is disabled. "
            "Falling back to graph-cut segmentation which may be less accurate "
            "for complex or photographic backgrounds."
        )
    else:
        if _rembg_session is not None:
            try:
                from rembg import remove as _rembg_remove  # type: ignore
                from PIL import Image as _PILImage

                pil_in  = _PILImage.fromarray(rgb)
                pil_out = _rembg_remove(pil_in, session=_rembg_session)  # reuses in-memory model
                alpha   = np.array(pil_out.split()[-1])     # A channel
                mask    = alpha > 10                         # near-transparent = background
                mask    = morphology.remove_small_objects(mask, max_size=300)
                mask    = morphology.remove_small_holes(mask, max_size=2000)
                logger.info("Extracting foreground with REMBG (cached U2Net session).")
                return mask, ""
            except ImportError:
                pass  # rembg not installed — continue to fallback

        # ── Felzenszwalb fallback ──────────────────────────────────────────────
        logger.warning(
            "rembg is not installed — falling back to GRAPH-CUT (Felzenszwalb) "
            "segmentation. Quality may be reduced for complex backgrounds. "
            "Install rembg[cpu] for best results: pip install 'rembg[cpu]'"
        )
        warning = (
            "Complex background detected. For best results install the 'rembg' "
            "package (pip install rembg) — it runs locally with no API key. "
            "Falling back to graph-cut segmentation which may be less accurate."
        )

    segments = felzenszwalb(rgb, scale=scale, sigma=sigma, min_size=min_size)

    # The foreground is assumed to be centred: take the segment that covers
    # the most of the central 50 % of the image.
    cy, cx = rgb.shape[0] // 2, rgb.shape[1] // 2
    ch, cw = rgb.shape[0] // 4, rgb.shape[1] // 4
    centre  = segments[cy - ch : cy + ch, cx - cw : cx + cw]
    labels, counts = np.unique(centre, return_counts=True)
    fg_label = labels[np.argmax(counts)]

    mask = segments == fg_label
    mask = morphology.closing(mask, morphology.disk(5))
    mask = morphology.remove_small_objects(mask, max_size=300)
    mask = morphology.remove_small_holes(mask, max_size=2000)

    return mask, warning


# ──────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ──────────────────────────────────────────────────────────────────────────────

def extract_foreground_mask(
    img: Image.Image,
    mode: ImageMode | Literal["auto"] = "auto",
    threshold: int = 200,
    delta_e_threshold: float = 28.0,
) -> tuple[np.ndarray, ImageMode, str]:
    """
    Extract a boolean foreground mask from *img*.

    Parameters
    ----------
    img               PIL image (any mode).
    mode              "auto" (default) classifies the image and picks the
                      best strategy; or pass "binary" / "simple_bg" /
                      "complex" to force a specific path.
    threshold         Luminance cut-off used in "binary" mode.
    delta_e_threshold ΔE cut-off used in "simple_bg" mode.

    Returns
    -------
    mask              bool ndarray, True = foreground.
    detected_mode     The mode that was actually used.
    warning           Non-empty string if quality may be reduced.
    """
    requested = mode
    if mode == "auto":
        mode = classify_image(img)
    else:
        logger.info("Extraction mode forced to '%s' (not auto-detected).", mode)

    gray = np.array(img.convert("L"))
    rgb  = np.array(img.convert("RGB"))
    warning = ""

    if mode == "binary":
        logger.info("Running extraction: BINARY threshold (luminance < %d).", threshold)
        mask = extract_mask_binary(gray, threshold=threshold)
    elif mode == "simple_bg":
        logger.info("Running extraction: UNIFORM BACKGROUND colour-distance (ΔE threshold=%.1f).", delta_e_threshold)
        mask = extract_mask_simple_bg(rgb, delta_e_threshold=delta_e_threshold)
    else:  # complex
        logger.info("Running extraction: COMPLEX — attempting rembg, with graph-cut fallback.")
        mask, warning = extract_mask_complex(rgb)

    return mask.astype(float), mode, warning
