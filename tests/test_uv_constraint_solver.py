"""Tests for UV-space constraint solver in perspective_math module."""

import numpy as np
import pytest

from src.iPhoto.gui.ui.widgets.perspective_math import (
    NormalisedRect,
    build_perspective_matrix,
    calculate_texture_safety_padding,
    constrain_rect_to_uv_bounds,
    inverse_project_point,
    validate_crop_corners_in_uv_space,
)


def test_inverse_project_point_identity():
    """Test that inverse projection works correctly with identity matrix."""
    matrix = np.identity(3, dtype=np.float32)
    
    # Test corner points - should map to themselves with identity matrix
    assert inverse_project_point((0.0, 0.0), matrix) == pytest.approx((0.0, 0.0), abs=1e-5)
    assert inverse_project_point((1.0, 1.0), matrix) == pytest.approx((1.0, 1.0), abs=1e-5)
    assert inverse_project_point((0.5, 0.5), matrix) == pytest.approx((0.5, 0.5), abs=1e-5)


def test_inverse_project_point_with_perspective():
    """Test inverse projection with actual perspective transformation."""
    # Small perspective angle - should still map points reasonably
    matrix = build_perspective_matrix(0.2, 0.1)
    
    # Center point should be relatively stable
    u, v = inverse_project_point((0.5, 0.5), matrix)
    assert 0.0 <= u <= 1.0
    assert 0.0 <= v <= 1.0
    assert abs(u - 0.5) < 0.2  # Should be close to center
    assert abs(v - 0.5) < 0.2


def test_calculate_texture_safety_padding():
    """Test safety padding calculation for different texture sizes."""
    # 1000x1000 texture with 3 pixel padding
    epsilon_u, epsilon_v = calculate_texture_safety_padding(1000, 1000, 3)
    assert epsilon_u == pytest.approx(0.003)
    assert epsilon_v == pytest.approx(0.003)
    
    # 2000x1000 texture (rectangular)
    epsilon_u, epsilon_v = calculate_texture_safety_padding(2000, 1000, 3)
    assert epsilon_u == pytest.approx(0.0015)
    assert epsilon_v == pytest.approx(0.003)
    
    # With 2 pixel padding
    epsilon_u, epsilon_v = calculate_texture_safety_padding(1000, 1000, 2)
    assert epsilon_u == pytest.approx(0.002)
    assert epsilon_v == pytest.approx(0.002)


def test_calculate_texture_safety_padding_invalid_size():
    """Test safety padding with invalid texture size."""
    epsilon_u, epsilon_v = calculate_texture_safety_padding(0, 0, 3)
    assert epsilon_u == 0.0
    assert epsilon_v == 0.0


def test_validate_crop_corners_no_perspective():
    """Test crop corner validation with no perspective (identity matrix)."""
    matrix = np.identity(3, dtype=np.float32)
    rect = NormalisedRect(left=0.1, top=0.1, right=0.9, bottom=0.9)
    texture_size = (1000, 1000)
    
    is_valid, uv_corners = validate_crop_corners_in_uv_space(
        rect, matrix, texture_size, padding_pixels=3
    )
    
    # Should be valid - well within bounds
    assert is_valid is True
    assert len(uv_corners) == 4
    
    # Corners should be close to the rect corners
    assert uv_corners[0] == pytest.approx((0.1, 0.1), abs=1e-5)
    assert uv_corners[1] == pytest.approx((0.9, 0.1), abs=1e-5)
    assert uv_corners[2] == pytest.approx((0.9, 0.9), abs=1e-5)
    assert uv_corners[3] == pytest.approx((0.1, 0.9), abs=1e-5)


def test_validate_crop_corners_at_edge():
    """Test crop corner validation when rect is at the very edge."""
    matrix = np.identity(3, dtype=np.float32)
    # Rectangle that goes all the way to the edges
    rect = NormalisedRect(left=0.0, top=0.0, right=1.0, bottom=1.0)
    texture_size = (1000, 1000)
    
    is_valid, _ = validate_crop_corners_in_uv_space(
        rect, matrix, texture_size, padding_pixels=3
    )
    
    # Should be invalid - no safety padding
    assert is_valid is False


def test_validate_crop_corners_with_safe_margin():
    """Test crop corner validation with appropriate safety margin."""
    matrix = np.identity(3, dtype=np.float32)
    texture_size = (1000, 1000)
    
    # Calculate the epsilon for 3 pixels
    epsilon = 3.0 / 1000.0  # 0.003
    
    # Rectangle with exactly the safety margin
    rect = NormalisedRect(
        left=epsilon, top=epsilon, right=1.0 - epsilon, bottom=1.0 - epsilon
    )
    
    is_valid, _ = validate_crop_corners_in_uv_space(
        rect, matrix, texture_size, padding_pixels=3
    )
    
    # Should be valid now
    assert is_valid is True


def test_validate_crop_corners_with_perspective():
    """Test crop corner validation with perspective transformation."""
    # Moderate perspective
    matrix = build_perspective_matrix(0.5, 0.3)
    rect = NormalisedRect(left=0.1, top=0.1, right=0.9, bottom=0.9)
    texture_size = (1000, 1000)
    
    is_valid, uv_corners = validate_crop_corners_in_uv_space(
        rect, matrix, texture_size, padding_pixels=3
    )
    
    # Should return 4 corners
    assert len(uv_corners) == 4
    
    # All corners should be in [0, 1] range (though might not pass safety check)
    for u, v in uv_corners:
        assert -0.5 <= u <= 1.5  # Allow some perspective distortion
        assert -0.5 <= v <= 1.5


def test_constrain_rect_to_uv_bounds_no_constraint_needed():
    """Test constraint solver when no constraint is needed."""
    matrix = np.identity(3, dtype=np.float32)
    rect = NormalisedRect(left=0.1, top=0.1, right=0.9, bottom=0.9)
    texture_size = (1000, 1000)
    
    constrained = constrain_rect_to_uv_bounds(
        rect, matrix, texture_size, padding_pixels=3, max_iterations=10
    )
    
    # Should be unchanged - already valid
    assert constrained.left == pytest.approx(rect.left)
    assert constrained.top == pytest.approx(rect.top)
    assert constrained.right == pytest.approx(rect.right)
    assert constrained.bottom == pytest.approx(rect.bottom)


def test_constrain_rect_to_uv_bounds_shrinks_invalid_rect():
    """Test that constraint solver shrinks invalid rectangles."""
    matrix = np.identity(3, dtype=np.float32)
    # Rectangle that extends to edges (invalid)
    rect = NormalisedRect(left=0.0, top=0.0, right=1.0, bottom=1.0)
    texture_size = (1000, 1000)
    
    constrained = constrain_rect_to_uv_bounds(
        rect, matrix, texture_size, padding_pixels=3, max_iterations=10
    )
    
    # Should be smaller than original
    assert constrained.width < rect.width
    assert constrained.height < rect.height
    
    # Center should be preserved
    cx_orig, cy_orig = rect.center
    cx_new, cy_new = constrained.center
    assert cx_new == pytest.approx(cx_orig, abs=1e-5)
    assert cy_new == pytest.approx(cy_orig, abs=1e-5)


def test_constrain_rect_to_uv_bounds_with_perspective():
    """Test constraint solver with perspective transformation."""
    # Strong perspective
    matrix = build_perspective_matrix(0.8, 0.6)
    # Large rectangle that likely violates UV bounds
    rect = NormalisedRect(left=0.05, top=0.05, right=0.95, bottom=0.95)
    texture_size = (1000, 1000)
    
    constrained = constrain_rect_to_uv_bounds(
        rect, matrix, texture_size, padding_pixels=3, max_iterations=10
    )
    
    # Should produce a valid, constrained rectangle
    is_valid, _ = validate_crop_corners_in_uv_space(
        constrained, matrix, texture_size, padding_pixels=3
    )
    
    # Result should be valid
    assert is_valid is True
    
    # Should be smaller than original
    assert constrained.width <= rect.width
    assert constrained.height <= rect.height


def test_constrain_rect_convergence():
    """Test that the iterative solver converges within reasonable iterations."""
    matrix = build_perspective_matrix(0.9, 0.9)  # Very strong perspective
    rect = NormalisedRect(left=0.0, top=0.0, right=1.0, bottom=1.0)
    texture_size = (1000, 1000)
    
    # Should converge with default iterations
    constrained = constrain_rect_to_uv_bounds(
        rect, matrix, texture_size, padding_pixels=3, max_iterations=10
    )
    
    # Verify the result is valid
    is_valid, _ = validate_crop_corners_in_uv_space(
        constrained, matrix, texture_size, padding_pixels=3
    )
    
    assert is_valid is True


def test_constrain_rect_preserves_aspect_ratio():
    """Test that constraint solver preserves aspect ratio during shrinking."""
    matrix = np.identity(3, dtype=np.float32)
    # Rectangle with 2:1 aspect ratio
    rect = NormalisedRect(left=0.0, top=0.25, right=1.0, bottom=0.75)
    texture_size = (1000, 1000)
    
    constrained = constrain_rect_to_uv_bounds(
        rect, matrix, texture_size, padding_pixels=3, max_iterations=10
    )
    
    # Calculate aspect ratios
    original_aspect = rect.width / max(rect.height, 1e-9)
    constrained_aspect = constrained.width / max(constrained.height, 1e-9)
    
    # Aspect ratio should be preserved (within tolerance)
    assert constrained_aspect == pytest.approx(original_aspect, rel=1e-3)


def test_extreme_perspective_angles():
    """Test constraint solver at maximum perspective angles."""
    # Maximum perspective (±1.0)
    matrix = build_perspective_matrix(1.0, -1.0)
    rect = NormalisedRect(left=0.2, top=0.2, right=0.8, bottom=0.8)
    texture_size = (2000, 2000)  # High resolution
    
    constrained = constrain_rect_to_uv_bounds(
        rect, matrix, texture_size, padding_pixels=3, max_iterations=15
    )
    
    # Should produce a valid rectangle even at extreme angles
    is_valid, _ = validate_crop_corners_in_uv_space(
        constrained, matrix, texture_size, padding_pixels=3
    )
    
    assert is_valid is True
    
    # Should be significantly smaller than original due to extreme distortion
    assert constrained.width < rect.width
    assert constrained.height < rect.height
