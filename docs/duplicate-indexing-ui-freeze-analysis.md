# 重复索引导致UI卡死问题分析与修复方案

## 问题描述

当用户在"All Photos"（所有照片）视图中浏览已经被索引并生成好缩略图的媒体后，从侧边栏切换到该媒体所属的物理相册（文件夹）时，会出现以下现象：

1. **短暂正常显示**：界面首先会显示在"All Photos"中已经索引的媒体数据
2. **可滚动时间窗口**：在非常短暂的时间内（约100-200ms），用户可以进行滚动操作
3. **UI冻结**：随后界面完全卡死，无法响应任何操作
4. **恢复显示**：卡死一段时间后，界面恢复，显示该文件夹内重新索引后的数据

## 根本原因分析

### 1. 双模型架构的设计冲突

应用采用了**双模型架构**来管理资产数据：

```python
# 位于 src/iPhoto/gui/facade.py
self._library_list_model = AssetListModel(self)  # 持久化的库模型，用于"All Photos"
self._album_list_model = AssetListModel(self)    # 临时相册模型，用于物理文件夹
```

**问题关键**：这两个模型使用**不同的数据源和索引策略**：

- **library_list_model**：
  - 使用全局索引 `global_index.db`（位于库根目录的 `.iphoto` 文件夹）
  - 包含整个库中所有已索引的媒体
  - 是**持久化**的，在切换视图时不会重置

- **album_list_model**：
  - 根据当前打开的相册路径加载数据
  - 对于物理相册（非库根目录），会创建新的数据加载流程
  - 每次切换相册时会**重置模型**并重新加载

### 2. 索引数据冲突的具体表现

当从"All Photos"切换到物理相册时，发生以下流程：

#### 阶段1：模型切换判断（facade.py:187-238）

```python
def open_album(self, root: Path) -> Optional[Album]:
    target_model = self._album_list_model
    library_root = self._library_manager.root() if self._library_manager else None
    
    # 如果请求的路径是库根目录，使用library_list_model
    if library_root and self._paths_equal(root, library_root):
        target_model = self._library_list_model
    
    # 对于物理相册（非库根），使用album_list_model
    should_prepare = True
    if target_model is self._library_list_model:
        # 优化：如果library模型已有数据，跳过prepare
        if (target_model.rowCount() > 0 and existing_root == album_root):
            should_prepare = False
    
    if should_prepare:
        target_model.prepare_for_album(album_root)  # 重置模型！
```

**关键冲突点**：当切换到物理相册时，由于 `root != library_root`，系统会：
1. 选择使用 `album_list_model`
2. 调用 `prepare_for_album()` **重置整个模型**
3. 清空所有已加载的行数据

#### 阶段2：模型重置（model.py:265-281）

```python
def prepare_for_album(self, root: Path) -> None:
    """Reset internal state so *root* becomes the active album."""
    self._controller.prepare_for_album(root)
    self._album_root = root
    
    self.beginResetModel()  # 通知视图即将重置
    self._state_manager.clear_rows()  # 清空所有行数据！
    self.endResetModel()  # 完成重置
    
    self._cache_manager.reset_for_album(root)
```

**此时UI显示空白网格**，因为模型已被清空。

#### 阶段3：数据重新加载（controller.py:163-238）

```python
def start_load(self) -> None:
    """Start loading assets for the current album root."""
    self._reset_buffers()
    self._is_first_chunk = True
    
    # 从磁盘索引重新读取数据
    self._data_loader.start(self._album_root, featured, filter_params=filter_params)
    
    # 注入live扫描结果
    live_items = self._facade.library_manager.get_live_scan_results(
        relative_to=self._album_root
    )
```

**UI卡死的根源**：

1. **数据加载器启动**：`AssetDataLoader` 开始从 `global_index.db` 读取该文件夹的资产
2. **Live扫描结果注入**：同时注入正在进行的后台扫描的临时结果
3. **双重数据流竞争**：
   - 磁盘索引的数据流（已完成的索引）
   - Live扫描的数据流（正在进行的实时扫描）
4. **去重检查开销**：对每个传入的数据块进行重复检查

```python
def _on_loader_chunk_ready(self, root: Path, chunk: List[Dict[str, object]]) -> None:
    unique_chunk = []
    for row in chunk:
        rel = row.get("rel")
        norm_rel = normalise_rel_value(rel)
        abs_key = str(abs_val) if abs_val else None
        
        # 检查是否已在模型中
        is_duplicate_in_model = self._duplication_checker(norm_rel, abs_key)
        # 检查是否已在待处理缓冲区中
        is_duplicate_in_buffer = (
            norm_rel in self._pending_rels
            or (abs_key and abs_key in self._pending_abs)
        )
        
        if not is_duplicate_in_model and not is_duplicate_in_buffer:
            unique_chunk.append(row)
```

#### 阶段4：UI响应性问题

**短暂可滚动的原因**：
- 在 `beginResetModel()` 和 `endResetModel()` 之间，Qt的模型/视图架构允许短暂的UI更新
- 第一批数据到达前的间隙期（~100ms），UI事件循环可以处理滚动事件

**卡死的原因**：
- 大量数据块同时到达（磁盘索引 + Live扫描）
- 每个数据块需要O(n)的去重检查
- 主线程被数据处理逻辑阻塞
- Qt事件循环无法及时处理UI事件

### 3. 为什么"All Photos"不卡死

当打开"All Photos"视图时：

```python
# navigation_controller.py:329-341
if is_same_root:
    # --- OPTIMIZED PATH (In-Memory) ---
    # 我们停留在同一个库中
    # 1. 跳过open_album()以防止模型销毁和重新加载
    # 2. 直接应用过滤器，这是唯一的开销
    self._asset_model.set_filter_mode(filter_mode)
    self._asset_model.ensure_chronological_order()
```

**优化路径**：
- 不调用 `open_album()`
- 不重置模型
- 不重新加载数据
- 只应用过滤器（如videos、live photos等）
- **数据已经在内存中**，无需从磁盘读取

## 修复方案

### 核心思路：索引共享与缓存复用

**目标**：避免在已索引的库根目录和其子文件夹之间切换时重复加载数据。

### 方案A：智能模型选择（推荐）

#### 1. 扩展路径匹配逻辑

修改 `facade.py` 中的 `open_album()` 方法：

```python
def open_album(self, root: Path) -> Optional[Album]:
    target_model = self._album_list_model
    library_root = self._library_manager.root() if self._library_manager else None
    
    # 新增：检查root是否是library的子目录
    is_library_descendant = False
    if library_root:
        if self._paths_equal(root, library_root):
            target_model = self._library_list_model
            is_library_descendant = True
        else:
            # 检查是否是库的子目录
            try:
                root.resolve().relative_to(library_root.resolve())
                # 如果没有抛出ValueError，说明是子目录
                target_model = self._library_list_model  # 使用同一个模型！
                is_library_descendant = True
            except (ValueError, OSError):
                # 不是子目录，使用独立的album模型
                target_model = self._album_list_model
    
    # 跳过prepare的条件更新
    should_prepare = True
    if is_library_descendant and target_model is self._library_list_model:
        existing_root = target_model.album_root()
        # 如果已经加载了库数据，不需要prepare
        if target_model.rowCount() > 0:
            should_prepare = False
```

#### 2. 增强过滤逻辑

在 `AssetListModel` 中添加路径过滤：

```python
def set_album_view_filter(self, album_root: Path) -> None:
    """Filter model to show only assets from a specific album subfolder."""
    self._album_root = album_root
    # 使用路径前缀过滤，而不是重新加载
    # 这需要在proxy model或者state manager中实现
```

#### 3. 优化导航控制器

修改 `navigation_controller.py` 中的 `open_album()` 方法：

```python
def open_album(self, path: Path) -> None:
    target_root = path.resolve()
    library_root = self._context.library.root()
    
    # 检查是否在同一个库内切换
    is_within_same_library = False
    if library_root:
        try:
            if target_root == library_root.resolve():
                is_within_same_library = True
            elif library_root.resolve() in target_root.parents:
                is_within_same_library = True
        except OSError:
            pass
    
    if is_within_same_library:
        # 优化路径：不重新扫描，只更新视图过滤
        self._facade.open_album_lightweight(path)
        self._static_selection = None
        # 应用路径过滤，而不是重新加载数据
        self._asset_model.filter_by_path_prefix(path)
        self._view_controller.show_gallery_view()
    else:
        # 标准路径：完整的打开流程
        album = self._facade.open_album(path)
        # ... existing code ...
```

### 方案B：增量视图更新（备选）

如果方案A实施复杂度过高，可以采用增量更新策略：

#### 1. 预缓存子目录数据

```python
class AssetCacheManager:
    def __init__(self, ...):
        self._subfolder_cache: Dict[Path, List[Dict]] = {}
    
    def cache_subfolder_assets(self, folder: Path, assets: List[Dict]) -> None:
        """Cache assets belonging to a specific subfolder."""
        self._subfolder_cache[folder] = assets
    
    def get_subfolder_assets(self, folder: Path) -> Optional[List[Dict]]:
        """Retrieve cached assets for a subfolder."""
        return self._subfolder_cache.get(folder)
```

#### 2. 快速模型切换

```python
def prepare_for_album_cached(self, root: Path) -> None:
    """Prepare for album using cached data if available."""
    cached = self._cache_manager.get_subfolder_assets(root)
    
    if cached:
        # 使用缓存数据快速填充
        self.beginResetModel()
        self._state_manager.clear_rows()
        self._state_manager.append_chunk(cached)
        self.endResetModel()
        
        # 后台验证数据是否仍然有效
        self._controller.verify_cached_data(root)
    else:
        # 标准流程
        self.prepare_for_album(root)
```

### 方案C：统一索引架构（长期方案）

重构索引系统，使用单一的全局索引模型：

1. **全局索引视图**：
   - 所有视图（All Photos、物理相册、Favorites等）共享同一个 `AssetListModel` 实例
   - 使用 `QSortFilterProxyModel` 实现不同的视图过滤

2. **路径基础过滤**：
   - 在 proxy model 中实现基于路径前缀的过滤
   - 切换相册只需更新过滤条件，不重置数据

3. **惰性加载优化**：
   - 只加载当前视图需要的数据
   - 使用虚拟滚动减少内存占用

```python
class UnifiedAssetModel(QAbstractListModel):
    """Unified model for all library views."""
    
    def set_view_context(self, context: ViewContext) -> None:
        """Update view context without resetting model."""
        self._context = context
        # 只通知数据变化，不重置
        self.dataChanged.emit(...)
```

## 实施建议

### 阶段1：快速修复（1-2天）

实施**方案A的核心部分**：

1. 修改 `facade.py::open_album()` 的模型选择逻辑
2. 为库的子文件夹使用 `library_list_model`
3. 添加基于路径的简单过滤

**预期效果**：
- 消除模型重置和重新加载
- UI保持响应
- 数据立即可用

### 阶段2：优化体验（3-5天）

1. 实现智能缓存管理
2. 优化去重算法（使用哈希集合而非线性查找）
3. 改进数据流控制，避免数据洪流

### 阶段3：架构重构（1-2周）

如果第一阶段效果不理想，考虑实施**方案C**：
- 统一索引架构
- 引入 proxy model 架构
- 重构视图层逻辑

## 测试验证

### 测试场景

1. **基础场景**：
   - 在"All Photos"浏览50张照片
   - 切换到包含这50张照片的物理相册
   - 验证：无卡顿，数据立即显示

2. **大数据集**：
   - 库包含10,000张照片
   - 物理相册包含1,000张照片
   - 验证：切换时间 < 100ms

3. **并发扫描**：
   - 后台正在扫描新文件夹
   - 同时切换到已索引的相册
   - 验证：UI响应流畅

### 性能指标

- **切换延迟**：< 100ms
- **UI响应时间**：< 16ms（60fps）
- **内存增长**：< 50MB（对于1000张照片）

## 总结

问题的根本原因是**双模型架构**在库根目录和子文件夹之间切换时，**不必要地重置模型并重新加载已索引的数据**。这导致：

1. 模型清空后短暂的UI响应
2. 数据重新加载时主线程阻塞
3. 去重检查带来的额外开销

**推荐方案**是扩展模型选择逻辑，让库的子文件夹也使用 `library_list_model`，并通过路径过滤而非数据重载来实现视图切换。这种方案：
- 实施简单
- 风险可控
- 效果显著
- 保持现有架构稳定性

后续可以根据实际效果决定是否需要更深层次的架构重构。
