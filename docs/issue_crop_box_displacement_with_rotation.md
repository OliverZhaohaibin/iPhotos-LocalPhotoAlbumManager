# Issue: 裁剪框在旋转步数(step)不为0时的位移问题

## 1. 问题描述

### 1.1 现象

当用户对图像进行以下组合操作时，裁剪框(crop box)会出现位移：

1. **旋转步数 (step/rotate_steps) ≠ 0**：即图像进行了90°/180°/270°离散旋转
2. **加入 straighten（微调旋转）**：任意微调角度
3. **加入 vertical/horizontal（透视校正）**：垂直或水平透视调整

在上述组合下，应用step旋转后，裁剪框的位置与图像的实际有效区域不匹配，导致用户看到的裁剪框发生了偏移。

### 1.2 正常情况

当 `step = 0` 时，即图像未进行90°离散旋转，配合 `straighten`、`vertical`、`horizontal` 变换时，裁剪框位置始终正确。

---

## 2. 问题分析

### 2.1 代码架构回顾

系统中涉及黑边检测和裁剪框定位的核心模块：

| 模块 | 文件 | 职责 |
|------|------|------|
| 透视矩阵构建 | `perspective_math.py` | 构建包含透视、微调、翻转的变换矩阵 |
| 裁剪模型 | `gl_crop/model.py` | 管理裁剪状态、透视四边形计算 |
| 渲染器 | `gl_renderer.py` | 传递uniform到shader，设置透视矩阵 |
| 着色器 | `gl_image_viewer.frag` | 执行透视逆变换、90°旋转、黑边检测 |
| 坐标变换 | `gl_image_viewer/geometry.py` | 纹理空间与逻辑空间的坐标转换 |
| 缩放计算 | `view_transform_controller.py` | 计算旋转覆盖缩放系数 |

### 2.2 变换链分析

#### 2.2.1 渲染侧的变换顺序（Shader中）

在 `gl_image_viewer.frag` 中，变换按以下顺序应用：

```glsl
// main() 中的变换顺序：
1. uv_corrected = crop_boundary_check(uv);      // 裁剪边界检查
2. is_within_valid_bounds(uv_corrected);         // 统一黑边检测
   2.1. apply_inverse_perspective(uv);           // 透视逆变换
   2.2. apply_rotation_90(uv_perspective, uRotate90);  // 90°旋转
3. uv_original = apply_inverse_perspective(uv_corrected);  // 透视逆变换
4. uv_original = apply_rotation_90(uv_original, uRotate90); // 90°旋转
5. texture(uTex, uv_original);                   // 纹理采样
```

#### 2.2.2 裁剪模型侧的透视四边形计算

在 `CropSessionModel.update_perspective()` 中：

```python
# 当前实现
matrix = build_perspective_matrix(
    new_vertical,
    new_horizontal,
    image_aspect_ratio=aspect_ratio,
    straighten_degrees=new_straighten,
    rotate_steps=0,  # 始终为0
    flip_horizontal=new_flip,
)
self._perspective_quad = compute_projected_quad(matrix)
```

问题在于：`build_perspective_matrix` 中的 `rotate_steps` 始终传入 `0`，因此透视四边形的计算不考虑90°旋转。

#### 2.2.3 坐标空间不匹配

```
┌─────────────────────────────────────────────────────────────────┐
│                         问题根源                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  裁剪模型 (CropSessionModel):                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ perspective_quad = compute_projected_quad(matrix)        │   │
│  │                                                          │   │
│  │ matrix 使用:                                              │   │
│  │   - straighten_degrees = 实际微调角度                      │   │
│  │   - rotate_steps = 0  ← 不考虑90°旋转！                    │   │
│  │   - aspect_ratio = 逻辑宽高比（已旋转）                     │   │
│  │                                                          │   │
│  │ 结果: perspective_quad 在"逻辑空间"中计算，               │   │
│  │       但裁剪坐标存储在"纹理空间"中                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           ↓                                       │
│  裁剪验证 (rect_inside_quad):                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ rect_inside_quad(crop_rect, perspective_quad)            │   │
│  │                                                          │   │
│  │ crop_rect 在"纹理空间"中定义                               │   │
│  │ perspective_quad 在"逻辑空间"中定义                        │   │
│  │                                                          │   │
│  │ 空间不匹配 → 验证结果错误 → 裁剪框位移！                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 根本原因

**坐标空间不一致**：

1. **裁剪框坐标（Crop_CX, Crop_CY等）** 存储在 **纹理空间**（未旋转的原始纹理坐标系）
2. **透视四边形（perspective_quad）** 计算在 **逻辑空间**（已应用90°旋转的视觉坐标系）
3. 当 `rotate_steps ≠ 0` 时，两个坐标系不一致
4. 使用 `rect_inside_quad()` 验证时，坐标空间不匹配导致验证结果错误
5. 裁剪框约束和自动缩放基于错误的验证结果，导致视觉上的位移

---

## 3. 问题根源总结

| 问题 | 描述 |
|------|------|
| **坐标空间混淆** | 透视四边形在逻辑空间计算，裁剪框在纹理空间存储 |
| **rotate_steps 处理不一致** | shader中rotate_steps影响渲染，但裁剪模型中不考虑 |
| **验证逻辑缺陷** | `rect_inside_quad` 比较了两个不同坐标空间的几何体 |
| **宽高比计算** | aspect_ratio 使用逻辑尺寸，但矩阵未完整考虑旋转 |

---

## 4. 修复方案

### 4.1 方案一：统一到逻辑空间（推荐）

**核心思想**：在裁剪验证时，将纹理空间的裁剪框转换到逻辑空间，与透视四边形在同一空间进行比较。

#### 修改文件: `gl_crop/model.py`

```python
def _current_normalised_rect(self) -> NormalisedRect:
    """Return the current crop as a normalised rect in LOGICAL space."""
    # 获取纹理空间的裁剪框
    left, top, right, bottom = self._crop_state.bounds_normalised()
    
    # 根据旋转步数转换到逻辑空间
    if self._rotate_steps == 0:
        return NormalisedRect(left, top, right, bottom)
    
    # 转换中心和尺寸
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    w = right - left
    h = bottom - top
    
    # 应用旋转变换 (纹理空间 → 逻辑空间)
    if self._rotate_steps == 1:
        # 90° CW: (x', y') = (1-y, x)
        lcx, lcy = 1.0 - cy, cx
        lw, lh = h, w
    elif self._rotate_steps == 2:
        # 180°: (x', y') = (1-x, 1-y)
        lcx, lcy = 1.0 - cx, 1.0 - cy
        lw, lh = w, h
    else:  # self._rotate_steps == 3
        # 270° CW (90° CCW): (x', y') = (y, 1-x)
        lcx, lcy = cy, 1.0 - cx
        lw, lh = h, w
    
    # 重建边界
    new_left = lcx - lw / 2
    new_right = lcx + lw / 2
    new_top = lcy - lh / 2
    new_bottom = lcy + lh / 2
    
    return NormalisedRect(new_left, new_top, new_right, new_bottom)
```

### 4.2 方案二：统一到纹理空间

**核心思想**：在计算透视四边形时，将其转换回纹理空间。

#### 修改文件: `gl_crop/model.py`

```python
def update_perspective(self, ...):
    # ... 构建透视矩阵 ...
    
    # 计算逻辑空间的透视四边形
    logical_quad = compute_projected_quad(matrix)
    
    # 将透视四边形从逻辑空间转换到纹理空间
    self._perspective_quad = self._transform_quad_to_texture_space(
        logical_quad, 
        new_rotate
    )

def _transform_quad_to_texture_space(
    self, 
    quad: list[tuple[float, float]], 
    rotate_steps: int
) -> list[tuple[float, float]]:
    """将逻辑空间的四边形转换到纹理空间。"""
    if rotate_steps == 0:
        return quad
    
    def inverse_rotate_point(x: float, y: float) -> tuple[float, float]:
        if rotate_steps == 1:
            # 逆90° CW: (x, y) = (y', 1-x')
            return (y, 1.0 - x)
        elif rotate_steps == 2:
            # 逆180°: (x, y) = (1-x', 1-y')
            return (1.0 - x, 1.0 - y)
        else:  # rotate_steps == 3
            # 逆270° CW: (x, y) = (1-y', x')
            return (1.0 - y, x)
    
    return [inverse_rotate_point(pt[0], pt[1]) for pt in quad]
```

### 4.3 方案三：完全统一到Shader（长期方案）

参考 `requirements_unified_black_border_detection.md` 中的完整重构方案，将所有黑边检测和验证逻辑移至shader端。

**优点**：
- 完全消除Python端和Shader端的坐标空间不一致问题
- 所有 `rotate_steps` 值使用完全相同的检测逻辑

**缺点**：
- 改动较大，需要较多测试
- Shader端复杂度增加

---

## 5. 推荐修复策略

### 阶段一：快速修复（方案一或方案二）

选择 **方案一** 或 **方案二**，最小化改动以快速解决当前问题。

推荐 **方案一（统一到逻辑空间）**，因为：
- 透视四边形本身就在逻辑空间计算
- 只需要在验证时转换裁剪框
- 改动集中在一个位置

### 阶段二：完整重构（方案三）

在快速修复验证通过后，根据 `requirements_unified_black_border_detection.md` 的规划，逐步迁移到shader统一处理模式。

---

## 6. 验证测试用例

修复后需要验证以下场景：

| 测试场景 | 预期结果 |
|---------|---------|
| step=0 + straighten=0 + perspective=0 | 裁剪框位置正确 |
| step=0 + straighten=±10° | 裁剪框位置正确，无黑边 |
| step=0 + vertical/horizontal=±0.5 | 裁剪框位置正确，适应透视变换 |
| step=1 + straighten=0 | 裁剪框位置正确 |
| step=1 + straighten=±10° | 裁剪框位置正确，无黑边 |
| step=1 + vertical/horizontal=±0.5 | 裁剪框位置正确，适应透视变换 |
| step=2 + straighten=±10° | 裁剪框位置正确 |
| step=3 + straighten=±10° | 裁剪框位置正确 |
| 任意 step + 组合变换 | 裁剪框位置正确，无位移 |

---

## 7. 影响范围

| 文件 | 改动类型 | 风险评估 |
|------|---------|---------|
| `gl_crop/model.py` | 核心修改 | 中 |
| `perspective_math.py` | 可能无需修改 | 低 |
| `gl_image_viewer/geometry.py` | 可复用已有函数 | 低 |
| 测试文件 | 新增测试用例 | 低 |

---

## 8. 附录：变换公式参考

### 90°旋转变换（纹理空间 → 逻辑空间）

```
Step 0 (0°):   (x', y') = (x, y)
Step 1 (90° CW):  (x', y') = (1-y, x)
Step 2 (180°): (x', y') = (1-x, 1-y)
Step 3 (270° CW): (x', y') = (y, 1-x)
```

### 逆变换（逻辑空间 → 纹理空间）

```
Step 0 (0°):   (x, y) = (x', y')
Step 1 (90° CW):  (x, y) = (y', 1-x')
Step 2 (180°): (x, y) = (1-x', 1-y')
Step 3 (270° CW): (x, y) = (1-y', x')
```

---

## 9. 参考文档

- [黑边检测参数差异分析](./black_border_detection_parameters.md)
- [统一黑边检测逻辑需求](./requirements_unified_black_border_detection.md)
