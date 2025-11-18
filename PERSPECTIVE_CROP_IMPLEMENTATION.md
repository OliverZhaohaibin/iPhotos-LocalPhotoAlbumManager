# Perspective Crop Box Interaction Implementation

## Overview

This document describes the implementation of smart crop box behavior during perspective adjustments in the iPhoto photo editor.

## Problem Statement

Previously, when adjusting perspective sliders, the crop box would only shrink to avoid black edges but would never expand back to its original size. This resulted in a progressively smaller crop box that didn't utilize the maximum available area.

## Solution

Implement an "interaction-aware" crop box that:
1. Captures the crop box size when the user starts dragging a perspective slider
2. During dragging, attempts to restore the crop box to its original size while keeping it centered at the optimal position (perspective quad centroid)
3. Scales down proportionally only when necessary to avoid black edges
4. Returns to passive constraint checking when the user releases the slider

## Implementation Details

### 1. Signal Chain: BWSlider → PerspectiveControls → DetailPageWidget → CropInteractionController

#### BWSlider (edit_strip.py)
- Added `sliderPressed` signal - emitted when user presses the slider
- Added `sliderReleased` signal - emitted when user releases the slider
- These signals are emitted in `mousePressEvent()` and `mouseReleaseEvent()`

#### _PerspectiveSliderRow (edit_perspective_controls.py)
- Forwards `sliderPressed` and `sliderReleased` from BWSlider
- Acts as a wrapper for individual perspective slider rows

#### PerspectiveControls (edit_perspective_controls.py)
- Added `interactionStarted` signal - emitted when any perspective slider is pressed
- Added `interactionEnded` signal - emitted when any perspective slider is released
- Connects both vertical and horizontal slider rows to these signals
- Exposed via `EditSidebar.perspective_controls()` accessor

#### DetailPageWidget (detail_page.py)
- In `_build_edit_container()`, connects:
  - `perspective_controls.interactionStarted` → `crop_controller.set_perspective_interaction(True)`
  - `perspective_controls.interactionEnded` → `crop_controller.set_perspective_interaction(False)`

### 2. State Management in CropInteractionController (gl_crop_controller.py)

#### New State Variables
```python
self._perspective_interaction_active: bool = False
self._interaction_base_size: tuple[float, float] = (1.0, 1.0)
self._interaction_aspect_ratio: float = 1.0
```

#### New Method: `set_perspective_interaction(active: bool)`
- When `active=True`:
  - Captures current crop state as baseline
  - Sets `_perspective_interaction_active = True`
  - Records `_interaction_base_size` (width, height)
  - Records `_interaction_aspect_ratio` (width / height)
- When `active=False`:
  - Sets `_perspective_interaction_active = False`
  - Clears interaction state

### 3. Dual Logic in `update_perspective()`

#### Non-Interactive Mode (Existing Behavior)
When `_perspective_interaction_active == False`:
- Ensures crop center is inside the quad
- Shrinks crop box if it extends outside the quad
- Never expands the crop box

#### Interactive Mode (New Behavior)
When `_perspective_interaction_active == True`:
- Calls `_adjust_crop_interactive()` which:
  1. Calculates the centroid of the current perspective quad
  2. Creates a candidate rectangle at the centroid with base size
  3. Calls `calculate_min_zoom_to_fit()` to check if it fits
  4. If scale > 1.0: shrinks the crop box proportionally
  5. If scale ≈ 1.0: keeps the base size (achieves "auto-expand" effect)
  6. Updates crop state with new center and dimensions

### 4. The `_adjust_crop_interactive()` Method

```python
def _adjust_crop_interactive(self) -> bool:
    quad = self._perspective_quad or unit_quad()
    
    # Get quad centroid for optimal positioning
    centroid = quad_centroid(quad)
    
    # Build candidate rect at centroid with base size
    base_width, base_height = self._interaction_base_size
    candidate_rect = NormalisedRect(
        left=centroid[0] - base_width * 0.5,
        top=centroid[1] - base_height * 0.5,
        right=centroid[0] + base_width * 0.5,
        bottom=centroid[1] + base_height * 0.5,
    )
    
    # Check if candidate fits inside quad
    scale = calculate_min_zoom_to_fit(candidate_rect, quad)
    
    # Apply scaling to get final dimensions
    final_width = base_width / scale
    final_height = base_height / scale
    
    # Update crop state
    self._crop_state.cx = centroid[0]
    self._crop_state.cy = centroid[1]
    self._crop_state.width = final_width
    self._crop_state.height = final_height
    self._crop_state.clamp()
    
    return True  # if changed
```

## Key Mathematical Concepts

### Perspective Quad
- The perspective transformation creates a distorted quadrilateral
- Calculated via `build_perspective_matrix()` and `compute_projected_quad()`
- Represents the valid region where crop box corners must stay

### Quad Centroid
- Arithmetic center of the quad: `(Σx/4, Σy/4)`
- Provides optimal positioning for maximizing crop box size
- Calculated by `quad_centroid()`

### Scale Factor from `calculate_min_zoom_to_fit()`
- Returns the minimum uniform scale factor needed to fit a rect inside a quad
- Scale > 1.0: rect is too large, must shrink by factor `1/scale`
- Scale ≈ 1.0: rect fits perfectly, no adjustment needed
- Uses ray-casting from rect center to corners to find quad boundaries

## Coordinate System

All calculations use **Normalised Texture Space (0.0 - 1.0)**:
- (0, 0) = top-left corner
- (1, 1) = bottom-right corner
- Crop box position and size are stored as normalized values
- Perspective quad vertices are in normalized coordinates

## Testing

### Manual Testing Steps

1. **Basic Interaction**:
   - Open an image in crop mode
   - Adjust vertical perspective slider
   - Verify crop box shrinks to avoid black edges
   - Release slider, then adjust again
   - Verify crop box attempts to expand back to original size

2. **Multiple Adjustments**:
   - Press and drag vertical slider
   - While holding, observe crop box behavior
   - Release and press again
   - Verify baseline is recaptured each time

3. **Combined Adjustments**:
   - Adjust vertical perspective
   - Then adjust horizontal perspective
   - Verify crop box stays centered and maximized

4. **Edge Cases**:
   - Try extreme perspective values (near ±1.0)
   - Verify crop box doesn't go outside valid region
   - Verify no crashes or unusual behavior

### Expected Behavior

- ✅ Crop box shrinks when necessary to avoid black edges
- ✅ Crop box expands back to maximum size when perspective allows
- ✅ Crop box stays centered at optimal position (quad centroid)
- ✅ Aspect ratio is maintained during interactive adjustments
- ✅ Smooth transitions without jumps or glitches

## Code Quality

- All files pass Python syntax validation
- Ruff linter applied for code style
- Modern type annotations (Python 3.10+ style)
- Follows existing code patterns and conventions
- Minimal changes to existing logic

## Files Modified

1. `src/iPhoto/gui/ui/widgets/edit_strip.py` - Added slider press/release signals
2. `src/iPhoto/gui/ui/widgets/edit_perspective_controls.py` - Added interaction signals
3. `src/iPhoto/gui/ui/widgets/edit_sidebar.py` - Added accessor method
4. `src/iPhoto/gui/ui/widgets/gl_image_viewer.py` - Added accessor method
5. `src/iPhoto/gui/ui/widgets/gl_crop_controller.py` - Added interaction logic
6. `src/iPhoto/gui/ui/widgets/detail_page.py` - Connected signals

Total changes: **~130 lines added** across 6 files

## References

- Original requirement: See problem statement in Chinese (translated above)
- Mathematical helpers: `perspective_math.py`
- Existing crop logic: `gl_crop_controller.py`
