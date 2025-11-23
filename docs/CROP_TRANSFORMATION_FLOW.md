# 裁剪坐标变换流程图 (Crop Coordinate Transformation Flow)

## 完整数据流 (Complete Data Flow)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           1. 用户加载图像                                     │
│                        (User Loads Image)                                   │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    2. 从 Sidecar 读取持久化数据                               │
│                 (Load Persisted Data from Sidecar)                          │
│                                                                             │
│  adjustments = {                                                            │
│      "Crop_CX": 0.3,          ← 纹理空间中心 X                               │
│      "Crop_CY": 0.7,          ← 纹理空间中心 Y                               │
│      "Crop_W": 0.5,           ← 纹理空间宽度                                 │
│      "Crop_H": 0.6,           ← 纹理空间高度                                 │
│      "Crop_Rotate90": 1.0     ← 旋转步骤 (0-3)                              │
│  }                                                                          │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    3. 用户点击裁剪按钮                                        │
│                   (User Clicks Crop Button)                                 │
│                                                                             │
│  → widget.setCropMode(enabled=True, values=adjustments)                     │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│              4. 纹理空间 → 逻辑空间转换 (进入裁剪模式)                         │
│          (Texture Space → Logical Space Conversion)                         │
│                                                                             │
│  rotate_steps = 1  (90° CW)                                                 │
│                                                                             │
│  logical_values = geometry.logical_crop_mapping_from_texture(adjustments)   │
│                                                                             │
│  转换公式 (Transformation):                                                  │
│    logical_cx = 1.0 - texture_cy = 1.0 - 0.7 = 0.3                          │
│    logical_cy = texture_cx = 0.3                                            │
│    logical_w = texture_h = 0.6   (宽高交换)                                  │
│    logical_h = texture_w = 0.5                                              │
│                                                                             │
│  结果 (Result):                                                              │
│  logical_values = {                                                         │
│      "Crop_CX": 0.3,          ← 逻辑空间中心 X                               │
│      "Crop_CY": 0.3,          ← 逻辑空间中心 Y                               │
│      "Crop_W": 0.6,           ← 逻辑空间宽度                                 │
│      "Crop_H": 0.5            ← 逻辑空间高度                                 │
│  }                                                                          │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                  5. 裁剪控制器初始化 (逻辑空间)                               │
│              (Crop Controller Initialization - Logical Space)               │
│                                                                             │
│  crop_controller.set_active(enabled=True, values=logical_values)            │
│      ↓                                                                      │
│  CropBoxState 加载逻辑坐标:                                                  │
│      state.cx = 0.3                                                         │
│      state.cy = 0.3                                                         │
│      state.width = 0.6                                                      │
│      state.height = 0.5                                                     │
│                                                                             │
│  ✓ 裁剪框现在匹配用户的视觉方向 (旋转后的图像)                                 │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                   6. 用户交互 (逻辑空间操作)                                  │
│                 (User Interaction - Logical Space Operations)               │
│                                                                             │
│  鼠标拖拽裁剪框:                                                              │
│      delta_view = mouse_current - mouse_previous                            │
│      state.translate_pixels(delta_view, image_size)                         │
│          ↓                                                                  │
│      state.cx += delta_view.x() / image_width   (逻辑空间移动)               │
│      state.cy += delta_view.y() / image_height                              │
│                                                                             │
│  调整裁剪框边缘:                                                              │
│      state.drag_edge_pixels(handle, delta, image_size)                      │
│          ↓                                                                  │
│      根据拖动的边缘更新 state.width, state.height (逻辑空间)                  │
│                                                                             │
│  滚轮缩放:                                                                   │
│      state.zoom_about_point(anchor_x, anchor_y, factor)                     │
│          ↓                                                                  │
│      state.width /= factor  (逻辑空间缩放)                                   │
│      state.height /= factor                                                 │
│                                                                             │
│  ✓ 所有操作都在逻辑空间，直观且简单                                           │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                   7. 实时回调 (每次裁剪框改变)                                │
│                  (Real-time Callback - On Crop Changed)                     │
│                                                                             │
│  crop_controller._emit_crop_changed()                                       │
│      ↓                                                                      │
│  widget._handle_crop_interaction_changed(                                   │
│      cx=state.cx,        # 逻辑坐标                                          │
│      cy=state.cy,                                                           │
│      width=state.width,                                                     │
│      height=state.height                                                    │
│  )                                                                          │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│              8. 逻辑空间 → 纹理空间转换 (准备保存)                             │
│          (Logical Space → Texture Space Conversion for Storage)             │
│                                                                             │
│  假设用户编辑后的逻辑坐标:                                                     │
│      logical = (0.4, 0.35, 0.5, 0.4)  # (cx, cy, w, h)                      │
│                                                                             │
│  rotate_steps = 1  (仍然是 90° CW)                                           │
│                                                                             │
│  texture_coords = geometry.logical_crop_to_texture(logical, rotate_steps)   │
│                                                                             │
│  转换公式 (Inverse Transformation):                                          │
│    texture_cx = logical_cy = 0.35                                           │
│    texture_cy = 1.0 - logical_cx = 1.0 - 0.4 = 0.6                          │
│    texture_w = logical_h = 0.4    (宽高交换回来)                             │
│    texture_h = logical_w = 0.5                                              │
│                                                                             │
│  结果 (Result):                                                              │
│  texture_coords = (0.35, 0.6, 0.4, 0.5)                                     │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    9. 发出信号保存纹理坐标                                    │
│                (Emit Signal to Save Texture Coordinates)                    │
│                                                                             │
│  widget.cropChanged.emit(                                                   │
│      tex_cx=0.35,                                                           │
│      tex_cy=0.6,                                                            │
│      tex_w=0.4,                                                             │
│      tex_h=0.5                                                              │
│  )                                                                          │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                   10. 更新 adjustments 并持久化                              │
│                (Update Adjustments and Persist)                             │
│                                                                             │
│  adjustments["Crop_CX"] = 0.35      ← 纹理空间坐标                           │
│  adjustments["Crop_CY"] = 0.6                                               │
│  adjustments["Crop_W"] = 0.4                                                │
│  adjustments["Crop_H"] = 0.5                                                │
│  adjustments["Crop_Rotate90"] = 1.0  (保持不变)                              │
│                                                                             │
│  → 保存到 sidecar.json                                                       │
│                                                                             │
│  ✓ 纹理坐标独立于旋转，避免累积误差                                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 关键变换点总结 (Key Transformation Points Summary)

### 变换点 1: 进入裁剪模式
```python
# 文件: src/iPhoto/gui/ui/widgets/gl_image_viewer/widget.py:517
def setCropMode(self, enabled: bool, values: Mapping[str, float] | None = None):
    # 纹理 → 逻辑
    logical_values = geometry.logical_crop_mapping_from_texture(source_values)
    self._crop_controller.set_active(enabled, logical_values)
```

### 变换点 2: 保存裁剪结果
```python
# 文件: src/iPhoto/gui/ui/widgets/gl_image_viewer/widget.py:783
def _handle_crop_interaction_changed(self, cx, cy, width, height):
    # 逻辑 → 纹理
    rotate_steps = geometry.get_rotate_steps(self._adjustments)
    tex_coords = geometry.logical_crop_to_texture((cx, cy, width, height), rotate_steps)
    self.cropChanged.emit(*tex_coords)
```

---

## 坐标空间对比图 (Coordinate Space Comparison)

### 原始图像 (1920x1080, rotate_steps=0)
```
纹理空间 (Texture Space):        逻辑空间 (Logical Space):
┌──────────────────┐             ┌──────────────────┐
│                  │             │                  │
│  ┌────────┐      │             │  ┌────────┐      │
│  │ 裁剪框  │      │             │  │ 裁剪框  │      │
│  └────────┘      │             │  └────────┘      │
│                  │             │                  │
└──────────────────┘             └──────────────────┘
Crop_CX=0.3, Crop_CY=0.5         Crop_CX=0.3, Crop_CY=0.5
相同 (Same)                       相同 (Same)
```

### 旋转 90° CW (rotate_steps=1)
```
纹理空间 (Texture Space):        逻辑空间 (Logical Space):
┌──────────────────┐             ┌─────────────┐
│                  │             │             │
│  ┌────────┐      │             │             │
│  │ 裁剪框  │      │             │  ┌────┐     │
│  └────────┘      │             │  │裁剪│     │
│                  │             │  │ 框 │     │
└──────────────────┘             │  └────┘     │
                                 │             │
Crop_CX=0.3, Crop_CY=0.5         └─────────────┘
(不变，存储值)                    Crop_CX=0.5, Crop_CY=0.3
                                 (变换后，视觉值)
```

**转换关系**:
```
逻辑 X = 1.0 - 纹理 Y = 1.0 - 0.5 = 0.5
逻辑 Y = 纹理 X = 0.3
逻辑 W = 纹理 H
逻辑 H = 纹理 W
```

---

## 为什么这样设计？(Why This Design?)

### 优势 1: 存储稳定性
```
用户操作序列:
1. 原始裁剪 → 纹理坐标 (0.3, 0.5, 0.6, 0.4)
2. 旋转 90° → 纹理坐标 (0.3, 0.5, 0.6, 0.4)  ← 不变!
3. 再旋转 90° → 纹理坐标 (0.3, 0.5, 0.6, 0.4)  ← 仍不变!
4. 再裁剪 → 纹理坐标 (0.35, 0.55, 0.5, 0.35) ← 只更新实际编辑

✓ 避免浮点累积误差
✓ 旋转操作不污染裁剪数据
```

### 优势 2: 交互自然性
```
用户拖拽裁剪框向右 →
    逻辑空间: cx += delta  (直观)
    纹理空间: 需要根据 rotate_steps 决定是 ±cx 还是 ±cy  (复杂)

✓ 逻辑空间操作符合视觉直觉
✓ 代码简单，易于维护
```

### 优势 3: 渲染高效
```
GPU Shader:
    直接使用纹理坐标采样
    无需 CPU 端旋转变换

CPU:
    只需转换 4 个角点到屏幕坐标
    碰撞检测在逻辑空间 (轴对齐)

✓ 最小化 CPU-GPU 数据传输
✓ 避免逐像素旋转计算
```

---

## 实际代码调用链 (Actual Code Call Chain)

```python
# 1. 用户点击裁剪按钮
edit_controller.on_crop_btn_clicked()
    ↓
# 2. 进入裁剪模式 (纹理 → 逻辑)
gl_image_viewer.setCropMode(enabled=True, values=adjustments)
    ↓ geometry.logical_crop_mapping_from_texture(adjustments)
        ↓ rotate_steps = get_rotate_steps(values)
        ↓ crop = normalised_crop_from_mapping(values)
        ↓ logical_crop = texture_crop_to_logical(crop, rotate_steps)
    ↓
# 3. 裁剪控制器加载逻辑坐标
crop_controller.set_active(enabled=True, values=logical_values)
    ↓ model.get_crop_state().set_from_mapping(logical_values)
        ↓ state.cx = logical_values["Crop_CX"]
        ↓ state.cy = logical_values["Crop_CY"]
        ↓ state.width = logical_values["Crop_W"]
        ↓ state.height = logical_values["Crop_H"]
    ↓
# 4. 用户拖拽裁剪框 (逻辑空间操作)
crop_controller.handle_mouse_move(event)
    ↓ strategy.on_drag(delta_view)
        ↓ state.translate_pixels(delta, image_size)  # 逻辑空间移动
            ↓ state.cx += delta.x() / image_width
            ↓ state.cy += delta.y() / image_height
    ↓
# 5. 发出变更信号 (逻辑 → 纹理)
crop_controller._emit_crop_changed()
    ↓ on_crop_changed_callback(state.cx, state.cy, state.width, state.height)
        ↓
gl_image_viewer._handle_crop_interaction_changed(cx, cy, width, height)
    ↓ rotate_steps = geometry.get_rotate_steps(adjustments)
    ↓ tex_coords = geometry.logical_crop_to_texture((cx, cy, width, height), rotate_steps)
    ↓
# 6. 保存纹理坐标
gl_image_viewer.cropChanged.emit(tex_cx, tex_cy, tex_w, tex_h)
    ↓
edit_controller._on_crop_changed(tex_cx, tex_cy, tex_w, tex_h)
    ↓ adjustments["Crop_CX"] = tex_cx
    ↓ adjustments["Crop_CY"] = tex_cy
    ↓ adjustments["Crop_W"] = tex_w
    ↓ adjustments["Crop_H"] = tex_h
    ↓
# 7. 持久化到 sidecar
sidecar.save(adjustments)
```

---

## 测试验证 (Test Validation)

所有几何变换都有完整的单元测试覆盖:

```bash
$ pytest tests/test_gl_image_viewer_geometry.py -v
================================================= test session starts ==================================================
tests/test_gl_image_viewer_geometry.py::TestTextureCropToLogical::test_no_rotation PASSED
tests/test_gl_image_viewer_geometry.py::TestTextureCropToLogical::test_90_degree_rotation PASSED
tests/test_gl_image_viewer_geometry.py::TestTextureCropToLogical::test_180_degree_rotation PASSED
tests/test_gl_image_viewer_geometry.py::TestTextureCropToLogical::test_270_degree_rotation PASSED
tests/test_gl_image_viewer_geometry.py::TestLogicalCropToTexture::test_rotation_inverse_property PASSED
================================================== 16 passed in 0.05s ==================================================
```

**关键测试: 往返转换无损**
```python
def test_rotation_inverse_property(self):
    original = (0.3, 0.7, 0.5, 0.6)
    for rotate_steps in range(4):
        logical = texture_crop_to_logical(original, rotate_steps)
        back = logical_crop_to_texture(logical, rotate_steps)
        assert back == pytest.approx(original, abs=1e-6)  ← 验证通过! ✓
```

---

## 结论 (Conclusion)

**系统没有基于 step=0 做所有坐标变换，而是采用了更优雅的双坐标系设计:**

1. **纹理空间** (Texture Space) - 存储层，等效于 step=0，不随旋转变化
2. **逻辑空间** (Logical Space) - 交互层，跟随当前 rotate_steps，保证直观性
3. **转换函数** - 纯函数实现双向映射，测试覆盖完整

这种设计兼顾了**存储稳定性**、**交互自然性**和**渲染效率**。
