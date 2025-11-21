"""
Unit tests for gl_image_viewer geometry transformations.

Tests the coordinate transformation logic between texture space and logical space,
particularly for rotation operations.
"""

import sys
from pathlib import Path

import pytest

# Import geometry module directly without going through package __init__
geometry_path = (
    Path(__file__).parent.parent
    / "src"
    / "iPhoto"
    / "gui"
    / "ui"
    / "widgets"
    / "gl_image_viewer"
)
sys.path.insert(0, str(geometry_path))

import geometry  # noqa: E402

clamp_unit = geometry.clamp_unit
get_rotate_steps = geometry.get_rotate_steps
logical_crop_from_texture = geometry.logical_crop_from_texture
logical_crop_mapping_from_texture = geometry.logical_crop_mapping_from_texture
logical_crop_to_texture = geometry.logical_crop_to_texture
normalised_crop_from_mapping = geometry.normalised_crop_from_mapping
texture_crop_to_logical = geometry.texture_crop_to_logical


class TestClampUnit:
    """Test the clamp_unit function."""

    def test_clamp_negative(self):
        """Values below 0 should be clamped to 0."""
        assert clamp_unit(-0.5) == 0.0

    def test_clamp_above_one(self):
        """Values above 1 should be clamped to 1."""
        assert clamp_unit(1.5) == 1.0

    def test_clamp_within_range(self):
        """Values within [0, 1] should remain unchanged."""
        assert clamp_unit(0.5) == 0.5
        assert clamp_unit(0.0) == 0.0
        assert clamp_unit(1.0) == 1.0


class TestGetRotateSteps:
    """Test rotation step extraction."""

    def test_no_rotation(self):
        """Default or zero rotation should return 0."""
        assert get_rotate_steps({}) == 0
        assert get_rotate_steps({"Crop_Rotate90": 0.0}) == 0

    def test_rotation_steps(self):
        """Various rotation steps should be normalized to 0-3."""
        assert get_rotate_steps({"Crop_Rotate90": 1.0}) == 1
        assert get_rotate_steps({"Crop_Rotate90": 2.0}) == 2
        assert get_rotate_steps({"Crop_Rotate90": 3.0}) == 3
        assert get_rotate_steps({"Crop_Rotate90": 4.0}) == 0  # wraps around
        assert get_rotate_steps({"Crop_Rotate90": 5.0}) == 1


class TestNormalisedCropFromMapping:
    """Test extraction of normalized crop values."""

    def test_default_values(self):
        """Empty mapping should return default centered full crop."""
        cx, cy, w, h = normalised_crop_from_mapping({})
        assert cx == 0.5
        assert cy == 0.5
        assert w == 1.0
        assert h == 1.0

    def test_custom_values(self):
        """Custom crop values should be extracted and clamped."""
        values = {
            "Crop_CX": 0.3,
            "Crop_CY": 0.7,
            "Crop_W": 0.5,
            "Crop_H": 0.6,
        }
        cx, cy, w, h = normalised_crop_from_mapping(values)
        assert cx == 0.3
        assert cy == 0.7
        assert w == 0.5
        assert h == 0.6

    def test_out_of_range_clamping(self):
        """Out-of-range values should be clamped."""
        values = {
            "Crop_CX": -0.1,
            "Crop_CY": 1.5,
            "Crop_W": 2.0,
            "Crop_H": -0.5,
        }
        cx, cy, w, h = normalised_crop_from_mapping(values)
        assert cx == 0.0
        assert cy == 1.0
        assert w == 1.0
        assert h == 0.0


class TestTextureCropToLogical:
    """Test texture-to-logical crop coordinate transformation."""

    def test_no_rotation(self):
        """Zero rotation should preserve coordinates."""
        crop = (0.3, 0.7, 0.5, 0.6)
        result = texture_crop_to_logical(crop, 0)
        assert result == crop

    def test_90_degree_rotation(self):
        """90° CW rotation should transform coordinates correctly."""
        crop = (0.3, 0.7, 0.5, 0.6)
        result = texture_crop_to_logical(crop, 1)
        # Step 1: (x', y') = (1-y, x) and swap w/h
        expected_x = 1.0 - 0.7  # 0.3
        expected_y = 0.3
        expected_w = 0.6  # height becomes width
        expected_h = 0.5  # width becomes height
        assert result[0] == pytest.approx(expected_x)
        assert result[1] == pytest.approx(expected_y)
        assert result[2] == pytest.approx(expected_w)
        assert result[3] == pytest.approx(expected_h)

    def test_180_degree_rotation(self):
        """180° rotation should invert both coordinates."""
        crop = (0.3, 0.7, 0.5, 0.6)
        result = texture_crop_to_logical(crop, 2)
        expected = (1.0 - 0.3, 1.0 - 0.7, 0.5, 0.6)
        assert result[0] == pytest.approx(expected[0])
        assert result[1] == pytest.approx(expected[1])
        assert result[2] == pytest.approx(expected[2])
        assert result[3] == pytest.approx(expected[3])

    def test_270_degree_rotation(self):
        """270° CW (90° CCW) rotation should transform correctly."""
        crop = (0.3, 0.7, 0.5, 0.6)
        result = texture_crop_to_logical(crop, 3)
        # Step 3: (x', y') = (y, 1-x) and swap w/h
        expected_x = 0.7
        expected_y = 1.0 - 0.3  # 0.7
        expected_w = 0.6
        expected_h = 0.5
        assert result[0] == pytest.approx(expected_x)
        assert result[1] == pytest.approx(expected_y)
        assert result[2] == pytest.approx(expected_w)
        assert result[3] == pytest.approx(expected_h)


class TestLogicalCropToTexture:
    """Test logical-to-texture crop coordinate transformation (inverse)."""

    def test_no_rotation_inverse(self):
        """Zero rotation should preserve coordinates."""
        crop = (0.3, 0.7, 0.5, 0.6)
        result = logical_crop_to_texture(crop, 0)
        assert result == crop

    def test_rotation_inverse_property(self):
        """Converting texture -> logical -> texture should preserve original."""
        original = (0.3, 0.7, 0.5, 0.6)
        
        for rotate_steps in range(4):
            logical = texture_crop_to_logical(original, rotate_steps)
            back_to_texture = logical_crop_to_texture(logical, rotate_steps)
            
            assert back_to_texture[0] == pytest.approx(original[0], abs=1e-6)
            assert back_to_texture[1] == pytest.approx(original[1], abs=1e-6)
            assert back_to_texture[2] == pytest.approx(original[2], abs=1e-6)
            assert back_to_texture[3] == pytest.approx(original[3], abs=1e-6)


class TestLogicalCropFromTexture:
    """Test complete transformation from texture mapping to logical coordinates."""

    def test_with_rotation(self):
        """Should extract and transform crop values correctly."""
        values = {
            "Crop_CX": 0.3,
            "Crop_CY": 0.7,
            "Crop_W": 0.5,
            "Crop_H": 0.6,
            "Crop_Rotate90": 1.0,  # 90° rotation
        }
        cx, cy, w, h = logical_crop_from_texture(values)
        
        # Should be same as texture_crop_to_logical((0.3, 0.7, 0.5, 0.6), 1)
        expected_x = 1.0 - 0.7
        expected_y = 0.3
        expected_w = 0.6
        expected_h = 0.5
        
        assert cx == pytest.approx(expected_x)
        assert cy == pytest.approx(expected_y)
        assert w == pytest.approx(expected_w)
        assert h == pytest.approx(expected_h)


class TestLogicalCropMappingFromTexture:
    """Test conversion to mapping dictionary."""

    def test_returns_mapping(self):
        """Should return a dictionary with correct keys."""
        values = {
            "Crop_CX": 0.3,
            "Crop_CY": 0.7,
            "Crop_W": 0.5,
            "Crop_H": 0.6,
            "Crop_Rotate90": 0.0,
        }
        result = logical_crop_mapping_from_texture(values)
        
        assert isinstance(result, dict)
        assert "Crop_CX" in result
        assert "Crop_CY" in result
        assert "Crop_W" in result
        assert "Crop_H" in result
        
        # With no rotation, values should match
        assert result["Crop_CX"] == 0.3
        assert result["Crop_CY"] == 0.7
        assert result["Crop_W"] == 0.5
        assert result["Crop_H"] == 0.6
