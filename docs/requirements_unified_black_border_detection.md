# 需求文档：统一黑边检测逻辑

## 1. 背景与问题描述

### 1.1 当前问题

目前当 `step != 0`（即图像进行了90°/180°/270°旋转）时，配合 `straighten`、`vertical`、`horizontal` 变换后，黑边检测逻辑失效，导致裁剪框内出现黑边。而当 `step = 0` 时，黑边检测始终正常工作。

### 1.2 根本原因

- **`step = 0` 时**：使用逻辑尺寸和物理尺寸分离的新模式，`total_degrees` 仅包含 `straighten_degrees`
- **`step != 0` 时**：使用兼容模式，`total_degrees` 包含完整的旋转角度（`straighten + step * -90`），导致角隅检测逻辑与实际渲染不匹配

### 1.3 目标

将所有 Python 端涉及到黑边检测的逻辑统一移动到 shader 中，使 `step = 0/1/2/3` 使用完全相同的判定逻辑。

---

## 2. 当前架构分析

### 2.1 Python 端黑边检测相关代码

| 文件 | 函数/方法 | 当前职责 |
|------|----------|---------|
| `view_transform_controller.py` | `compute_rotation_cover_scale()` | 计算旋转覆盖缩放系数 |
| `gl_crop/model.py` | `CropSessionModel.update_perspective()` | 更新透视四边形、处理参数反向 |
| `perspective_math.py` | `build_perspective_matrix()` | 构建透视变换矩阵 |
| `gl_image_viewer/widget.py` | `_update_cover_scale()` | 调用缩放计算并更新控制器 |

### 2.2 Shader 端相关代码

| 文件 | 函数/代码块 | 当前职责 |
|------|------------|---------|
| `gl_image_viewer.frag` | `apply_rotation_90()` | 处理90°离散旋转 |
| `gl_image_viewer.frag` | `apply_inverse_perspective()` | 应用透视逆变换 |
| `gl_image_viewer.frag` | 裁剪边界检测 (L202-211) | 检测像素是否在裁剪框外 |
| `gl_image_viewer.frag` | 透视边界检测 (L214-217) | 检测透视变换后是否越界 |

---

## 3. 需求规格

### 3.1 核心需求

**将黑边检测逻辑从 Python 端移至 Shader 端，确保所有旋转步数使用统一的检测逻辑。**

### 3.2 详细需求

#### 3.2.1 Shader 端改动

1. **新增 uniform 变量**
   ```glsl
   uniform float uStraightenDegrees;  // 微调角度
   uniform float uVertical;           // 垂直透视
   uniform float uHorizontal;         // 水平透视
   uniform bool  uFlipHorizontal;     // 水平翻转
   ```

2. **新增黑边检测函数**
   ```glsl
   // 计算变换后的有效边界坐标
   // 详见 4.1 节的完整实现
   vec2 compute_valid_bounds(vec2 uv, int rotate_steps, float straighten_deg);
   ```

3. **修改 main() 函数**
   - 在应用透视和旋转变换后，调用统一的黑边检测函数
   - 如果检测到黑边区域，执行 `discard`

#### 3.2.2 Python 端改动

1. **`compute_rotation_cover_scale()` 函数**
   - **删除或简化**：不再需要计算覆盖缩放系数
   - 或者统一始终使用 `physical_texture_size` 模式

2. **`CropSessionModel.update_perspective()` 方法**
   - **移除参数反向逻辑**：不再根据 `step % 2` 反向参数
   - 直接传递原始参数到 shader

3. **`build_perspective_matrix()` 函数**
   - **移除 rotate_steps 参数**：旋转完全由 shader 处理
   - 仅处理透视和微调

4. **`GLRenderer.render()` 方法**
   - 新增 uniform 设置：`uStraightenDegrees`, `uVertical`, `uHorizontal`, `uFlipHorizontal`
   - 将原始参数直接传递给 shader

### 3.3 接口变更

#### 3.3.1 Shader Uniforms 新增

| Uniform 名称 | 类型 | 说明 |
|-------------|------|------|
| `uStraightenDegrees` | float | 微调旋转角度（度） |
| `uVertical` | float | 垂直透视参数 [-1, 1] |
| `uHorizontal` | float | 水平透视参数 [-1, 1] |
| `uFlipHorizontal` | bool | 是否水平翻转 |

#### 3.3.2 Python 函数签名变更

```python
# 移除或简化
def compute_rotation_cover_scale(
    texture_size: tuple[int, int],
    base_scale: float,
    straighten_degrees: float,
    rotate_steps: int,
    physical_texture_size: tuple[int, int] | None = None,
) -> float:
    return 1.0  # 不再需要覆盖缩放，由 shader 统一处理

# 简化 build_perspective_matrix
def build_perspective_matrix(
    vertical: float,
    horizontal: float,
    *,
    image_aspect_ratio: float,
    straighten_degrees: float = 0.0,
    # 移除 rotate_steps 参数
    flip_horizontal: bool = False,
) -> np.ndarray:
```

---

## 4. 实现方案

### 4.1 Shader 端实现

```glsl
// 新增：在 shader 中计算透视+旋转后的有效区域检测
vec2 compute_valid_bounds(vec2 uv, int rotate_steps, float straighten_deg) {
    // 1. 应用90°旋转
    vec2 rotated_uv = apply_rotation_90(uv, rotate_steps);
    
    // 2. 应用微调旋转（straighten）
    float theta = radians(straighten_deg);
    float cos_t = cos(theta);
    float sin_t = sin(theta);
    vec2 centered = rotated_uv * 2.0 - 1.0;
    vec2 rotated = vec2(
        centered.x * cos_t - centered.y * sin_t,
        centered.x * sin_t + centered.y * cos_t
    );
    
    // 3. 检测是否在物理纹理边界内
    vec2 final_uv = rotated * 0.5 + 0.5;
    return final_uv;
}

void main() {
    // ... 现有逻辑 ...
    
    // 统一的黑边检测
    vec2 final_uv = compute_valid_bounds(uv_original, uRotate90, uStraightenDegrees);
    if (final_uv.x < 0.0 || final_uv.x > 1.0 ||
        final_uv.y < 0.0 || final_uv.y > 1.0) {
        discard;
    }
    
    // ... 继续采样和处理 ...
}
```

### 4.2 Python 端实现

1. **修改 `GLRenderer.render()`**
   ```python
   # 传递原始参数，不做反向处理
   self._set_uniform1f("uStraightenDegrees", straighten_value)
   self._set_uniform1f("uVertical", adjustment_value("Perspective_Vertical", 0.0))
   self._set_uniform1f("uHorizontal", adjustment_value("Perspective_Horizontal", 0.0))
   self._set_uniform1i("uFlipHorizontal", int(flip_enabled))
   ```

2. **简化 `CropSessionModel.update_perspective()`**
   ```python
   def update_perspective(self, vertical, horizontal, straighten, rotate_steps, flip_horizontal, aspect_ratio):
       # 移除 step % 2 的反向逻辑
       matrix = build_perspective_matrix(
           vertical,      # 不反向
           horizontal,    # 不反向
           image_aspect_ratio=aspect_ratio,
           straighten_degrees=straighten,  # 不反向
           flip_horizontal=flip_horizontal,
       )
       self._perspective_quad = compute_projected_quad(matrix)
   ```

3. **简化 `_update_cover_scale()`**
   ```python
   def _update_cover_scale(self, straighten_deg: float, rotate_steps: int) -> None:
       # 覆盖缩放由 shader 统一处理
       self._transform_controller.set_image_cover_scale(1.0)
   ```

---

## 5. 验证标准

### 5.1 功能验证

| 测试场景 | 预期结果 |
|---------|---------|
| step=0 + straighten=0 | 无黑边 |
| step=0 + straighten=±10° | 无黑边，图像正确放大覆盖 |
| step=1 + straighten=0 | 无黑边 |
| step=1 + straighten=±10° | 无黑边，图像正确放大覆盖 |
| step=2 + straighten=0 | 无黑边 |
| step=2 + straighten=±10° | 无黑边，图像正确放大覆盖 |
| step=3 + straighten=0 | 无黑边 |
| step=3 + straighten=±10° | 无黑边，图像正确放大覆盖 |
| 任意 step + vertical/horizontal 调整 | 无黑边，透视正确 |

### 5.2 回归验证

- 裁剪框交互正常
- 透视滑块响应正确
- 旋转按钮工作正常
- 图像质量无损失

---

## 6. 影响范围

### 6.1 受影响文件

| 文件路径 | 改动类型 |
|---------|---------|
| `src/iPhoto/gui/ui/widgets/gl_image_viewer.frag` | 新增检测逻辑 |
| `src/iPhoto/gui/ui/widgets/gl_renderer.py` | 新增 uniform 设置 |
| `src/iPhoto/gui/ui/widgets/view_transform_controller.py` | 简化/移除函数 |
| `src/iPhoto/gui/ui/widgets/gl_crop/model.py` | 移除反向逻辑 |
| `src/iPhoto/gui/ui/widgets/perspective_math.py` | 移除 rotate_steps 参数 |
| `src/iPhoto/gui/ui/widgets/gl_image_viewer/widget.py` | 简化调用 |

### 6.2 向后兼容性

- **无需数据迁移**：调整参数存储格式不变
- **无需 UI 变更**：用户界面保持不变
- **可能需要的测试更新**：涉及旋转和透视的单元测试

---

## 7. 时间估算

| 阶段 | 预估时间 |
|------|---------|
| Shader 端实现 | 2-3 小时 |
| Python 端重构 | 2-3 小时 |
| 单元测试更新 | 1-2 小时 |
| 集成测试 | 1-2 小时 |
| **总计** | **6-10 小时** |

---

## 8. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| Shader 性能下降 | 优化检测算法，避免重复计算 |
| 边界条件处理不当 | 增加边界测试用例 |
| 现有功能回归 | 保留完整的测试套件 |

---

## 9. 附录：当前代码流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                       当前流程 (step != 0 有问题)                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Python 端:                                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ CropSessionModel.update_perspective()                     │   │
│  │   ├─ 如果 step % 2 != 0, 反向参数                          │   │
│  │   └─ 调用 build_perspective_matrix(rotate_steps=0)        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                       │
│                           ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ compute_rotation_cover_scale()                            │   │
│  │   ├─ 有 physical_texture_size: total = straighten         │   │
│  │   └─ 无 physical_texture_size: total = straighten + step*-90│  │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                       │
│                           ▼                                       │
│  Shader 端:                                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ main()                                                    │   │
│  │   ├─ apply_inverse_perspective() ← 使用 uPerspectiveMatrix  │  │
│  │   ├─ 检测越界 → discard                                    │   │
│  │   └─ apply_rotation_90() ← 使用 uRotate90                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  问题: Python 端的参数反向与 shader 端的旋转顺序不匹配             │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                       目标流程 (统一逻辑)                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Python 端:                                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ GLRenderer.render()                                       │   │
│  │   └─ 直接传递原始参数到 shader uniforms                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                       │
│                           ▼                                       │
│  Shader 端:                                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ main()                                                    │   │
│  │   ├─ 统一应用: 透视 → 微调 → 90°旋转                        │   │
│  │   ├─ 统一的边界检测逻辑                                     │   │
│  │   └─ 如果越界 → discard                                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  优点: 所有 rotate_steps 值使用完全相同的检测逻辑                  │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```
