# 黑边检测参数差异分析

本文档详细分析了在 `step != 0` 和 `step = 0` 两种情况下，黑边检测相关函数传入参数的不同点。

## 1. 概述

在 iPhoto 项目中，黑边检测主要涉及以下两个核心函数：
- `compute_rotation_cover_scale`: 计算旋转覆盖缩放系数，确保旋转后的图像无黑边
- `build_perspective_matrix`: 构建透视变换矩阵，包含旋转和透视校正

`rotate_steps`（即 step）参数表示90°旋转的步数（0-3），决定了图像的离散旋转状态。

---

## 2. `compute_rotation_cover_scale` 函数分析

### 函数签名
```python
def compute_rotation_cover_scale(
    texture_size: tuple[int, int],
    base_scale: float,
    straighten_degrees: float,
    rotate_steps: int,
    physical_texture_size: tuple[int, int] | None = None,
) -> float:
```

### 2.1 当 `step = 0` 时

**调用方式（在 `widget.py` 中）:**
```python
cover_scale = compute_rotation_cover_scale(
    (display_w, display_h),      # 逻辑尺寸
    base_scale,
    straighten_deg,
    rotate_steps,                 # rotate_steps = 0
    physical_texture_size=(tex_w, tex_h),
)
```

**参数特点:**
| 参数 | 值/特点 |
|------|---------|
| `texture_size` | 逻辑尺寸 `(display_w, display_h)` |
| `rotate_steps` | 0 |
| `total_degrees` | 仅包含 `straighten_degrees` |
| `physical_texture_size` | 物理纹理尺寸 `(tex_w, tex_h)` |

**计算逻辑:**
```python
# 当提供 physical_texture_size 时
total_degrees = float(straighten_degrees)  # 仅微调角度，无90°旋转
```

### 2.2 当 `step != 0` 时

**向后兼容模式（不提供 `physical_texture_size`）:**
```python
total_degrees = float(straighten_degrees) + float(int(rotate_steps)) * -90.0
```

**参数特点:**
| 参数 | 值/特点 |
|------|---------|
| `texture_size` | 物理尺寸（未旋转的原始尺寸） |
| `rotate_steps` | 1, 2, 或 3 |
| `total_degrees` | `straighten_degrees + rotate_steps * -90.0` |
| `physical_texture_size` | `None`（未提供） |

**关键差异:**
- 当 `step != 0` 且未提供 `physical_texture_size` 时，`total_degrees` 会包含90°的倍数旋转
- 角隅检测使用相同的纹理尺寸 `(tex_w, tex_h)` 进行边界检查

---

## 3. `build_perspective_matrix` 函数分析

### 函数签名
```python
def build_perspective_matrix(
    vertical: float,
    horizontal: float,
    *,
    image_aspect_ratio: float,
    straighten_degrees: float = 0.0,
    rotate_steps: int = 0,
    flip_horizontal: bool = False,
) -> np.ndarray:
```

### 3.1 在 `GLRenderer.render` 中（渲染器）

**始终传入 `rotate_steps=0`:**
```python
perspective_matrix = build_perspective_matrix(
    adjustment_value("Perspective_Vertical", 0.0),
    adjustment_value("Perspective_Horizontal", 0.0),
    image_aspect_ratio=logical_aspect_ratio,
    straighten_degrees=straighten_value,
    # 注释说明：旋转由 shader 中的 uRotate90 处理
    rotate_steps=0,  # 始终为0
    flip_horizontal=flip_enabled,
)
```

**原因:**
- 90°旋转由 shader 中的 `uRotate90` uniform 变量单独处理
- 透视矩阵只需处理微调角度（straighten）和透视校正
- 避免在透视矩阵中重复计算旋转

### 3.2 在 `CropSessionModel.update_perspective` 中（裁剪模型）

**当 `step != 0` 时有特殊处理:**
```python
# 根据旋转步数调整坐标系
calc_straighten = new_straighten
calc_vertical = new_vertical
calc_horizontal = new_horizontal

if new_rotate % 2 != 0:  # 当 step = 1 或 3 时
    calc_straighten = -new_straighten      # 反向
    calc_vertical = -new_vertical          # 反向
    calc_horizontal = -new_horizontal      # 反向

matrix = build_perspective_matrix(
    calc_vertical,                          # 可能被反向
    calc_horizontal,                        # 可能被反向
    image_aspect_ratio=aspect_ratio,
    straighten_degrees=calc_straighten,     # 可能被反向
    rotate_steps=0,                         # 始终传入0
    flip_horizontal=new_flip,
)
```

**参数差异表:**

| step值 | calc_vertical | calc_horizontal | calc_straighten | rotate_steps |
|--------|--------------|-----------------|-----------------|--------------|
| 0 | `vertical` | `horizontal` | `straighten` | 0 |
| 1 | `-vertical` | `-horizontal` | `-straighten` | 0 |
| 2 | `vertical` | `horizontal` | `straighten` | 0 |
| 3 | `-vertical` | `-horizontal` | `-straighten` | 0 |

**关键发现:**
- `rotate_steps` 参数始终传入 `0`
- 当 `step` 为奇数（1或3）时，`vertical`、`horizontal` 和 `straighten` 参数会被反向（乘以-1）
- 这种反向是为了保持透视校正在视觉上的一致性

---

## 4. 总结对比表

### `compute_rotation_cover_scale` 参数差异

| 条件 | texture_size | rotate_steps | total_degrees 计算 | physical_texture_size |
|------|--------------|--------------|-------------------|----------------------|
| step=0 (新模式) | 逻辑尺寸 | 0 | `straighten_degrees` | 物理尺寸 |
| step≠0 (兼容模式) | 物理尺寸 | 1-3 | `straighten + step * -90` | None |

### `build_perspective_matrix` 参数差异

| 调用位置 | rotate_steps参数 | 其他参数处理 |
|----------|-----------------|-------------|
| GLRenderer.render | 始终为0 | 无特殊处理 |
| CropSessionModel | 始终为0 | step为奇数时反向 vertical/horizontal/straighten |

---

## 5. 设计原理

### 5.1 为何在透视矩阵中传入 `rotate_steps=0`

1. **职责分离**: 90°离散旋转由 shader 的 `uRotate90` uniform 单独处理
2. **避免重复计算**: 防止在矩阵和 shader 中重复应用旋转
3. **数值稳定性**: 减少浮点误差累积

### 5.2 为何在裁剪模型中反向参数

1. **坐标系一致性**: 当图像旋转90°或270°时，视觉坐标系发生变化
2. **用户体验**: 确保透视滑块在任何旋转角度下都按预期方向工作
3. **逻辑空间映射**: 将逻辑空间的透视参数正确映射到纹理空间

### 5.3 新模式 vs 兼容模式

新模式（提供 `physical_texture_size`）:
- 使用逻辑尺寸计算视口边框
- 使用物理尺寸检查角隅边界
- 仅应用微调角度（straighten）

兼容模式（不提供 `physical_texture_size`）:
- 使用物理尺寸进行所有计算
- `total_degrees` 包含完整的旋转角度
