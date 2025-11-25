"""
Crop session model for state management.

This module manages crop state, perspective transformations, and validation
logic without any direct UI interaction.
"""

from __future__ import annotations

import math

from ..perspective_math import (
    NormalisedRect,
    build_perspective_matrix,
    calculate_min_zoom_to_fit,
    compute_projected_quad,
    point_in_convex_polygon,
    quad_centroid,
    rect_inside_quad,
    unit_quad,
)
from .utils import CropBoxState


class CropSessionModel:
    """Manages crop session data and validation logic."""

    def __init__(self) -> None:
        """Initialize the crop session model."""
        self._crop_state = CropBoxState()
        self._perspective_quad: list[tuple[float, float]] = unit_quad()
        self._baseline_crop_state: tuple[float, float, float, float] | None = None

        # Cached perspective parameters
        self._perspective_vertical: float = 0.0
        self._perspective_horizontal: float = 0.0
        self._straighten_degrees: float = 0.0
        self._rotate_steps: int = 0
        self._flip_horizontal: bool = False

    def get_crop_state(self) -> CropBoxState:
        """Return the current crop state object."""
        return self._crop_state

    def get_perspective_quad(self) -> list[tuple[float, float]]:
        """Return the current perspective quad."""
        return self._perspective_quad

    def create_snapshot(self) -> tuple[float, float, float, float]:
        """Return a tuple describing the current crop rectangle."""
        state = self._crop_state
        return (float(state.cx), float(state.cy), float(state.width), float(state.height))

    def restore_snapshot(self, snapshot: tuple[float, float, float, float]) -> None:
        """Restore the crop rectangle from snapshot."""
        cx, cy, width, height = snapshot
        self._crop_state.cx = cx
        self._crop_state.cy = cy
        self._crop_state.width = width
        self._crop_state.height = height
        self._crop_state.clamp()

    def has_changed(self, snapshot: tuple[float, float, float, float]) -> bool:
        """Return True when the current crop differs from snapshot."""
        current = self.create_snapshot()
        return any(abs(a - b) > 1e-6 for a, b in zip(snapshot, current, strict=True))

    def create_baseline(self) -> None:
        """Cache the current crop state as baseline for perspective interactions."""
        self._baseline_crop_state = self.create_snapshot()

    def clear_baseline(self) -> None:
        """Clear the cached baseline crop."""
        self._baseline_crop_state = None

    def has_baseline(self) -> bool:
        """Return True if a baseline crop state exists."""
        return self._baseline_crop_state is not None

    def update_perspective(
        self,
        vertical: float,
        horizontal: float,
        straighten: float = 0.0,
        rotate_steps: int = 0,
        flip_horizontal: bool = False,
        aspect_ratio: float = 1.0,
    ) -> bool:
        """Update the perspective quad based on parameters.

        This method computes the perspective quad in LOGICAL space (matching the
        shader's coordinate system), then transforms it to TEXTURE space for crop
        validation. This ensures that crop coordinates (stored in texture space)
        are validated correctly against the perspective quad.

        Parameters
        ----------
        vertical:
            Vertical perspective distortion.
        horizontal:
            Horizontal perspective distortion.
        straighten:
            Straighten angle in degrees.
        rotate_steps:
            Number of 90° rotation steps.
        flip_horizontal:
            Whether to flip horizontally.
        aspect_ratio:
            Image aspect ratio (width/height) in LOGICAL space (post-rotation).

        Returns
        -------
        bool:
            True if the perspective quad changed, False otherwise.
        """
        new_vertical = float(vertical)
        new_horizontal = float(horizontal)
        new_straighten = float(straighten)
        new_rotate = int(rotate_steps)
        new_flip = bool(flip_horizontal)

        # Check if anything changed
        if (
            abs(new_vertical - self._perspective_vertical) <= 1e-6
            and abs(new_horizontal - self._perspective_horizontal) <= 1e-6
            and abs(new_straighten - self._straighten_degrees) <= 1e-6
            and new_rotate == self._rotate_steps
            and new_flip is self._flip_horizontal
        ):
            return False

        self._perspective_vertical = new_vertical
        self._perspective_horizontal = new_horizontal
        self._straighten_degrees = new_straighten
        self._rotate_steps = new_rotate
        self._flip_horizontal = new_flip

        # Build perspective matrix in LOGICAL space (matching shader's coordinate system).
        # The shader handles 90° rotation via uRotate90, so we pass rotate_steps=0 here.
        # The aspect_ratio must be the LOGICAL aspect ratio (post-rotation dimensions).
        matrix = build_perspective_matrix(
            new_vertical,
            new_horizontal,
            image_aspect_ratio=aspect_ratio,
            straighten_degrees=new_straighten,
            rotate_steps=0,  # Rotation handled by shader's uRotate90
            flip_horizontal=new_flip,
        )

        # Compute the perspective quad in LOGICAL space
        logical_quad = compute_projected_quad(matrix)

        # Transform the quad from logical space to texture space for crop validation.
        # This ensures crop coordinates (stored in texture space) are validated correctly.
        self._perspective_quad = self._transform_quad_to_texture_space(
            logical_quad,
            new_rotate,
        )

        return True

    def _transform_quad_to_texture_space(
        self,
        quad: list[tuple[float, float]],
        rotate_steps: int,
    ) -> list[tuple[float, float]]:
        """Transform a quad from logical space to texture space.

        This is the inverse of the shader's apply_rotation_90() function.
        When the shader applies rotation to go from logical→physical,
        we need the inverse to go from logical→texture for crop validation.

        Parameters
        ----------
        quad:
            List of (x, y) tuples in logical space.
        rotate_steps:
            Number of 90° rotation steps.

        Returns
        -------
        list[tuple[float, float]]:
            List of (x, y) tuples in texture space.
        """
        steps = rotate_steps % 4
        if steps == 0:
            return quad

        def inverse_rotate_point(logical_x: float, logical_y: float) -> tuple[float, float]:
            """Apply the inverse of the shader's 90° rotation.

            Given a point (logical_x, logical_y) in logical space (post-rotation),
            compute the corresponding point (texture_x, texture_y) in texture space.

            Shader rotation (logical → physical, applied in shader):
              Step 1 (90° CW):  physical = (logical_y, 1 - logical_x)
              Step 2 (180°):    physical = (1 - logical_x, 1 - logical_y)
              Step 3 (270° CW): physical = (1 - logical_y, logical_x)

            Inverse (logical → texture, applied here for crop validation):
              Step 1: texture = (logical_y, 1 - logical_x)
              Step 2: texture = (1 - logical_x, 1 - logical_y)
              Step 3: texture = (1 - logical_y, logical_x)

            Note: The inverse transformation formula is the same as the forward
            transformation because these are 90° rotations applied to normalized
            [0,1] coordinates around the center (0.5, 0.5).
            """
            if steps == 1:
                # Inverse of 90° CW rotation
                return (logical_y, 1.0 - logical_x)
            elif steps == 2:
                # Inverse of 180° rotation
                return (1.0 - logical_x, 1.0 - logical_y)
            else:  # steps == 3
                # Inverse of 270° CW rotation
                return (1.0 - logical_y, logical_x)

        return [inverse_rotate_point(pt[0], pt[1]) for pt in quad]

    def _current_normalised_rect(self) -> NormalisedRect:
        """Return the current crop as a normalised rect."""
        left, top, right, bottom = self._crop_state.bounds_normalised()
        return NormalisedRect(left, top, right, bottom)

    def is_crop_inside_quad(self) -> bool:
        """Check if the crop rectangle is entirely inside the perspective quad."""
        quad = self._perspective_quad or unit_quad()
        return rect_inside_quad(self._current_normalised_rect(), quad)

    def ensure_crop_center_inside_quad(self) -> bool:
        """Reposition the crop center when perspective squeezes the valid quad.

        Returns
        -------
        bool:
            True if the crop center was moved, False otherwise.
        """
        quad = self._perspective_quad or unit_quad()
        center = (float(self._crop_state.cx), float(self._crop_state.cy))
        if point_in_convex_polygon(center, quad):
            return False
        centroid = quad_centroid(quad)
        self._crop_state.cx = max(0.0, min(1.0, centroid[0]))
        self._crop_state.cy = max(0.0, min(1.0, centroid[1]))
        self._crop_state.clamp()
        return True

    def auto_scale_crop_to_quad(self) -> bool:
        """Shrink the crop uniformly so it sits entirely inside the quad.

        Returns
        -------
        bool:
            True if the crop was scaled, False otherwise.
        """
        quad = self._perspective_quad or unit_quad()
        rect = self._current_normalised_rect()
        scale = calculate_min_zoom_to_fit(rect, quad)
        if not math.isfinite(scale) or scale <= 1.0 + 1e-4:
            return False
        self._crop_state.width = max(self._crop_state.min_width, self._crop_state.width / scale)
        self._crop_state.height = max(self._crop_state.min_height, self._crop_state.height / scale)
        self._crop_state.clamp()
        return True

    def apply_baseline_perspective_fit(self) -> bool:
        """Fit the stored baseline crop into the current perspective quad.

        Returns
        -------
        bool:
            True if the crop state changed, False otherwise.
        """
        if self._baseline_crop_state is None:
            return False
        snapshot = self.create_snapshot()
        quad = self._perspective_quad or unit_quad()
        base_cx, base_cy, base_width, base_height = self._baseline_crop_state
        center = (float(base_cx), float(base_cy))
        if not point_in_convex_polygon(center, quad):
            centroid = quad_centroid(quad)
            center = (
                max(0.0, min(1.0, float(centroid[0]))),
                max(0.0, min(1.0, float(centroid[1]))),
            )

        half_w = max(0.0, float(base_width) * 0.5)
        half_h = max(0.0, float(base_height) * 0.5)
        rect = NormalisedRect(
            center[0] - half_w,
            center[1] - half_h,
            center[0] + half_w,
            center[1] + half_h,
        )
        scale = calculate_min_zoom_to_fit(rect, quad)
        if not math.isfinite(scale) or scale < 1.0:
            scale = 1.0

        new_width = max(self._crop_state.min_width, float(base_width) / scale)
        new_height = max(self._crop_state.min_height, float(base_height) / scale)
        self._crop_state.width = min(1.0, new_width)
        self._crop_state.height = min(1.0, new_height)
        self._crop_state.cx = max(0.0, min(1.0, center[0]))
        self._crop_state.cy = max(0.0, min(1.0, center[1]))
        self._crop_state.clamp()
        return self.has_changed(snapshot)

    def ensure_valid_or_revert(
        self,
        snapshot: tuple[float, float, float, float],
        *,
        allow_shrink: bool,
    ) -> bool:
        """Keep the crop within the perspective quad or restore snapshot.

        Parameters
        ----------
        snapshot:
            Snapshot to restore if validation fails.
        allow_shrink:
            If True, allow automatic scaling to fit within quad.

        Returns
        -------
        bool:
            True if the crop is valid or was made valid, False if reverted.
        """
        if self.is_crop_inside_quad():
            return True
        if allow_shrink and self.auto_scale_crop_to_quad():
            return True
        self.restore_snapshot(snapshot)
        return False
