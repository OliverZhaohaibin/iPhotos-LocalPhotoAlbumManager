# 裁剪坐标变换分析总结

## 问题

**帮我分析一下目前 cropstep 变换的时候，裁剪框和图片本身，是不是都是基于 step=0 的时候做的 CPU 坐标变换实现的？**

## 答案

**否。** 系统采用了更优雅的双坐标系设计，而不是基于 step=0 做所有变换。

## 双坐标系设计

### 1. 纹理空间 (Texture Space)
- **用途**: 持久化存储
- **特点**: 永远对应原始图像方向 (相当于 step=0)
- **不变性**: 无论旋转多少次，存储的坐标始终不变
- **应用**: 
  - 保存到 sidecar 文件
  - GPU 纹理采样

### 2. 逻辑空间 (Logical Space)
- **用途**: UI 交互
- **特点**: 随当前旋转步骤 (rotate_steps) 动态变化
- **直观性**: 匹配用户当前看到的视觉方向
- **应用**:
  - 拖拽裁剪框
  - 缩放裁剪框
  - 碰撞检测

## 关键转换函数

### 纹理 → 逻辑
```python
# 文件: src/iPhoto/gui/ui/widgets/gl_image_viewer/geometry.py
logical_crop = texture_crop_to_logical(texture_crop, rotate_steps)
```

**转换规则**:
- `step=0` (0°): 逻辑坐标 = 纹理坐标
- `step=1` (90° CW): `(x', y') = (1-y, x)`, 宽高交换
- `step=2` (180°): `(x', y') = (1-x, 1-y)`
- `step=3` (270° CW): `(x', y') = (y, 1-x)`, 宽高交换

### 逻辑 → 纹理
```python
texture_crop = logical_crop_to_texture(logical_crop, rotate_steps)
```

这是上述转换的**逆变换**，用于将用户编辑的坐标转回存储格式。

## 工作流程

```
1. 加载图像
   ↓
2. 从 sidecar 读取纹理坐标 (Crop_CX, Crop_CY, Crop_W, Crop_H, Crop_Rotate90)
   ↓
3. 用户进入裁剪模式
   ↓
4. 纹理坐标 → 逻辑坐标 (根据 rotate_steps 转换)
   ↓
5. 用户在逻辑空间中交互 (拖拽、缩放)
   ↓
6. 实时回调: 逻辑坐标 → 纹理坐标
   ↓
7. 保存纹理坐标到 sidecar
```

## 设计优势

### ✅ 存储稳定
- 纹理坐标不随旋转变化
- 避免浮点数累积误差
- 旋转 → 旋转 → 旋转，存储坐标始终一致

### ✅ 交互直观
- 用户拖动方向 = 裁剪框移动方向
- 无需在交互层做旋转补偿
- 代码简单清晰

### ✅ 渲染高效
- GPU 直接使用纹理坐标采样
- CPU 只需转换 4 个角点
- 无逐像素旋转计算

### ✅ 职责分离
- 存储层: 纹理空间，不可变
- 交互层: 逻辑空间，动态变化
- 转换层: 纯函数，可测试

## 代码示例

### 进入裁剪模式
```python
# widget.py:517
def setCropMode(self, enabled: bool, values: dict):
    # 纹理 → 逻辑
    logical_values = geometry.logical_crop_mapping_from_texture(values)
    self._crop_controller.set_active(enabled, logical_values)
```

### 保存裁剪结果
```python
# widget.py:783
def _handle_crop_interaction_changed(self, cx, cy, width, height):
    # 逻辑 → 纹理
    rotate_steps = geometry.get_rotate_steps(self._adjustments)
    tex_coords = geometry.logical_crop_to_texture((cx, cy, width, height), rotate_steps)
    self.cropChanged.emit(*tex_coords)
```

## 测试验证

所有几何变换测试通过:
```bash
$ pytest tests/test_gl_image_viewer_geometry.py -v
16 passed in 0.05s
```

关键测试: **往返转换无损**
```python
# 对于所有旋转步骤 (0, 1, 2, 3)
texture → logical → texture == texture  ✓
```

## 运行演示

```bash
python demo/crop_coordinate_demo.py
```

演示内容:
1. 基本坐标转换
2. 往返转换验证
3. 用户交互流程模拟
4. 设计优势说明

## 结论

**系统没有基于 step=0 做所有变换。** 而是采用了:
- **纹理空间** (存储层) - 相当于 step=0，但仅用于存储
- **逻辑空间** (交互层) - 跟随当前 rotate_steps
- **纯函数转换** - 在两者之间映射

这种设计兼顾了存储稳定性、交互自然性和渲染效率。

## 参考文档

- 详细分析: `docs/CROP_TRANSFORMATION_ANALYSIS.md`
- 流程图: `docs/CROP_TRANSFORMATION_FLOW.md`
- 交互演示: `demo/crop_coordinate_demo.py`
- 核心代码: `src/iPhoto/gui/ui/widgets/gl_image_viewer/geometry.py`
- 单元测试: `tests/test_gl_image_viewer_geometry.py`
