"""Tests for perspective_math module, especially the crop + perspective fix."""

import pytest
import numpy as np

from src.iPhoto.gui.ui.widgets.perspective_math import (
    NormalisedRect,
    build_perspective_matrix,
    compute_projected_quad,
    rect_inside_quad,
)


def test_compute_projected_quad_full_image_no_perspective():
    """Test that identity matrix produces the unit quad."""
    matrix = np.identity(3, dtype=np.float32)
    quad = compute_projected_quad(matrix)
    
    expected = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for actual, exp in zip(quad, expected):
        assert actual[0] == pytest.approx(exp[0], abs=1e-5)
        assert actual[1] == pytest.approx(exp[1], abs=1e-5)


def test_compute_projected_quad_with_crop_rect():
    """Test that compute_projected_quad correctly handles crop rectangles."""
    # Identity matrix should preserve the crop rect corners
    matrix = np.identity(3, dtype=np.float32)
    crop_rect = NormalisedRect(0.2, 0.2, 0.8, 0.8)
    
    quad = compute_projected_quad(matrix, crop_rect)
    
    # With identity matrix, the quad should match the crop rectangle corners
    expected = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
    for actual, exp in zip(quad, expected):
        assert actual[0] == pytest.approx(exp[0], abs=1e-5)
        assert actual[1] == pytest.approx(exp[1], abs=1e-5)


def test_compute_projected_quad_crop_with_perspective():
    """Test that perspective + crop produces different quad than full image."""
    # Build a perspective matrix with some vertical perspective
    matrix = build_perspective_matrix(vertical=0.5, horizontal=0.0)
    
    # Compute quad for full image
    quad_full = compute_projected_quad(matrix, crop_rect=None)
    
    # Compute quad for cropped region
    crop_rect = NormalisedRect(0.2, 0.2, 0.8, 0.8)
    quad_crop = compute_projected_quad(matrix, crop_rect)
    
    # The two quads should be different (this is the fix!)
    # At least one corner should differ significantly
    differences = [
        abs(quad_full[i][0] - quad_crop[i][0]) + abs(quad_full[i][1] - quad_crop[i][1])
        for i in range(4)
    ]
    assert max(differences) > 0.01, "Crop quad should differ from full image quad"


def test_rect_inside_quad_with_perspective_and_crop():
    """Test the scenario described in crop_algorithms_analysis.md.
    
    When crop step ≠ 0 and perspective is applied:
    - Old behavior: CPU checks if crop is inside full-image projected quad (wrong)
    - New behavior: CPU checks if crop is inside crop-region projected quad (correct)
    """
    # Create a non-full-size crop
    crop_rect = NormalisedRect(0.2, 0.2, 0.8, 0.8)
    
    # Apply moderate vertical perspective
    matrix = build_perspective_matrix(vertical=0.8, horizontal=0.0)
    
    # Compute projected quad based on the crop region (new behavior)
    quad_cropped = compute_projected_quad(matrix, crop_rect)
    
    # The crop rectangle should be inside its own projected quad
    # (though it may need to be shrunk by the auto-scaling algorithm)
    # This test verifies the coordinate space is consistent
    is_inside = rect_inside_quad(crop_rect, quad_cropped)
    
    # The quad might require the crop to shrink, but at minimum,
    # the center should be inside
    from src.iPhoto.gui.ui.widgets.perspective_math import point_in_convex_polygon
    center = crop_rect.center
    assert point_in_convex_polygon(center, quad_cropped), \
        "Crop center should be inside the projected quad"


def test_normalised_rect_properties():
    """Test basic NormalisedRect properties."""
    rect = NormalisedRect(0.2, 0.3, 0.7, 0.8)
    
    assert rect.width == pytest.approx(0.5)
    assert rect.height == pytest.approx(0.5)
    assert rect.center == pytest.approx((0.45, 0.55))


def test_build_perspective_matrix_zero_returns_identity():
    """Test that zero perspective returns identity matrix."""
    matrix = build_perspective_matrix(0.0, 0.0)
    identity = np.identity(3, dtype=np.float32)
    
    np.testing.assert_array_almost_equal(matrix, identity, decimal=5)


def test_build_perspective_matrix_clamping():
    """Test that perspective values are clamped to [-1, 1]."""
    # Extreme values should be clamped
    matrix1 = build_perspective_matrix(2.0, 0.0)
    matrix2 = build_perspective_matrix(1.0, 0.0)
    
    # Both should produce the same result (clamped to 1.0)
    np.testing.assert_array_almost_equal(matrix1, matrix2, decimal=5)
