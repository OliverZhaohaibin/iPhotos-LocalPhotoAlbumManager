# Issue: 统一Shader坐标变换架构 - 黑边检测与裁剪框位移修复

## 📋 问题概述 (Executive Summary)

### 现状分析

当前的裁剪（Crop）和透视变换（Perspective）功能存在坐标系统不一致问题，导致以下症状：

1. **黑边检测失效风险**：在 `rotate_steps ≠ 0` 时，黑边检测逻辑可能失效
2. **裁剪框位移问题**：保存后重新进入Crop界面时裁剪框出现位移
3. **Detail/Adjust界面加载失败**：从 `.ipo` 文件读取参数后无法正确显示框内图像
4. **Step Rotate后位移**：在当场旋转时正常，但Done保存后再次进入会出现位移

### 目标架构

将所有坐标变换统一到 **Fragment Shader** 中，Python层仅在逻辑空间操作，避免：
- 复杂的多坐标系换算
- 旋转导致的累积误差
- 不同界面的坐标处理不一致

---

## 🔍 技术背景 (Technical Background)

### 坐标系统架构

系统使用四套坐标系，参见 `AGENT.md` 第11节第5小节：

| 坐标系 | 定义 | 用途 |
|--------|------|------|
| **纹理空间 (Texture Space)** | 原始图片像素空间 [0,1] | 持久化存储、纹理采样 |
| **逻辑空间 (Logical Space)** | 旋转后用户看到的空间 | UI交互、裁剪框拖拽 |
| **投影空间 (Projected Space)** | 透视变换后（旋转前） | 黑边检测 |
| **视口空间 (Viewport Space)** | 屏幕像素坐标 | 鼠标事件处理 |

### 关键坐标转换函数

位置：`src/iPhoto/gui/ui/widgets/gl_image_viewer/geometry.py`

```python
def texture_crop_to_logical(crop, rotate_steps) -> tuple:
    """纹理空间 → 逻辑空间（用于UI显示）"""
    
def logical_crop_to_texture(crop, rotate_steps) -> tuple:
    """逻辑空间 → 纹理空间（用于持久化）"""
```

### 当前 Shader 变换管线

位置：`src/iPhoto/gui/ui/widgets/gl_image_viewer.frag`

```glsl
void main() {
    // 1. Y轴翻转
    uv.y = 1.0 - uv.y;
    
    // 2. 透视逆变换
    vec2 uv_perspective = apply_inverse_perspective(uv_corrected);
    
    // 3. 裁剪测试（在旋转前）
    if (uv_perspective outside crop_bounds) discard;
    
    // 4. 应用旋转
    vec2 uv_tex = apply_rotation_90(uv_perspective, uRotate90);
    
    // 5. 纹理采样
    vec4 texel = texture(uTex, uv_tex);
}
```

---

## 🐛 问题详细分析 (Detailed Problem Analysis)

### 问题1: Detail/Adjust界面加载失败

#### 症状
- Crop界面保存数据正确（写入 `.ipo` 文件）
- 返回Detail界面后显示的裁剪结果与预期不符
- Adjust界面中裁剪框可视化位置不正确
- 重新打开Crop界面时能正确恢复

#### 根因分析

**文件**：`src/iPhoto/gui/ui/controllers/player_view_controller.py`

```python
# _AdjustedImageWorker.run() 方法 (行 46-77)
def run(self) -> None:
    # 加载原始图像
    image = image_loader.load_qimage(self._source, None)
    
    # 从 sidecar 加载参数
    raw_adjustments = sidecar.load_adjustments(self._source)
    adjustments = sidecar.resolve_render_adjustments(raw_adjustments, color_stats=stats)
    
    # 发送到主线程
    self._signals.completed.emit(self._source, image, adjustments or {})
```

```python
# _on_adjusted_image_ready() 方法 (行 276-296)
def _on_adjusted_image_ready(self, source: Path, image: QImage, adjustments: dict) -> None:
    self._image_viewer.set_image(
        image,
        adjustments,  # ⚠️ 直接传递，未区分纹理/逻辑空间
        image_source=source,
        reset_view=True,
    )
```

**问题点**：
1. `sidecar.load_adjustments()` 返回的 `Crop_*` 参数在**纹理空间**
2. `sidecar.resolve_render_adjustments()` 未转换 Crop 参数
3. 传递给 `GLImageViewer` 的参数直接使用纹理空间坐标

**文件**：`src/iPhoto/gui/ui/widgets/gl_image_viewer/widget.py`

```python
# paintGL() 方法 (行 474-509)
def paintGL(self) -> None:
    if self._crop_controller.is_active():
        effective_adjustments = dict(self._adjustments)
        effective_adjustments.update({
            "Crop_CX": 0.5, "Crop_CY": 0.5,
            "Crop_W": 1.0, "Crop_H": 1.0,
        })
    else:
        # ✅ 正确：转换为逻辑空间传给Shader
        effective_adjustments = dict(self._adjustments)
        logical_crop = geometry.logical_crop_mapping_from_texture(self._adjustments)
        effective_adjustments.update(logical_crop)
```

**矛盾点**：
- `paintGL()` 在非Crop模式下会将纹理空间转换为逻辑空间
- 但 Shader 的裁剪测试是在 `uv_perspective` 坐标上进行的
- 需要验证 Shader 是否正确处理这种转换

---

### 问题2: Step Rotate后裁剪框位移

#### 症状
- 在Crop编辑界面当场旋转（rotate_image_ccw）时**没有位移**
- 点击Done保存后，再次进入Crop界面进行step rotate时**出现位移**

#### 根因分析

**当场旋转的正确流程**（`widget.py` 行 306-345）：

```python
def rotate_image_ccw(self) -> dict[str, float]:
    """旋转图片90°逆时针，不改变crop几何"""
    
    rotated_steps = (geometry.get_rotate_steps(self._adjustments) - 1) % 4
    
    # 透视参数重映射到旋转后坐标系
    old_v = float(self._adjustments.get("Perspective_Vertical", 0.0))
    old_h = float(self._adjustments.get("Perspective_Horizontal", 0.0))
    old_flip = bool(self._adjustments.get("Crop_FlipH", False))
    
    new_v = old_h
    new_h = -old_v
    if old_flip:
        new_h = -new_h
    
    updates: dict[str, float] = {
        "Crop_Rotate90": float(rotated_steps),
        "Perspective_Vertical": new_v,
        "Perspective_Horizontal": new_h,
    }
    
    # 立即应用到viewer
    self.set_adjustments({**self._adjustments, **updates})
    self.reset_zoom()
    return updates
```

**关键点**：当场旋转时：
1. `Crop_Rotate90` 改变
2. 透视参数（V/H）重映射
3. **Crop_CX/CY/W/H 不变**（在纹理空间保持不变）

**保存后重新加载的流程问题**：

**文件**：`src/iPhoto/gui/ui/controllers/edit_controller.py`

```python
# begin_edit() 方法 (行 212-277)
def begin_edit(self) -> None:
    adjustments = sidecar.load_adjustments(source)  # 纹理空间
    
    session = EditSession(self)
    session.set_values(adjustments, emit_individual=False)
    self._session = session
    self._apply_session_adjustments_to_viewer()
    
    # ⚠️ 关键：进入Crop模式时的初始化
    viewer.setCropMode(False, session.values())
```

**文件**：`src/iPhoto/gui/ui/widgets/gl_image_viewer/widget.py`

```python
# setCropMode() 方法 (行 523-532)
def setCropMode(self, enabled: bool, values: Mapping[str, float] | None = None) -> None:
    was_active = self._crop_controller.is_active()
    source_values = values if values is not None else self._adjustments
    
    # ✅ 正确转换：纹理空间 → 逻辑空间
    logical_values = geometry.logical_crop_mapping_from_texture(source_values)
    self._crop_controller.set_active(enabled, logical_values)
```

**问题追踪**：

1. **_set_mode("crop")** (edit_controller.py 行 810-830)：
```python
def _set_mode(self, mode: str, *, from_top_bar: bool = False) -> None:
    if mode == "crop":
        crop_values: Mapping[str, float] | None = None
        if self._session is not None:
            crop_values = {
                "Crop_CX": float(self._session.value("Crop_CX")),
                "Crop_CY": float(self._session.value("Crop_CY")),
                "Crop_W": float(self._session.value("Crop_W")),
                "Crop_H": float(self._session.value("Crop_H")),
            }
        # ⚠️ 注意：这里传的是session的原始值（纹理空间）
        # 但没有包含Crop_Rotate90！
        self._ui.edit_image_viewer.setCropMode(True, crop_values)
```

**关键发现**：`_set_mode("crop")` 传递的 `crop_values` **缺少 `Crop_Rotate90`**！

这导致 `setCropMode()` 中调用 `logical_crop_mapping_from_texture()` 时：
```python
logical_values = geometry.logical_crop_mapping_from_texture(source_values)
# source_values 缺少 Crop_Rotate90，默认为0
# 导致坐标转换不正确！
```

---

### 问题3: 黑边检测与Step≠0的兼容性

#### 当前黑边检测逻辑

**文件**：`src/iPhoto/gui/ui/widgets/gl_crop/model.py`

```python
def update_perspective(self, vertical, horizontal, straighten, rotate_steps, flip_horizontal, aspect_ratio) -> bool:
    # ✅ 关键：四边形计算时强制 rotate_steps=0
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

**设计意图**：
- 有效区域四边形在"投影空间"计算，不受旋转影响
- 旋转只是坐标重映射，不改变有效像素区域
- 因此黑边检测应该在 `rotate_steps=0` 的投影空间进行

**潜在问题**：
- Crop Model 的 `_crop_state` 在**逻辑空间**
- 透视四边形 `_perspective_quad` 在**投影空间（rotate_steps=0）**
- 当 `rotate_steps ≠ 0` 时，两者坐标系不一致
- `rect_inside_quad()` 检查可能产生错误结果

---

## 🔧 修复方案 (Proposed Solution)

### 总体策略

**核心原则**：
1. **存储空间**：`.ipo` 文件始终使用**纹理空间**
2. **交互空间**：Python UI层始终使用**逻辑空间**
3. **渲染空间**：Shader 负责所有变换，接收**逻辑空间**参数
4. **黑边检测**：在**投影空间**（rotate_steps=0）进行

### 方案A: 修复缺失的Crop_Rotate90传递

**修改文件**：`src/iPhoto/gui/ui/controllers/edit_controller.py`

```python
def _set_mode(self, mode: str, *, from_top_bar: bool = False) -> None:
    if mode == "crop":
        crop_values: Mapping[str, float] | None = None
        if self._session is not None:
            crop_values = {
                "Crop_CX": float(self._session.value("Crop_CX")),
                "Crop_CY": float(self._session.value("Crop_CY")),
                "Crop_W": float(self._session.value("Crop_W")),
                "Crop_H": float(self._session.value("Crop_H")),
                # ✅ 修复：包含Crop_Rotate90
                "Crop_Rotate90": float(self._session.value("Crop_Rotate90")),
            }
        self._ui.edit_image_viewer.setCropMode(True, crop_values)
```

### 方案B: 统一resolve_render_adjustments中的Crop参数

**修改文件**：`src/iPhoto/io/sidecar.py`

```python
def resolve_render_adjustments(
    adjustments: Mapping[str, float | bool] | None,
    *,
    color_stats: ColorStats | None = None,
) -> Dict[str, float]:
    """Return adjustments suitable for rendering pipelines."""
    
    # ... 现有Light/Color/BW处理 ...
    
    # ✅ 新增：转换Crop参数到逻辑空间
    from ..gui.ui.widgets.gl_image_viewer import geometry
    
    rotate_steps = int(float(adjustments.get("Crop_Rotate90", 0.0)))
    if rotate_steps != 0:
        crop_tuple = (
            float(adjustments.get("Crop_CX", 0.5)),
            float(adjustments.get("Crop_CY", 0.5)),
            float(adjustments.get("Crop_W", 1.0)),
            float(adjustments.get("Crop_H", 1.0)),
        )
        logical_crop = geometry.texture_crop_to_logical(crop_tuple, rotate_steps)
        resolved["Crop_CX"] = logical_crop[0]
        resolved["Crop_CY"] = logical_crop[1]
        resolved["Crop_W"] = logical_crop[2]
        resolved["Crop_H"] = logical_crop[3]
    
    resolved["Crop_Rotate90"] = float(rotate_steps)
    
    return resolved
```

### 方案C: 修复黑边检测的坐标系一致性

**修改文件**：`src/iPhoto/gui/ui/widgets/gl_crop/model.py`

需要确保：
1. `_crop_state` 存储的是逻辑空间坐标
2. `is_crop_inside_quad()` 在检查前将逻辑空间坐标转换到投影空间

```python
def is_crop_inside_quad(self) -> bool:
    """Check if the crop rectangle is entirely inside the perspective quad."""
    quad = self._perspective_quad or unit_quad()
    
    # 逻辑空间crop → 投影空间（需要应用逆旋转）
    crop_in_projected = self._convert_crop_to_projected_space()
    
    return rect_inside_quad(crop_in_projected, quad)

def _convert_crop_to_projected_space(self) -> NormalisedRect:
    """Convert logical-space crop to projected space (rotate_steps=0)."""
    from ..gl_image_viewer.geometry import logical_crop_to_texture
    
    crop_state = self._crop_state
    crop_tuple = (crop_state.cx, crop_state.cy, crop_state.width, crop_state.height)
    
    # 逻辑空间 → 纹理空间（相当于rotate_steps=0）
    tex_crop = logical_crop_to_texture(crop_tuple, self._rotate_steps)
    
    left = tex_crop[0] - tex_crop[2] * 0.5
    top = tex_crop[1] - tex_crop[3] * 0.5
    right = tex_crop[0] + tex_crop[2] * 0.5
    bottom = tex_crop[1] + tex_crop[3] * 0.5
    
    return NormalisedRect(left, top, right, bottom)
```

---

## 📊 数据流图 (Data Flow Diagram)

### 保存流程 (Save Flow)

```
                    ┌─────────────────────────┐
                    │ 用户在Crop界面编辑      │
                    │ (逻辑空间交互)          │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │ CropInteractionController│
                    │ _emit_crop_changed()    │
                    │ 发出逻辑空间坐标        │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │ GLImageViewer           │
                    │ _handle_crop_changed()  │
                    │ 逻辑→纹理空间转换       │
                    │ logical_crop_to_texture()│
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │ EditController          │
                    │ _handle_crop_changed()  │
                    │ 更新Session（纹理空间） │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │ _handle_done_clicked()  │
                    │ sidecar.save_adjustments│
                    │ 写入.ipo文件（纹理空间）│
                    └─────────────────────────┘
```

### 加载流程 (Load Flow) - 需要修复

```
                    ┌─────────────────────────┐
                    │ sidecar.load_adjustments│
                    │ 从.ipo文件读取          │
                    │ (纹理空间)              │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │ PlayerViewController    │
                    │ _AdjustedImageWorker    │
                    │ resolve_render_adjustments│
                    │ ⚠️ 缺少Crop坐标转换     │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │ GLImageViewer.set_image │
                    │ paintGL()               │
                    │ ✅ 已有转换逻辑         │
                    │ logical_crop_mapping... │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │ Fragment Shader         │
                    │ 接收逻辑空间Crop参数    │
                    │ 裁剪测试在uv_perspective│
                    │ ⚠️ 坐标系不匹配？       │
                    └─────────────────────────┘
```

---

## ✅ 实施检查清单 (Implementation Checklist)

### Phase 1: 修复Crop_Rotate90传递问题

- [ ] 修改 `edit_controller.py` 的 `_set_mode()` 方法，添加 `Crop_Rotate90`
- [ ] 验证进入Crop模式时坐标转换正确
- [ ] 添加单元测试验证旋转后重新进入Crop的行为

### Phase 2: 统一渲染参数解析

- [ ] 修改 `sidecar.py` 的 `resolve_render_adjustments()` 方法
- [ ] 确保Detail/Adjust界面接收正确的逻辑空间Crop参数
- [ ] 添加单元测试验证参数解析

### Phase 3: 验证黑边检测一致性

- [ ] 审查 `model.py` 的 `is_crop_inside_quad()` 方法
- [ ] 确保crop状态和透视四边形在同一坐标系比较
- [ ] 添加测试验证rotate_steps≠0时的黑边检测

### Phase 4: Shader层验证

- [ ] 验证Fragment Shader的裁剪测试逻辑
- [ ] 确认 `uv_perspective` 坐标与传入的Crop参数坐标系一致
- [ ] 考虑是否需要在Shader中添加旋转逆变换

### Phase 5: 集成测试

- [ ] 测试完整的保存-加载-编辑循环
- [ ] 测试多次旋转后的累积误差
- [ ] 测试透视变换+旋转的组合场景

---

## 📁 相关文件清单 (Related Files)

### 核心文件
| 文件 | 职责 |
|------|------|
| `src/iPhoto/io/sidecar.py` | `.ipo` 文件读写 |
| `src/iPhoto/gui/ui/widgets/gl_image_viewer/geometry.py` | 坐标转换函数 |
| `src/iPhoto/gui/ui/widgets/gl_image_viewer/widget.py` | GL查看器主类 |
| `src/iPhoto/gui/ui/widgets/gl_image_viewer.frag` | Fragment Shader |

### 控制器
| 文件 | 职责 |
|------|------|
| `src/iPhoto/gui/ui/controllers/player_view_controller.py` | Detail界面控制 |
| `src/iPhoto/gui/ui/controllers/edit_controller.py` | Adjust/Crop界面控制 |
| `src/iPhoto/gui/ui/widgets/gl_crop/controller.py` | Crop交互控制 |

### 数据模型
| 文件 | 职责 |
|------|------|
| `src/iPhoto/gui/ui/widgets/gl_crop/model.py` | Crop状态与黑边检测 |
| `src/iPhoto/gui/ui/models/edit_session.py` | 编辑会话状态 |

### 测试文件
| 文件 | 职责 |
|------|------|
| `tests/test_gl_image_viewer_geometry.py` | 几何变换测试 |
| `tests/test_shader_coordinate_refactoring.py` | Shader坐标测试 |
| `tests/test_sidecar_crop_persistence.py` | Sidecar持久化测试 |

---

## 📚 参考文档 (References)

- `AGENT.md` 第11节："OpenGL开发规范"
- `AGENT.md` 第11节第5小节："裁剪与透视变换：坐标系定义"
- `docs/crop-display-coordinate-issue.md`：现有问题分析文档
- `src/iPhoto/gui/ui/widgets/gl_image_viewer/geometry.py` 顶部文档注释

---

## 🏷️ 元信息 (Metadata)

| 属性 | 值 |
|------|-----|
| **创建日期** | 2024-11-26 |
| **优先级** | High |
| **类型** | Bug / Architecture |
| **影响范围** | Crop、Perspective、Detail、Adjust界面 |
| **状态** | 待实施 (To Be Implemented) |

---

## 📝 附录A: 坐标转换验证表

### 纹理空间 → 逻辑空间 转换

| rotate_steps | 变换公式 | 示例 (0.3, 0.7) → |
|--------------|----------|-------------------|
| 0 | (x, y, w, h) | (0.3, 0.7, w, h) |
| 1 (90° CW) | (1-y, x, h, w) | (0.3, 0.3, h, w) |
| 2 (180°) | (1-x, 1-y, w, h) | (0.7, 0.3, w, h) |
| 3 (270° CW) | (y, 1-x, h, w) | (0.7, 0.7, h, w) |

### 逻辑空间 → 纹理空间 转换（逆变换）

| rotate_steps | 变换公式 | 示例 (0.3, 0.7) → |
|--------------|----------|-------------------|
| 0 | (x, y, w, h) | (0.3, 0.7, w, h) |
| 1 | (y, 1-x, h, w) | (0.7, 0.7, h, w) |
| 2 | (1-x, 1-y, w, h) | (0.7, 0.3, w, h) |
| 3 | (1-y, x, h, w) | (0.3, 0.3, h, w) |

---

## 📝 附录B: Shader裁剪测试分析

### 当前实现 (gl_image_viewer.frag)

```glsl
// 裁剪参数（从Python传入，当前是逻辑空间）
uniform float uCropCX;
uniform float uCropCY;
uniform float uCropW;
uniform float uCropH;

void main() {
    // ...
    
    // uv_perspective 是透视变换后、旋转前的坐标
    // 这是"投影空间"坐标
    vec2 uv_perspective = apply_inverse_perspective(uv_corrected);
    
    // 裁剪测试使用逻辑空间参数 vs 投影空间坐标
    // ⚠️ 当rotate_steps≠0时，两者坐标系不一致！
    float crop_min_x = uCropCX - uCropW * 0.5;
    // ...
    if (uv_perspective outside crop_bounds) discard;
}
```

### 分析

当 `rotate_steps = 0` 时：
- 逻辑空间 = 纹理空间 = 投影空间
- 裁剪测试正确

当 `rotate_steps ≠ 0` 时：
- `uv_perspective` 在投影空间（未旋转）
- `uCrop*` 参数在逻辑空间（已旋转）
- **坐标系不匹配！**

### 潜在解决方案

**选项1**: Shader接收纹理空间参数
```glsl
// Python传入纹理空间参数，Shader直接使用
// 优点：简单一致
// 缺点：需要修改Python侧的参数传递
```

**选项2**: Shader将逻辑空间转回投影空间
```glsl
// 添加逆旋转函数
vec4 logical_crop_to_projected(float cx, float cy, float w, float h, int rotate_steps) {
    // 逆旋转变换
}
// 缺点：增加Shader复杂度
```

**选项3**: 统一Python侧的参数空间
```python
# 确保传给Shader的参数始终在投影空间
# 优点：Shader无需修改
# 缺点：需要仔细管理参数传递
```

---

**文档版本**: 1.0  
**最后更新**: 2024-11-26
