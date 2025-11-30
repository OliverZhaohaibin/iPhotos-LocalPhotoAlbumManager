
import pytest

# Simulation of Shader Functions

def check_crop(uv, crop_cx, crop_cy, crop_w, crop_h):
    """
    Simulates crop check.
    """
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
    """
    Simulates apply_rotation_90 from shader.
    Maps Logical (Screen) -> Texture.
    """
    steps = steps % 4
    x, y = uv
    if steps == 0:
        return (x, y)
    if steps == 1: # 90 CW Image Rotation
        # Screen Top-Right (1,0) maps to Texture Top-Left (0,0)
        # Formula: (v, 1-u)
        return (y, 1.0 - x)
    if steps == 2: # 180
        return (1.0 - x, 1.0 - y)
    if steps == 3: # 270 CW
        return (1.0 - y, x)
    return (x, y)

def apply_inverse_perspective(uv):
    # Simulating identity perspective for this test to isolate rotation issue
    return uv

# The Logic Under Test

def buggy_shader_logic(uv_corrected, crop_params, rotate_steps):
    """
    Simulates the CURRENT (Buggy) shader logic.
    1. Checks crop against uv_corrected (Logical Space).
    2. Applies Inverse Perspective.
    3. Applies Rotation.

    This logic fails because it compares Logical coordinates (uv_corrected)
    against Texture Space crop parameters, leading to incorrect cropping
    when rotation or perspective is applied.
    """
    cx, cy, w, h = crop_params

    # 1. Crop Test (Current Bug: Tests Logical UV against Params)
    if not check_crop(uv_corrected, cx, cy, w, h):
        return "DISCARD"

    # 2. Inverse Perspective
    uv_perspective = apply_inverse_perspective(uv_corrected)

    # 3. Rotation
    uv_tex = apply_rotation_90(uv_perspective, rotate_steps)
    return uv_tex

def fixed_shader_logic(uv_corrected, crop_params, rotate_steps):
    """
    Simulates the EXPECTED (Fixed) shader logic.
    1. Applies Inverse Perspective.
    2. Applies Rotation to obtain Texture Coordinates (uv_tex).
    3. Checks crop against uv_tex (Texture Space).

    This ensures that the crop rectangle is aligned with the original
    image content (Texture Space), respecting perspective and rotation.
    """
    cx, cy, w, h = crop_params

    # 1. Inverse Perspective
    uv_perspective = apply_inverse_perspective(uv_corrected)

    # 2. Rotation
    uv_tex = apply_rotation_90(uv_perspective, rotate_steps)

    # 3. Crop Test (Fix: Tests Texture UV against Params)
    if not check_crop(uv_tex, cx, cy, w, h):
        return "DISCARD"

    return uv_tex

def test_repro_rotation_crop_mismatch():
    """
    Verifies that the Fixed Logic correctly handles Texture Space cropping parameters
    under rotation, while the Buggy Logic fails (accepts invalid points).

    Scenario:
    - Texture: 100x100
    - Rotation: 90 CW.
    - Crop: Left Half of Texture (x < 0.5).
      Params: CX=0.25, CY=0.5, W=0.5, H=1.0.
    """

    # Texture Space Crop Parameters
    crop_params = (0.25, 0.5, 0.5, 1.0) # Left Half
    rotate_steps = 1 # 90 CW

    # Test Point:
    # Texture Point (0.8, 0.5).
    # This is in the Right Half (x > 0.5).
    # SHOULD BE DISCARDED.

    # Logical Point corresponding to Texture(0.8, 0.5) under 90 CW rotation:
    # Tex -> Log (Inverse of Log->Tex)
    # Log->Tex is (v, 1-u).
    # u_tex = v_log
    # v_tex = 1 - u_log
    # => v_log = u_tex = 0.8
    # => u_log = 1 - v_tex = 1 - 0.5 = 0.5
    # Logical Point is (0.5, 0.8).

    uv_test = (0.5, 0.8)

    # 1. Test Fixed Logic (Expectation)
    # --------------------------------
    # Should DISCARD the point because Texture X (0.8) is outside Crop Range [0, 0.5].
    result_fixed = fixed_shader_logic(uv_test, crop_params, rotate_steps)
    assert result_fixed == "DISCARD", "Fixed logic should discard point (0.8, 0.5)"

    # 2. Test Buggy Logic (Old Implementation)
    # --------------------------------------------
    # Buggy Logic checks uv_test (0.5, 0.8) against Crop Params [0, 0.5] x [0, 1].
    # Check X: 0.5 is inside [0, 0.5] (Boundary).
    # Check Y: 0.8 is inside [0, 1].
    # It erroneously PASSES.

    res_buggy = buggy_shader_logic(uv_test, crop_params, rotate_steps)
    assert res_buggy != "DISCARD", "Buggy logic erroneously accepts point"
