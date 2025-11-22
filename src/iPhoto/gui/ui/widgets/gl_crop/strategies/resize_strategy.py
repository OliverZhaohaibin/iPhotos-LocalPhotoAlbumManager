"""
Resize strategy for crop box edge/corner dragging.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF

from ...gl_image_viewer.geometry import logical_crop_to_texture, texture_crop_to_logical
from ..model import CropSessionModel
from ..utils import CropHandle
from .abstract import InteractionStrategy


class ResizeStrategy(InteractionStrategy):
    """Strategy for resizing crop box via edge/corner dragging."""

    def __init__(
        self,
        *,
        handle: CropHandle,
        model: CropSessionModel,
        texture_size_provider: Callable[[], tuple[int, int]],
        get_effective_scale: Callable[[], float],
        get_dpr: Callable[[], float],
        on_crop_changed: Callable[[], None],
        apply_edge_push_zoom: Callable[[QPointF], None],
    ) -> None:
        """Initialize resize strategy.

        Parameters
        ----------
        handle:
            The crop handle being dragged.
        model:
            Crop session model.
        texture_size_provider:
            Callable that returns (width, height) of the current texture.
        get_effective_scale:
            Callable that returns the current effective scale.
        get_dpr:
            Callable that returns the device pixel ratio.
        on_crop_changed:
            Callback when crop values change.
        apply_edge_push_zoom:
            Callback to apply edge-push auto-zoom.
        """
        self._handle = handle
        self._model = model
        self._texture_size_provider = texture_size_provider
        self._get_effective_scale = get_effective_scale
        self._get_dpr = get_dpr
        self._on_crop_changed = on_crop_changed
        self._apply_edge_push_zoom = apply_edge_push_zoom

    def on_drag(self, delta_view: QPointF) -> None:
        """Handle resize drag movement."""
        tex_w, tex_h = self._texture_size_provider()
        if tex_w <= 0 or tex_h <= 0:
            return

        view_scale = self._get_effective_scale()
        if view_scale <= 1e-6:
            return

        snapshot = self._model.create_snapshot()
        dpr = self._get_dpr()
        crop_state = self._model.get_crop_state()
        rotate_steps = self._model.get_rotate_steps()

        # Get current crop in appropriate coordinate system
        cx, cy, width, height = crop_state.cx, crop_state.cy, crop_state.width, crop_state.height
        
        # If rotation is applied, work in logical space
        if rotate_steps != 0:
            cx, cy, width, height = texture_crop_to_logical((cx, cy, width, height), rotate_steps)
        
        # Convert delta from view to normalized logical space
        delta_norm_x = float(delta_view.x()) * dpr / (view_scale * tex_w)
        delta_norm_y = float(delta_view.y()) * dpr / (view_scale * tex_h)
        
        # Calculate crop bounds in logical space
        half_w = width * 0.5
        half_h = height * 0.5
        left = cx - half_w
        right = cx + half_w
        top = cy - half_h
        bottom = cy + half_h
        
        # Minimum dimensions
        min_width = max(crop_state.min_width, 1.0 / tex_w)
        min_height = max(crop_state.min_height, 1.0 / tex_h)
        
        # Apply delta to appropriate edges based on handle
        texture_handle = self._handle
        
        if texture_handle in (CropHandle.LEFT, CropHandle.TOP_LEFT, CropHandle.BOTTOM_LEFT):
            new_left = left + delta_norm_x
            new_left = min(new_left, right - min_width)
            left = new_left
            
        if texture_handle in (CropHandle.RIGHT, CropHandle.TOP_RIGHT, CropHandle.BOTTOM_RIGHT):
            new_right = right + delta_norm_x
            new_right = max(new_right, left + min_width)
            right = new_right
            
        if texture_handle in (CropHandle.TOP, CropHandle.TOP_LEFT, CropHandle.TOP_RIGHT):
            new_top = top + delta_norm_y
            new_top = min(new_top, bottom - min_height)
            top = new_top
            
        if texture_handle in (CropHandle.BOTTOM, CropHandle.BOTTOM_LEFT, CropHandle.BOTTOM_RIGHT):
            new_bottom = bottom + delta_norm_y
            new_bottom = max(new_bottom, top + min_height)
            bottom = new_bottom
        
        # Calculate new center and dimensions in logical space
        new_cx = (left + right) * 0.5
        new_cy = (top + bottom) * 0.5
        new_width = right - left
        new_height = bottom - top
        
        # Convert back to texture space if rotation is applied
        if rotate_steps != 0:
            new_cx, new_cy, new_width, new_height = logical_crop_to_texture(
                (new_cx, new_cy, new_width, new_height), rotate_steps
            )
        
        # Update crop state in texture space
        crop_state.cx = new_cx
        crop_state.cy = new_cy
        crop_state.width = new_width
        crop_state.height = new_height
        crop_state.clamp()

        if not self._model.ensure_valid_or_revert(snapshot, allow_shrink=False):
            return
        self._on_crop_changed()
        self._apply_edge_push_zoom(delta_view)

    def on_end(self) -> None:
        """Handle end of resize interaction."""
        # No special cleanup needed
