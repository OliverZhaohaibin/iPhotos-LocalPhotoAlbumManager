# 裁剪坐标变换分析 (Crop Coordinate Transformation Analysis)

> **注意**: 本文档中的行号引用基于分析时的代码版本。如果代码发生变更，请参考方法名和类名来定位相关代码。
> 
> **Note**: Line number references in this document are based on the code version at the time of analysis. If code changes, please use method and class names to locate relevant code.

## 问题 (Question)

分析目前 cropstep 变换的时候，裁剪框和图片本身，是不是都是基于 step=0 的时候做的 CPU 坐标变换实现的？

(During crop-step transformation, are both the crop box and the image implemented based on CPU coordinate transformations when step=0?)

## 答案 (Answer)

**否 (No)** - 裁剪框和图片**不是**基于 step=0 做坐标变换。系统采用了更加合理的双坐标系设计：

1. **纹理空间 (Texture Space)** - 永远基于原始图像 (step=0)，用于存储
2. **逻辑空间 (Logical Space)** - 基于当前旋转步骤，用于 UI 交互

---

## 详细分析 (Detailed Analysis)

### 1. 坐标系统架构 (Coordinate System Architecture)

系统使用了**两套独立的坐标系**，通过显式的转换函数进行映射：

#### A. 纹理空间 (Texture Space)
- **定义**: 原始图像的像素坐标系，永远对应于 `rotate_steps = 0` 的状态
- **用途**: 
  - 持久化存储裁剪参数 (`Crop_CX`, `Crop_CY`, `Crop_W`, `Crop_H`)
  - GPU 纹理采样的源坐标
- **不变性**: 无论用户如何旋转图像，存储的坐标始终保持在纹理空间

#### B. 逻辑空间 (Logical Space)  
- **定义**: 用户当前视觉所见的坐标系，会随 `rotate_steps` 变化
- **用途**:
  - UI 交互 (拖拽、缩放裁剪框)
  - 显示裁剪框覆盖层
  - 计算屏幕坐标映射
- **动态性**: 每次旋转后，逻辑坐标会重新计算以匹配视觉方向

---

### 2. 核心转换函数 (Core Transformation Functions)

#### 函数位置: `src/iPhoto/gui/ui/widgets/gl_image_viewer/geometry.py`

##### A. `texture_crop_to_logical(crop, rotate_steps)`
将存储的纹理空间坐标转换为当前视觉的逻辑空间坐标。

**转换规则**:
```python
if rotate_steps == 0:
    # 无旋转，逻辑坐标 = 纹理坐标
    return (tcx, tcy, tw, th)

if rotate_steps == 1:  # 90° CW
    # 转换公式: (x', y') = (1-y, x)
    # 宽高交换: (w', h') = (h, w)
    return (1.0 - tcy, tcx, th, tw)

if rotate_steps == 2:  # 180°
    # 转换公式: (x', y') = (1-x, 1-y)
    return (1.0 - tcx, 1.0 - tcy, tw, th)

if rotate_steps == 3:  # 270° CW (90° CCW)
    # 转换公式: (x', y') = (y, 1-x)
    # 宽高交换: (w', h') = (h, w)
    return (tcy, 1.0 - tcx, th, tw)
```

##### B. `logical_crop_to_texture(crop, rotate_steps)`
将用户编辑的逻辑空间坐标转回纹理空间以便存储。

**这是 `texture_crop_to_logical` 的逆变换**:
```python
if rotate_steps == 0:
    return (lcx, lcy, lw, lh)

if rotate_steps == 1:  # 90° CW 的逆变换
    # 逆向公式: (x, y) = (y', 1-x')
    return (lcy, 1.0 - lcx, lh, lw)

if rotate_steps == 2:  # 180° 的逆变换
    return (1.0 - lcx, 1.0 - lcy, lw, lh)

if rotate_steps == 3:  # 270° CW 的逆变换
    # 逆向公式: (x, y) = (1-y', x')
    return (1.0 - lcy, lcx, lh, lw)
```

---

### 3. 实际工作流程 (Actual Workflow)

#### 场景 1: 进入裁剪模式 (Entering Crop Mode)

**代码路径**: `src/iPhoto/gui/ui/widgets/gl_image_viewer/widget.py:517`

```python
def setCropMode(self, enabled: bool, values: Mapping[str, float] | None = None) -> None:
    # 从存储的纹理坐标转换为逻辑坐标
    source_values = values if values is not None else self._adjustments
    logical_values = geometry.logical_crop_mapping_from_texture(source_values)
    
    # 将逻辑坐标传递给裁剪控制器
    self._crop_controller.set_active(enabled, logical_values)
```

**转换流程**:
```
纹理空间存储值 (Crop_CX, Crop_CY, Crop_W, Crop_H)
    ↓ [apply rotate_steps transformation]
逻辑空间值 (用户视觉所见的裁剪框位置)
    ↓
裁剪控制器使用逻辑坐标进行交互
```

#### 场景 2: 用户拖拽裁剪框 (User Drags Crop Box)

**代码路径**: `src/iPhoto/gui/ui/widgets/gl_crop/controller.py`

```python
def handle_mouse_move(self, event: QMouseEvent) -> None:
    # 1. 屏幕坐标 → 视口坐标
    pos = event.position()
    
    # 2. 计算逻辑空间中的位移
    delta_view = pos - previous_pos
    
    # 3. 在逻辑空间中更新裁剪框
    if self._current_strategy is not None:
        self._current_strategy.on_drag(delta_view)  # 操作 CropBoxState (逻辑坐标)
```

#### 场景 3: 保存裁剪结果 (Saving Crop Result)

**代码路径**: `src/iPhoto/gui/ui/widgets/gl_image_viewer/widget.py:783`

```python
def _handle_crop_interaction_changed(
    self, cx: float, cy: float, width: float, height: float
) -> None:
    """Convert logical crop updates back to texture space before emitting."""
    
    # 获取当前旋转步骤
    rotate_steps = geometry.get_rotate_steps(self._adjustments)
    
    # 将逻辑坐标转回纹理坐标
    tex_cx, tex_cy, tex_w, tex_h = geometry.logical_crop_to_texture(
        (float(cx), float(cy), float(width), float(height)),
        rotate_steps,
    )
    
    # 发出信号保存纹理坐标
    self.cropChanged.emit(tex_cx, tex_cy, tex_w, tex_h)
```

**转换流程**:
```
用户编辑后的逻辑坐标 (可视裁剪框)
    ↓ [apply inverse rotate_steps transformation]
纹理空间坐标 (存储到 adjustments)
    ↓
持久化到 sidecar 文件
```

---

### 4. 关键类的坐标空间 (Coordinate Space of Key Classes)

#### A. `CropBoxState` (逻辑空间)
**位置**: `src/iPhoto/gui/ui/widgets/gl_crop/utils.py`

```python
class CropBoxState:
    """Normalised crop rectangle maintained while crop mode is active."""
    
    def __init__(self) -> None:
        self.cx: float = 0.5      # 逻辑空间中心 X
        self.cy: float = 0.5      # 逻辑空间中心 Y
        self.width: float = 1.0   # 逻辑空间宽度
        self.height: float = 1.0  # 逻辑空间高度
```

**所有操作都在逻辑空间**:
- `translate_pixels()`: 逻辑空间平移
- `zoom_about_point()`: 逻辑空间缩放
- `drag_edge_pixels()`: 逻辑空间调整边缘

#### B. `CropInteractionController` (逻辑空间交互)
**位置**: `src/iPhoto/gui/ui/widgets/gl_crop/controller.py`

所有鼠标交互、碰撞检测、缩放操作都在**逻辑空间**中进行:
```python
def set_active(self, enabled: bool, values: Mapping[str, float] | None = None) -> None:
    # values 已经是转换后的逻辑坐标
    self._apply_crop_values(values)

def _crop_hit_test(self, point: QPointF) -> CropHandle:
    # 使用逻辑空间的裁剪框边界进行碰撞检测
    crop_state = self._model.get_crop_state()  # 逻辑坐标
    rect = crop_state.to_pixel_rect(tex_w, tex_h)
```

---

### 5. 为什么不使用 step=0 的坐标系？(Why Not Use step=0 Coordinates?)

#### 设计优势 (Design Advantages)

1. **交互自然性 (Natural Interaction)**
   - 用户拖拽时，裁剪框的移动方向与鼠标方向一致
   - 无需在交互层做旋转补偿

2. **数学简化 (Mathematical Simplification)**
   - 所有几何运算 (碰撞检测、缩放、平移) 都在轴对齐坐标系中
   - 避免了逐像素的旋转矩阵计算

3. **存储一致性 (Storage Consistency)**
   - 纹理坐标不随旋转变化，避免浮点累积误差
   - 多次旋转后仍能精确还原

4. **渲染效率 (Rendering Efficiency)**
   - GPU Shader 直接使用纹理坐标采样
   - CPU 只需转换一次裁剪框的四个角点

---

### 6. 代码验证 (Code Verification)

#### 测试用例确认
**位置**: `tests/test_gl_image_viewer_geometry.py:172`

```python
def test_rotation_inverse_property(self):
    """Converting texture → logical → texture should preserve original."""
    original = (0.3, 0.7, 0.5, 0.6)
    
    for rotate_steps in range(4):
        logical = texture_crop_to_logical(original, rotate_steps)
        back_to_texture = logical_crop_to_texture(logical, rotate_steps)
        
        # 验证往返转换无损
        assert back_to_texture[0] == pytest.approx(original[0], abs=1e-6)
        assert back_to_texture[1] == pytest.approx(original[1], abs=1e-6)
        assert back_to_texture[2] == pytest.approx(original[2], abs=1e-6)
        assert back_to_texture[3] == pytest.approx(original[3], abs=1e-6)
```

这证明了**双向转换的数学正确性**。

---

## 总结 (Summary)

### 回答原问题

**裁剪框和图片是否基于 step=0 做 CPU 坐标变换？**

**答：否 (No)**

系统采用了更优雅的设计：

1. **存储层 (Storage Layer)**: 使用纹理空间 (等效于 step=0)
2. **交互层 (Interaction Layer)**: 使用逻辑空间 (跟随当前 rotate_steps)
3. **转换层 (Transformation Layer)**: 通过纯函数 `texture_crop_to_logical()` 和 `logical_crop_to_texture()` 实现双向映射

### 坐标空间使用总结

| 组件 | 坐标空间 | 理由 |
|------|---------|------|
| 持久化存储 (`Crop_CX`, `Crop_CY`, etc.) | 纹理空间 | 不随旋转变化，避免累积误差 |
| `CropBoxState` | 逻辑空间 | 交互直观，数学简单 |
| `CropInteractionController` | 逻辑空间 | 碰撞检测、拖拽都在当前视角 |
| GPU Shader 采样 | 纹理空间 | 直接对应原始图像像素 |
| UI 渲染 (裁剪框覆盖层) | 逻辑→视口 | 转换后绘制到屏幕 |

### 关键转换点

```
┌─────────────────┐
│   纹理空间      │  ← 存储在 adjustments / sidecar
│  (Texture)      │
└────────┬────────┘
         │ texture_crop_to_logical(rotate_steps)
         ↓
┌─────────────────┐
│   逻辑空间      │  ← CropBoxState, 交互层
│  (Logical)      │
└────────┬────────┘
         │ 视口变换 (viewport transform)
         ↓
┌─────────────────┐
│   屏幕坐标      │  ← 鼠标事件、绘制
│  (Viewport)     │
└─────────────────┘
```

---

## 参考代码文件 (Reference Code Files)

1. **坐标转换**: `src/iPhoto/gui/ui/widgets/gl_image_viewer/geometry.py`
2. **裁剪状态**: `src/iPhoto/gui/ui/widgets/gl_crop/utils.py`
3. **交互控制**: `src/iPhoto/gui/ui/widgets/gl_crop/controller.py`
4. **主视图集成**: `src/iPhoto/gui/ui/widgets/gl_image_viewer/widget.py`
5. **单元测试**: `tests/test_gl_image_viewer_geometry.py`

---

## 建议 (Recommendations)

当前实现**符合最佳实践**，建议保持不变：

1. ✅ 纹理空间用于存储 - 避免浮点误差
2. ✅ 逻辑空间用于交互 - 保证直观性
3. ✅ 纯函数转换 - 可测试、可验证
4. ✅ 单元测试覆盖 - 保证数学正确性

唯一可能的改进点：

- 考虑添加内联文档说明坐标空间 (已在 AGENT.md 第 5 节部分覆盖)
- 在关键函数签名中标注坐标空间 (如 `@coordinate_space("logical")` 装饰器)
