
import pytest

# Simulation of Shader Functions (Same as before)
def check_crop(uv, crop_cx, crop_cy, crop_w, crop_h):
    min_x = crop_cx - crop_w * 0.5
    max_x = crop_cx + crop_w * 0.5
    min_y = crop_cy - crop_h * 0.5
    max_y = crop_cy + crop_h * 0.5

    # Use approximate comparison to handle float precision at boundaries
    if uv[0] < min_x or uv[0] > max_x:
        return False
    if uv[1] < min_y or uv[1] > max_y:
        return False
    return True

def apply_rotation_90(uv, steps):
    steps = steps % 4
    x, y = uv
    if steps == 0:
        return (x, y)
    if steps == 1: # 90 CW Image Rotation
        return (y, 1.0 - x)
    if steps == 2: # 180
        return (1.0 - x, 1.0 - y)
    if steps == 3: # 270 CW
        return (1.0 - y, x)
    return (x, y)

def apply_inverse_perspective(uv):
    return uv

# Simulation of Python Logic
def texture_crop_to_logical(crop_params, rotate_steps):
    cx, cy, w, h = crop_params
    steps = rotate_steps % 4
    # Simple conversion matching geometry.py (ignoring Perspective)
    # Note: geometry.py uses clamp_unit, simplified here
    if steps == 0: return (cx, cy, w, h)
    if steps == 1: return (1.0-cy, cx, h, w)
    if steps == 2: return (1.0-cx, 1.0-cy, w, h)
    if steps == 3: return (cy, 1.0-cx, h, w)
    return (cx, cy, w, h)

# The Logic Under Test (Original/Restored Shader)
def shader_logic(uv_corrected, logical_crop_params, rotate_steps):
    """
    Simulates the Restored shader logic.
    1. Checks crop against uv_corrected (Logical Space).
    2. Applies Inverse Perspective.
    3. Applies Rotation.
    """
    cx, cy, w, h = logical_crop_params

    # 1. Crop Test (Logical Space)
    if not check_crop(uv_corrected, cx, cy, w, h):
        return "DISCARD"

    # 2. Inverse Perspective
    uv_perspective = apply_inverse_perspective(uv_corrected)

    # 3. Rotation
    uv_tex = apply_rotation_90(uv_perspective, rotate_steps)
    return uv_tex

def test_screen_aligned_crop():
    """
    Verifies that the restored logic supports Screen-Aligned Cropping
    by converting Texture Params -> Logical Params in Python,
    and checking Logical UVs in Shader.
    """
    # Scenario: 90 CW Rotation.
    # Texture Crop: Left Half (x < 0.5).
    # Image Top (Texture Y=0) is Screen Right.
    # Image Left (Texture X=0) is Screen Top.
    # So Texture Left Half -> Screen Top Half.

    tex_params = (0.25, 0.5, 0.5, 1.0) # Left Half
    rotate_steps = 1

    # Python Conversion
    log_params = texture_crop_to_logical(tex_params, rotate_steps)
    # 90 CW: (1-cy, cx, h, w) -> (0.5, 0.25, 1.0, 0.5)
    # Center (0.5, 0.25). Width 1.0. Height 0.5.
    # Y range: [0.0, 0.5].
    # So Screen Top Half. Correct.

    # Test Point:
    # Screen Point (0.5, 0.25). Inside Top Half.
    # Should PASS.
    res = shader_logic((0.5, 0.25), log_params, rotate_steps)
    assert res != "DISCARD"

    # Test Point:
    # Screen Point (0.5, 0.75). Bottom Half.
    # Should FAIL.
    res_fail = shader_logic((0.5, 0.75), log_params, rotate_steps)
    assert res_fail == "DISCARD"
