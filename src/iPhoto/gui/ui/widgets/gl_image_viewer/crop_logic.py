"""
Crop calculation and view locking logic for GL image viewer.

This module handles the computation of crop rectangles in pixel space and
manages the auto-lock behavior for crop view framing.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF


def has_valid_crop(crop_w: float, crop_h: float) -> bool:
    """Return ``True`` when the adjustments describe a cropped image.
    
    Parameters
    ----------
    crop_w:
        Crop width as a fraction [0, 1]
    crop_h:
        Crop height as a fraction [0, 1]
        
    Returns
    -------
    bool
        True if the crop dimensions indicate an actual crop (not full image)
    """
    epsilon = 1e-3
    return (crop_w < 1.0 - epsilon or crop_h < 1.0 - epsilon) and crop_w > 0.0 and crop_h > 0.0


def compute_crop_rect_pixels(
    crop_cx: float,
    crop_cy: float,
    crop_w: float,
    crop_h: float,
    tex_w: int,
    tex_h: int,
) -> QRectF | None:
    """Return the crop rectangle expressed in texture pixels.
    
    Converts normalized crop coordinates (0-1 range) into pixel coordinates
    for the given texture dimensions.
    
    Parameters
    ----------
    crop_cx:
        Crop center X coordinate (normalized, 0-1)
    crop_cy:
        Crop center Y coordinate (normalized, 0-1)
    crop_w:
        Crop width (normalized, 0-1)
    crop_h:
        Crop height (normalized, 0-1)
    tex_w:
        Texture width in pixels
    tex_h:
        Texture height in pixels
        
    Returns
    -------
    QRectF | None
        Rectangle in pixel coordinates, or None if crop is invalid or covers entire image
    """
    if tex_w <= 0 or tex_h <= 0:
        return None
    
    if not has_valid_crop(crop_w, crop_h):
        return None

    tex_w_f = float(tex_w)
    tex_h_f = float(tex_h)
    width_px = max(1.0, min(tex_w_f, crop_w * tex_w_f))
    height_px = max(1.0, min(tex_h_f, crop_h * tex_h_f))

    center_x = max(0.0, min(tex_w_f, crop_cx * tex_w_f))
    center_y = max(0.0, min(tex_h_f, crop_cy * tex_h_f))

    half_w = width_px * 0.5
    half_h = height_px * 0.5

    left = max(0.0, center_x - half_w)
    top = max(0.0, center_y - half_h)
    right = min(tex_w_f, center_x + half_w)
    bottom = min(tex_h_f, center_y + half_h)

    rect_width = max(1.0, right - left)
    rect_height = max(1.0, bottom - top)
    epsilon = 1e-6
    if rect_width >= tex_w_f - epsilon and rect_height >= tex_h_f - epsilon:
        return None
    return QRectF(left, top, rect_width, rect_height)
