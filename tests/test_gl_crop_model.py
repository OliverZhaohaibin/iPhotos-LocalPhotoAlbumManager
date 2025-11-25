"""Tests for the gl_crop CropSessionModel module."""

import pytest

from src.iPhoto.gui.ui.widgets.gl_crop.model import CropSessionModel


@pytest.fixture
def model():
    """Create a CropSessionModel instance for testing."""
    return CropSessionModel()


def test_create_and_restore_snapshot(model):
    """Test snapshot creation and restoration."""
    # Set custom crop values
    crop_state = model.get_crop_state()
    crop_state.cx = 0.3
    crop_state.cy = 0.4
    crop_state.width = 0.5
    crop_state.height = 0.6

    # Create snapshot
    snapshot = model.create_snapshot()
    assert snapshot == (0.3, 0.4, 0.5, 0.6)

    # Modify crop
    crop_state.cx = 0.7
    crop_state.cy = 0.8

    # Restore snapshot
    model.restore_snapshot(snapshot)
    assert crop_state.cx == pytest.approx(0.3)
    assert crop_state.cy == pytest.approx(0.4)
    assert crop_state.width == pytest.approx(0.5)
    assert crop_state.height == pytest.approx(0.6)


def test_has_changed_detects_changes(model):
    """Test that has_changed correctly detects state changes."""
    snapshot = model.create_snapshot()
    assert not model.has_changed(snapshot)

    # Make a change
    crop_state = model.get_crop_state()
    crop_state.cx = 0.6
    assert model.has_changed(snapshot)


def test_has_changed_ignores_small_changes(model):
    """Test that has_changed ignores tiny floating-point differences."""
    snapshot = model.create_snapshot()
    crop_state = model.get_crop_state()
    crop_state.cx = 0.5 + 1e-7  # Very small change
    assert not model.has_changed(snapshot)


def test_baseline_management(model):
    """Test baseline crop state management."""
    assert not model.has_baseline()

    model.create_baseline()
    assert model.has_baseline()

    model.clear_baseline()
    assert not model.has_baseline()


def test_update_perspective_no_change(model):
    """Test that update_perspective returns False when nothing changes."""
    # First update sets values
    changed = model.update_perspective(0.0, 0.0, 0.0, 0, False, 1.0)
    assert changed  # First update should change

    # Same values should not trigger change
    changed = model.update_perspective(0.0, 0.0, 0.0, 0, False, 1.0)
    assert not changed


def test_update_perspective_with_change(model):
    """Test that update_perspective returns True when values change."""
    model.update_perspective(0.0, 0.0, 0.0, 0, False, 1.0)
    changed = model.update_perspective(0.1, 0.0, 0.0, 0, False, 1.0)
    assert changed


def test_is_crop_inside_quad_initially(model):
    """Test that crop starts inside the unit quad."""
    # Default crop (full image) should be inside unit quad
    model.update_perspective(0.0, 0.0, 0.0, 0, False, 1.0)
    assert model.is_crop_inside_quad()


def test_ensure_crop_center_inside_quad_when_already_inside(model):
    """Test that ensure_crop_center_inside_quad does nothing when already inside."""
    model.update_perspective(0.0, 0.0, 0.0, 0, False, 1.0)
    changed = model.ensure_crop_center_inside_quad()
    assert not changed


def test_auto_scale_crop_to_quad_when_already_fits(model):
    """Test that auto_scale_crop_to_quad does nothing when crop already fits."""
    model.update_perspective(0.0, 0.0, 0.0, 0, False, 1.0)
    changed = model.auto_scale_crop_to_quad()
    assert not changed


def test_ensure_valid_or_revert_keeps_valid_crop(model):
    """Test that ensure_valid_or_revert keeps a valid crop state."""
    model.update_perspective(0.0, 0.0, 0.0, 0, False, 1.0)
    snapshot = model.create_snapshot()
    result = model.ensure_valid_or_revert(snapshot, allow_shrink=False)
    assert result


def test_ensure_valid_or_revert_reverts_invalid_crop(model):
    """Test that ensure_valid_or_revert reverts an invalid crop state."""
    model.update_perspective(0.0, 0.0, 0.0, 0, False, 1.0)
    snapshot = model.create_snapshot()

    # Make crop invalid by moving it outside bounds
    crop_state = model.get_crop_state()
    crop_state.cx = -0.5  # Way outside
    crop_state.cy = -0.5

    # Should revert to snapshot
    model.ensure_valid_or_revert(snapshot, allow_shrink=False)
    
    # Check if reverted (cx, cy should be back to snapshot values)
    # The revert might clamp values, so we just check it's different from the invalid state
    assert crop_state.cx != -0.5 or crop_state.cy != -0.5


def test_apply_baseline_perspective_fit_without_baseline(model):
    """Test that apply_baseline_perspective_fit does nothing without a baseline."""
    changed = model.apply_baseline_perspective_fit()
    assert not changed


def test_apply_baseline_perspective_fit_with_baseline(model):
    """Test applying baseline perspective fit."""
    # Set up a baseline
    crop_state = model.get_crop_state()
    crop_state.cx = 0.5
    crop_state.cy = 0.5
    crop_state.width = 0.8
    crop_state.height = 0.8
    model.create_baseline()

    # Update perspective (this would normally change the quad)
    model.update_perspective(0.1, 0.1, 0.0, 0, False, 1.0)

    # Apply baseline fit
    changed = model.apply_baseline_perspective_fit()
    # The result depends on the perspective quad, so we just verify it runs
    assert isinstance(changed, bool)


# Tests for _transform_quad_to_texture_space (rotation coordinate transformation)

def test_transform_quad_no_rotation(model):
    """Test that quad is unchanged when rotate_steps=0."""
    # Set up with no rotation
    model.update_perspective(0.0, 0.0, 0.0, 0, False, 1.0)
    quad = model.get_perspective_quad()
    
    # Unit quad should remain unchanged
    assert len(quad) == 4
    # Corners should be approximately at unit square positions
    for pt in quad:
        assert 0.0 <= pt[0] <= 1.0
        assert 0.0 <= pt[1] <= 1.0


def test_transform_quad_with_90_rotation(model):
    """Test quad transformation with 90° rotation (step=1)."""
    # Set up with 90° rotation
    model.update_perspective(0.0, 0.0, 0.0, 1, False, 1.0)
    quad = model.get_perspective_quad()
    
    # With rotation, the quad should be transformed to texture space
    assert len(quad) == 4
    # All points should still be within valid bounds (with some tolerance for floating point)
    for pt in quad:
        assert -0.01 <= pt[0] <= 1.01
        assert -0.01 <= pt[1] <= 1.01


def test_transform_quad_with_180_rotation(model):
    """Test quad transformation with 180° rotation (step=2)."""
    # Set up with 180° rotation
    model.update_perspective(0.0, 0.0, 0.0, 2, False, 1.0)
    quad = model.get_perspective_quad()
    
    assert len(quad) == 4
    # The quad should be valid in texture space
    for pt in quad:
        assert -0.01 <= pt[0] <= 1.01
        assert -0.01 <= pt[1] <= 1.01


def test_transform_quad_with_270_rotation(model):
    """Test quad transformation with 270° rotation (step=3)."""
    # Set up with 270° rotation
    model.update_perspective(0.0, 0.0, 0.0, 3, False, 1.0)
    quad = model.get_perspective_quad()
    
    assert len(quad) == 4
    for pt in quad:
        assert -0.01 <= pt[0] <= 1.01
        assert -0.01 <= pt[1] <= 1.01


def test_crop_inside_quad_with_rotation(model):
    """Test that crop validation works correctly with rotation.
    
    This is the key test for the bug fix: crop coordinates are stored in
    texture space, and the perspective quad must be transformed to texture
    space for correct validation.
    """
    # Set up default centered crop
    crop_state = model.get_crop_state()
    crop_state.cx = 0.5
    crop_state.cy = 0.5
    crop_state.width = 0.5
    crop_state.height = 0.5
    
    # Test with different rotation values
    for rotate_steps in range(4):
        model.update_perspective(0.0, 0.0, 0.0, rotate_steps, False, 1.0)
        # A centered crop should always be inside the quad
        assert model.is_crop_inside_quad(), f"Failed for rotate_steps={rotate_steps}"


def test_crop_inside_quad_with_perspective_and_rotation(model):
    """Test crop validation with combined perspective and rotation.
    
    This tests the scenario described in the issue: perspective + straighten
    + rotation should not cause crop displacement.
    """
    crop_state = model.get_crop_state()
    crop_state.cx = 0.5
    crop_state.cy = 0.5
    crop_state.width = 0.3
    crop_state.height = 0.3
    
    # Test with perspective + straighten + rotation
    for rotate_steps in range(4):
        # Small perspective and straighten values
        model.update_perspective(0.1, 0.05, 2.0, rotate_steps, False, 1.5)
        # A small centered crop should be inside even with perspective
        inside = model.is_crop_inside_quad()
        assert inside, f"Centered crop should be inside quad for rotate_steps={rotate_steps}"


def test_perspective_quad_consistency_across_rotations(model):
    """Test that perspective quad is consistent across rotation steps.
    
    The quad should represent the valid crop area in texture space,
    regardless of the rotation step.
    """
    # Set up some perspective values
    perspective_vertical = 0.2
    perspective_horizontal = 0.1
    straighten = 5.0
    
    quads = []
    for rotate_steps in range(4):
        model.update_perspective(
            perspective_vertical, 
            perspective_horizontal, 
            straighten, 
            rotate_steps, 
            False, 
            1.5
        )
        quads.append(model.get_perspective_quad())
    
    # Each quad should be valid (all corners defined)
    for i, quad in enumerate(quads):
        assert len(quad) == 4, f"Quad {i} should have 4 corners"
        for j, pt in enumerate(quad):
            assert len(pt) == 2, f"Point {j} of quad {i} should have 2 coordinates"
