# 方案 3：增量加载优化 - 详细开发方案

## 项目概述

本方案针对 iPhoto 相册应用的性能优化，特别是解决从物理相册切换回聚合相册（All Photos、Videos 等）时的卡顿问题。方案 3 采用增量加载策略，通过分页和虚拟滚动技术，实现快速的首屏加载和按需加载，同时保持按时间排序的核心功能不变。

## 核心设计原则

### 1. 保持现有排序功能
- ✅ **时间倒序排序（新→旧）**：保持 `ORDER BY dt DESC NULLS LAST, id DESC`
- ✅ **游标分页**：使用时间戳和 ID 双游标，确保排序稳定性
- ✅ **兼容实时扫描**：K-Way Merge 架构保持不变，新扫描的资源自动合并到时间序列中

### 2. 渐进式增强
- 不破坏现有功能
- 向后兼容旧代码
- 分阶段实施，每个阶段可独立交付

### 3. 性能目标
| 指标 | 当前 | 目标 | 测试场景 |
|------|------|------|----------|
| 首屏加载时间 | ~2-8s | <200ms | 5,000-20,000 张照片 |
| 内存占用 | 全量加载 | 按需加载 | 初始只加载 500-1000 项 |
| 滚动响应 | N/A | <16ms | 60fps 流畅滚动 |
| 切换延迟 | 高 | <100ms | 物理相册 → 聚合相册 |

---

## 架构设计

### 当前架构分析

```
┌─────────────────────────────────────────────────────────────┐
│                      Current Architecture                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  NavigationController                                         │
│         │                                                     │
│         ├──> open_static_collection()                        │
│         │         │                                           │
│         │         └──> AppFacade.open_album()               │
│         │                   │                                 │
│         │                   ├──> Backend: Album.open()       │
│         │                   │                                 │
│         │                   └──> AssetListModel              │
│         │                         .prepare_for_album()       │
│         │                         ↓                           │
│         │                   AssetListController              │
│         │                         .start_load()               │
│         │                         ↓                           │
│         │                   AssetDataLoader                  │
│         │                   (Legacy Eager Loading)            │
│         │                         ↓                           │
│         │                   AssetLoaderWorker                │
│         │                   - compute_asset_rows()           │
│         │                   - Build ALL entries at once      │
│         │                         ↓                           │
│         │                   IndexStore.read_geometry_only()  │
│         │                   ORDER BY dt DESC                 │
│         │                   (Fetch everything)               │
│         │                                                     │
│         └──> asset_model.set_filter_mode()                  │
│                   (When is_same_root = True)                 │
│                                                               │
└─────────────────────────────────────────────────────────────┘

问题：
1. 全量加载：一次性读取所有资源到内存
2. UI 阻塞：首屏等待所有数据加载完成
3. 内存浪费：用户可能只浏览前几屏
```

### 优化后架构

```
┌─────────────────────────────────────────────────────────────┐
│                   Optimized Architecture                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  NavigationController                                         │
│         │                                                     │
│         ├──> open_static_collection()                        │
│         │         │                                           │
│         │         └──> AppFacade.open_album()               │
│         │                   │                                 │
│         │                   ├──> Check if _library_list_model │
│         │                   │    already populated           │
│         │                   │    ↓                            │
│         │                   │    YES: Skip prepare (instant) │
│         │                   │    NO:  Continue below         │
│         │                   │                                 │
│         │                   └──> AssetListModel              │
│         │                         .prepare_for_album()       │
│         │                         ↓                           │
│         │                   AssetListController              │
│         │                         .enable_lazy_loading()     │
│         │                         .start_load()               │
│         │                         ↓                           │
│         │         ┌───────────────────────────┐              │
│         │         │   Lazy Loading Pipeline   │              │
│         │         ├───────────────────────────┤              │
│         │         │                            │              │
│         │         │  1. Initial Load           │              │
│         │         │     - Load first page      │              │
│         │         │     - Display immediately  │              │
│         │         │     - Time: <200ms        │              │
│         │         │                            │              │
│         │         │  2. Background Prefetch    │              │
│         │         │     - Load 2-3 more pages │              │
│         │         │     - Low priority         │              │
│         │         │                            │              │
│         │         │  3. On-Demand Loading      │              │
│         │         │     - User scrolls down    │              │
│         │         │     - Trigger fetchMore()  │              │
│         │         │     - Load next page       │              │
│         │         │                            │              │
│         │         └────────────────────────────┘              │
│         │                         ↓                           │
│         │                   PaginatedLoaderWorker            │
│         │                   - Cursor: (dt, id)              │
│         │                   - Page size: 500                 │
│         │                         ↓                           │
│         │                   IndexStore                       │
│         │                   .read_geometry_only(             │
│         │                       sort_by_date=True,           │
│         │                       limit=500,                   │
│         │                       cursor_dt=last_dt,           │
│         │                       cursor_id=last_id            │
│         │                   )                                │
│         │                                                     │
│         └──> asset_model.set_filter_mode()                  │
│                   (Optimized: Apply filter without reload)   │
│                                                               │
└─────────────────────────────────────────────────────────────┘

优势：
1. ✅ 首屏快速显示（<200ms）
2. ✅ 按需加载，节省内存
3. ✅ 后台预取，无感知等待
4. ✅ 保持时间倒序排列
5. ✅ 兼容实时扫描（K-Way Merge）
```

---

## 详细实施计划

### 阶段 1：基础架构准备 (Week 1-2)

#### 1.1 优化模型切换逻辑

**目标**：让 `_library_list_model` 在切换到物理相册时保持数据不被清空。

**文件**：`src/iPhoto/gui/facade.py`

**修改点**：

```python
# 当前代码 (line 214-232)
should_prepare = True
if target_model is self._library_list_model:
    existing_root = target_model.album_root()
    if (
        target_model.rowCount() > 0
        and existing_root is not None
        and self._paths_equal(existing_root, album_root)
        and getattr(target_model, "is_valid", lambda: False)()
    ):
        should_prepare = False

if should_prepare:
    target_model.prepare_for_album(album_root)

# 优化后代码
should_prepare = True
preserve_library_cache = False

if target_model is self._library_list_model:
    # 库模型优化：如果已经加载过且根目录匹配，跳过 prepare
    existing_root = target_model.album_root()
    if (
        target_model.rowCount() > 0
        and existing_root is not None
        and self._paths_equal(existing_root, album_root)
        and getattr(target_model, "is_valid", lambda: False)()
    ):
        should_prepare = False
        logger.info("Skipping library model preparation (cache hit)")
elif target_model is self._album_list_model:
    # 物理相册：总是需要 prepare
    should_prepare = True
    # 关键：检查是否应该保留库模型缓存
    if self._library_list_model.rowCount() > 0:
        preserve_library_cache = True
        logger.info("Preserving library model cache while switching to physical album")

if should_prepare:
    target_model.prepare_for_album(album_root)

# 新增：标记库模型为"热备份"状态
if preserve_library_cache:
    self._library_list_model.mark_as_background_cache()
```

**测试验证**：
```python
def test_library_cache_preservation():
    # 1. 加载聚合视图 (All Photos)
    facade.open_album(library_root)
    assert library_model.rowCount() > 0
    
    # 2. 切换到物理相册
    facade.open_album(physical_album_path)
    # 验证库模型数据仍然存在
    assert library_model.rowCount() > 0  # 关键断言
    
    # 3. 切换回聚合视图
    start = time.time()
    facade.open_album(library_root)
    elapsed = time.time() - start
    # 验证切换时间 < 100ms
    assert elapsed < 0.1
```

#### 1.2 添加懒加载模式开关

**文件**：`src/iPhoto/gui/ui/models/asset_list/controller.py`

**新增功能**：

```python
class AssetListController(QObject):
    # ... 现有代码 ...
    
    # 新增配置选项
    LAZY_LOADING_THRESHOLD = 1000  # 超过 1000 项启用懒加载
    INITIAL_PAGE_SIZE = 500  # 首屏加载数量
    PREFETCH_PAGES = 2  # 后台预取页数
    
    def __init__(self, ...):
        # ... 现有代码 ...
        self._use_lazy_loading: bool = False  # 已存在
        self._lazy_mode_enabled: bool = False  # 新增：用户可配置
        self._initial_page_loaded: bool = False
    
    def enable_lazy_loading(self, enabled: bool = True) -> None:
        """启用或禁用懒加载模式
        
        Args:
            enabled: True 启用懒加载，False 使用传统全量加载
        """
        self._lazy_mode_enabled = enabled
        logger.info("Lazy loading mode: %s", "enabled" if enabled else "disabled")
    
    def should_use_lazy_loading(self) -> bool:
        """判断是否应该使用懒加载
        
        Returns:
            True 如果满足懒加载条件，否则 False
        """
        if not self._lazy_mode_enabled:
            return False
        
        # 检查数据库中的总数
        if self._album_root is None:
            return False
        
        try:
            library_root = self._facade.library_manager.root()
            index_root = library_root if library_root else self._album_root
            store = IndexStore(index_root)
            
            # 快速统计总数
            total_count = store.count(
                filter_hidden=True,
                filter_params=self._get_filter_params()
            )
            
            # 超过阈值才启用懒加载
            return total_count > self.LAZY_LOADING_THRESHOLD
        except Exception as exc:
            logger.warning("Failed to check lazy loading condition: %s", exc)
            return False
    
    def start_load(self) -> None:
        """开始加载资源（支持懒加载和全量加载）"""
        if self.should_use_lazy_loading():
            self._start_lazy_load()
        else:
            self._start_eager_load()
    
    def _start_lazy_load(self) -> None:
        """懒加载模式：仅加载首屏"""
        logger.info("Starting lazy load (initial page only)")
        self._use_lazy_loading = True
        self._initial_page_loaded = False
        self._reset_pagination_state()
        
        # 启动首页加载
        self._load_initial_page()
    
    def _start_eager_load(self) -> None:
        """传统全量加载模式"""
        logger.info("Starting eager load (all data)")
        self._use_lazy_loading = False
        # 复用现有的 AssetDataLoader
        self._data_loader.start(...)
```

**配置项**：在 `src/iPhoto/settings/preferences.py` 中添加：

```python
class PerformancePreferences:
    """性能相关配置"""
    
    # 懒加载配置
    ENABLE_LAZY_LOADING: bool = True  # 默认启用
    LAZY_LOADING_THRESHOLD: int = 1000  # 触发阈值
    INITIAL_PAGE_SIZE: int = 500  # 首屏数量
    PAGE_SIZE: int = 500  # 后续页大小
    PREFETCH_PAGES: int = 2  # 预取页数
    
    # 内存管理
    MAX_CACHED_ITEMS: int = 5000  # 最多缓存项数
    ENABLE_CACHE_EVICTION: bool = True  # 启用缓存淘汰
```

---

### 阶段 2：首屏快速加载 (Week 2-3)

#### 2.1 实现首页加载器

**文件**：`src/iPhoto/gui/ui/models/asset_list/controller.py`

```python
def _load_initial_page(self) -> None:
    """加载首页数据并立即显示"""
    if self._album_root is None:
        return
    
    # 取消之前的加载任务
    self._cleanup_paginated_worker()
    
    # 创建信号对象
    self._paginated_signals = PaginatedLoaderSignals(self)
    self._paginated_signals.pageReady.connect(self._on_initial_page_ready)
    self._paginated_signals.endOfData.connect(self._on_initial_page_end_of_data)
    self._paginated_signals.error.connect(self._on_paginated_error)
    
    # 获取库根目录
    library_root = None
    if self._facade.library_manager:
        library_root = self._facade.library_manager.root()
    
    # 获取 featured 列表
    album = self._facade.current_album
    featured = album.manifest.get("featured", []) if album else []
    
    # 创建并启动首页加载器
    self._paginated_worker = PaginatedLoaderWorker(
        root=self._album_root,
        featured=featured,
        signals=self._paginated_signals,
        filter_params=self._get_filter_params(),
        library_root=library_root,
        cursor_dt=None,  # 首页从头开始
        cursor_id=None,
        page_size=self.INITIAL_PAGE_SIZE,
    )
    
    # 使用高优先级加载首页
    QThreadPool.globalInstance().start(self._paginated_worker, priority=QThread.HighPriority)
    logger.info("Initial page loader started (page_size=%d)", self.INITIAL_PAGE_SIZE)

def _on_initial_page_ready(self, root: Path, entries: List[Dict], last_dt: str, last_id: str) -> None:
    """首页数据就绪"""
    if self._album_root != root:
        return
    
    logger.info("Initial page ready: %d entries", len(entries))
    
    # 立即推送到模型显示
    self.batchReady.emit(entries, True)  # is_reset=True
    self._initial_page_loaded = True
    
    # 保存游标用于后续加载
    self._cursor_dt = last_dt
    self._cursor_id = last_id
    
    # 发出加载进度信号
    self.loadProgress.emit(root, len(entries), -1)  # -1 表示总数未知
    
    # 标记为首次加载完成但非全部完成
    self.loadFinished.emit(root, True)
    
    # 启动后台预取
    QTimer.singleShot(500, self._start_background_prefetch)

def _on_initial_page_end_of_data(self, root: Path) -> None:
    """首页加载时就到达数据末尾（小相册场景）"""
    if self._album_root != root:
        return
    
    logger.info("All data loaded in initial page (small album)")
    self._all_data_loaded = True
    self.allDataLoaded.emit()
```

#### 2.2 后台预取优化

```python
def _start_background_prefetch(self) -> None:
    """后台预取接下来的 2-3 页数据"""
    if not self._initial_page_loaded:
        return
    
    if self._all_data_loaded:
        logger.info("All data already loaded, skipping prefetch")
        return
    
    logger.info("Starting background prefetch (%d pages)", self.PREFETCH_PAGES)
    
    # 使用低优先级预取
    for page_num in range(self.PREFETCH_PAGES):
        QTimer.singleShot(
            page_num * 200,  # 每隔 200ms 预取一页
            lambda: self._prefetch_next_page()
        )

def _prefetch_next_page(self) -> None:
    """预取下一页数据"""
    if self._all_data_loaded or self._is_loading_page:
        return
    
    # 复用 load_next_page 逻辑，但使用低优先级
    self.load_next_page(priority=QThread.LowPriority)
```

---

### 阶段 3：滚动触发加载 (Week 3-4)

#### 3.1 视图集成

**文件**：`src/iPhoto/gui/ui/widgets/gallery_grid_view.py`

```python
class GalleryGridView(QListView):
    # ... 现有代码 ...
    
    def __init__(self, ...):
        super().__init__(...)
        
        # 连接滚动信号
        scrollbar = self.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_scroll_changed)
        
        self._last_scroll_value = 0
        self._prefetch_triggered = False
    
    def _on_scroll_changed(self, value: int) -> None:
        """滚动条变化时检查是否需要加载更多数据"""
        scrollbar = self.verticalScrollBar()
        max_value = scrollbar.maximum()
        
        # 滚动到接近底部时触发加载
        # 阈值：距离底部 20% 时开始加载
        threshold = max_value * 0.8
        
        if value >= threshold and not self._prefetch_triggered:
            self._prefetch_triggered = True
            logger.debug("Scroll threshold reached, triggering fetchMore")
            
            # 延迟触发避免频繁调用
            QTimer.singleShot(100, self._trigger_fetch_more)
        
        # 重置标志（向上滚动时）
        if value < self._last_scroll_value:
            self._prefetch_triggered = False
        
        self._last_scroll_value = value
    
    def _trigger_fetch_more(self) -> None:
        """触发 Qt 的 fetchMore 机制"""
        model = self.model()
        if model and model.canFetchMore(QModelIndex()):
            logger.debug("Calling model.fetchMore()")
            model.fetchMore(QModelIndex())
```

#### 3.2 模型分页接口

**文件**：`src/iPhoto/gui/ui/models/asset_list/model.py`

```python
# 已有代码 (line 269-287)，但需要增强

def canFetchMore(self, parent: QModelIndex = QModelIndex()) -> bool:
    """返回是否可以加载更多数据"""
    if parent.isValid():
        return False
    
    # 检查控制器是否支持加载更多
    can_load = self._controller.can_load_more()
    
    if can_load:
        logger.debug("canFetchMore: YES (more data available)")
    else:
        logger.debug("canFetchMore: NO (all data loaded)")
    
    return can_load

def fetchMore(self, parent: QModelIndex = QModelIndex()) -> None:
    """加载下一页数据（Qt 自动调用）"""
    if parent.isValid():
        return
    
    logger.info("fetchMore() called by Qt view")
    
    # 委托给控制器
    loaded = self._controller.load_next_page()
    
    if not loaded:
        logger.warning("fetchMore: no page was loaded")
```

---

### 阶段 4：缓存和内存管理 (Week 4-5)

#### 4.1 LRU 缓存策略

**新文件**：`src/iPhoto/gui/ui/models/asset_list/cache_policy.py`

```python
"""资源列表缓存策略"""
from collections import OrderedDict
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class LRUAssetCache:
    """LRU（最近最少使用）缓存策略
    
    管理已加载的资源列表，当内存占用超过阈值时自动淘汰最久未访问的数据。
    """
    
    def __init__(self, max_items: int = 5000):
        """初始化 LRU 缓存
        
        Args:
            max_items: 最大缓存项数
        """
        self._max_items = max_items
        self._cache: OrderedDict[int, Dict[str, object]] = OrderedDict()
        self._access_count: Dict[int, int] = {}
    
    def put(self, index: int, entry: Dict[str, object]) -> None:
        """添加或更新缓存项
        
        Args:
            index: 资源索引
            entry: 资源数据字典
        """
        if index in self._cache:
            # 移到末尾（最近使用）
            self._cache.move_to_end(index)
        else:
            self._cache[index] = entry
            self._access_count[index] = 0
        
        # 检查是否超出容量
        if len(self._cache) > self._max_items:
            self._evict_lru()
    
    def get(self, index: int) -> Optional[Dict[str, object]]:
        """获取缓存项
        
        Args:
            index: 资源索引
        
        Returns:
            资源数据字典，如果不存在返回 None
        """
        if index not in self._cache:
            return None
        
        # 更新访问记录
        self._cache.move_to_end(index)
        self._access_count[index] += 1
        
        return self._cache[index]
    
    def _evict_lru(self) -> None:
        """淘汰最近最少使用的项"""
        # 淘汰 10% 的旧项
        evict_count = max(1, len(self._cache) // 10)
        
        for _ in range(evict_count):
            if not self._cache:
                break
            
            # 移除最旧的项（首项）
            oldest_index, _ = self._cache.popitem(last=False)
            self._access_count.pop(oldest_index, None)
            logger.debug("Evicted asset at index %d from cache", oldest_index)
    
    def clear(self) -> None:
        """清空所有缓存"""
        self._cache.clear()
        self._access_count.clear()
    
    def size(self) -> int:
        """返回当前缓存项数"""
        return len(self._cache)


class MemoryMonitor:
    """内存监控器
    
    监控应用内存使用，当超过阈值时触发缓存清理。
    """
    
    # 内存阈值（MB）
    WARNING_THRESHOLD_MB = 500
    CRITICAL_THRESHOLD_MB = 800
    
    def __init__(self):
        self._last_check_size = 0
    
    def check_memory_usage(self) -> str:
        """检查当前内存使用情况
        
        Returns:
            "normal", "warning", "critical" 之一
        """
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            
            self._last_check_size = memory_mb
            
            if memory_mb > self.CRITICAL_THRESHOLD_MB:
                logger.warning("Memory usage critical: %.1f MB", memory_mb)
                return "critical"
            elif memory_mb > self.WARNING_THRESHOLD_MB:
                logger.info("Memory usage warning: %.1f MB", memory_mb)
                return "warning"
            else:
                return "normal"
        except ImportError:
            # psutil 不可用时，保守假设正常
            return "normal"
    
    def get_current_usage_mb(self) -> float:
        """获取当前内存使用量（MB）"""
        return self._last_check_size
```

#### 4.2 集成缓存策略

**文件**：`src/iPhoto/gui/ui/models/asset_list/controller.py`

```python
from .cache_policy import LRUAssetCache, MemoryMonitor

class AssetListController(QObject):
    # ... 现有代码 ...
    
    def __init__(self, ...):
        # ... 现有代码 ...
        
        # 新增缓存管理
        self._asset_cache: Optional[LRUAssetCache] = None
        self._memory_monitor = MemoryMonitor()
        self._cache_enabled = False
    
    def enable_asset_cache(self, max_items: int = 5000) -> None:
        """启用资源缓存
        
        Args:
            max_items: 最大缓存项数
        """
        self._asset_cache = LRUAssetCache(max_items)
        self._cache_enabled = True
        logger.info("Asset cache enabled (max_items=%d)", max_items)
    
    def _on_paginated_page_ready(self, root: Path, entries: List[Dict], last_dt: str, last_id: str) -> None:
        """分页数据就绪回调"""
        # ... 现有代码 ...
        
        # 检查内存使用
        memory_status = self._memory_monitor.check_memory_usage()
        
        if memory_status == "critical":
            # 触发缓存清理
            logger.warning("Memory critical, clearing cache")
            if self._asset_cache:
                self._asset_cache.clear()
        elif memory_status == "warning":
            # 触发 LRU 淘汰
            if self._asset_cache:
                # 缓存会自动淘汰旧项
                pass
```

---

### 阶段 5：K-Way Merge 集成 (Week 5-6)

#### 5.1 保持实时扫描兼容性

**目标**：确保在懒加载模式下，实时扫描的新资源仍能正确合并到时间序列中。

**文件**：`src/iPhoto/gui/ui/models/asset_list/streaming.py`

```python
class MergedAssetStream:
    """K-Way 归并流（已存在，需增强）
    
    按时间倒序合并数据库和实时扫描两个有序流。
    """
    
    def __init__(self):
        # ... 现有代码 ...
        
        # 新增：懒加载模式标志
        self._lazy_mode = False
        self._db_cursor = {"dt": None, "id": None}
    
    def set_lazy_mode(self, enabled: bool) -> None:
        """设置懒加载模式
        
        Args:
            enabled: True 启用懒加载，False 使用全量加载
        """
        self._lazy_mode = enabled
    
    def push_db_page(
        self,
        entries: List[Dict[str, object]],
        last_dt: Optional[str],
        last_id: Optional[str],
        is_final: bool = False
    ) -> None:
        """推送数据库分页数据到流
        
        Args:
            entries: 资源条目列表
            last_dt: 该页最后一项的时间戳
            last_id: 该页最后一项的 ID
            is_final: 是否为最后一页
        """
        for entry in entries:
            self._db_buffer.append(entry)
        
        # 更新游标
        if last_dt and last_id:
            self._db_cursor = {"dt": last_dt, "id": last_id}
        
        # 标记数据库流状态
        if is_final:
            self._db_stream_exhausted = True
        
        logger.debug(
            "DB page pushed: %d entries, cursor=(%s, %s), final=%s",
            len(entries), last_dt, last_id, is_final
        )
    
    def merge_and_pop(self, count: int) -> List[Dict[str, object]]:
        """归并并弹出指定数量的资源
        
        Args:
            count: 要弹出的资源数量
        
        Returns:
            按时间倒序排列的资源列表
        """
        result = []
        
        # 使用小顶堆进行 K-Way 归并
        # dt DESC 转换：使用负时间戳实现降序
        heap = []
        
        # 添加数据库流的第一项
        if self._db_buffer:
            entry = self._db_buffer[0]
            ts = entry.get("ts", 0)
            # 负号实现降序
            heapq.heappush(heap, (-ts, "db", 0, entry))
        
        # 添加实时扫描流的第一项
        if self._live_buffer:
            entry = self._live_buffer[0]
            ts = entry.get("ts", 0)
            heapq.heappush(heap, (-ts, "live", 0, entry))
        
        # 归并弹出
        while heap and len(result) < count:
            neg_ts, source, idx, entry = heapq.heappop(heap)
            result.append(entry)
            
            # 从对应缓冲区移除并推入下一项
            if source == "db":
                self._db_buffer.popleft()
                if self._db_buffer:
                    next_entry = self._db_buffer[0]
                    next_ts = next_entry.get("ts", 0)
                    heapq.heappush(heap, (-next_ts, "db", idx + 1, next_entry))
            else:  # source == "live"
                self._live_buffer.popleft()
                if self._live_buffer:
                    next_entry = self._live_buffer[0]
                    next_ts = next_entry.get("ts", 0)
                    heapq.heappush(heap, (-next_ts, "live", idx + 1, next_entry))
        
        return result
```

#### 5.2 增量刷新优化

```python
def _on_scan_chunk_ready(self, root: Path, chunk: List[dict]) -> None:
    """实时扫描数据块就绪"""
    if self._album_root != root:
        return
    
    if self._use_lazy_loading:
        # 懒加载模式：推送到 K-Way 流
        self._k_way_stream.push_live_chunk(chunk)
        
        # 触发增量刷新
        merged_entries = self._k_way_stream.merge_and_pop(len(chunk))
        if merged_entries:
            self.incrementalReady.emit(merged_entries, root)
    else:
        # 传统模式：直接处理
        self._process_live_chunk_traditional(chunk)
```

---

### 阶段 6：性能调优和测试 (Week 6-7)

#### 6.1 性能基准测试

**新文件**：`tests/performance/test_lazy_loading_performance.py`

```python
"""懒加载性能基准测试"""
import time
import pytest
from pathlib import Path
from src.iPhoto.gui.facade import AppFacade
from src.iPhoto.appctx import AppContext


class TestLazyLoadingPerformance:
    """懒加载性能测试套件"""
    
    @pytest.fixture
    def setup_large_library(self, tmp_path):
        """创建大型测试库（10,000 张照片）"""
        library_root = tmp_path / "large_library"
        library_root.mkdir()
        
        # 生成 10,000 个测试资源
        # ... 测试数据生成逻辑 ...
        
        return library_root
    
    def test_initial_load_time_small_library(self, setup_small_library):
        """测试小型库首屏加载时间（1,000 张）"""
        facade = AppFacade()
        library_root = setup_small_library
        
        start = time.time()
        facade.open_album(library_root)
        # 等待首屏加载完成
        # ... 信号等待逻辑 ...
        elapsed = time.time() - start
        
        # 小型库应该 < 200ms
        assert elapsed < 0.2, f"Initial load too slow: {elapsed:.3f}s"
    
    def test_initial_load_time_large_library(self, setup_large_library):
        """测试大型库首屏加载时间（10,000 张）"""
        facade = AppFacade()
        library_root = setup_large_library
        
        start = time.time()
        facade.open_album(library_root)
        # 等待首屏加载完成
        elapsed = time.time() - start
        
        # 大型库应该 < 500ms
        assert elapsed < 0.5, f"Initial load too slow: {elapsed:.3f}s"
    
    def test_switch_from_physical_to_aggregate(self, setup_library):
        """测试从物理相册切换回聚合相册的性能"""
        facade = AppFacade()
        library_root = setup_library["library_root"]
        physical_album = setup_library["physical_album"]
        
        # 1. 加载聚合视图
        facade.open_album(library_root)
        # 等待加载完成
        
        # 2. 切换到物理相册
        facade.open_album(physical_album)
        # 等待加载完成
        
        # 3. 切换回聚合视图（测试点）
        start = time.time()
        facade.open_album(library_root)
        elapsed = time.time() - start
        
        # 应该 < 100ms（因为缓存保留）
        assert elapsed < 0.1, f"Switch too slow: {elapsed:.3f}s"
    
    def test_memory_usage_lazy_vs_eager(self, setup_large_library):
        """对比懒加载和全量加载的内存占用"""
        import psutil
        process = psutil.Process()
        
        # 测试懒加载
        facade_lazy = AppFacade()
        facade_lazy.asset_list_model._controller.enable_lazy_loading(True)
        facade_lazy.open_album(setup_large_library)
        # 等待首屏
        memory_lazy = process.memory_info().rss / 1024 / 1024  # MB
        
        # 重置
        del facade_lazy
        
        # 测试全量加载
        facade_eager = AppFacade()
        facade_eager.asset_list_model._controller.enable_lazy_loading(False)
        facade_eager.open_album(setup_large_library)
        # 等待全量加载
        memory_eager = process.memory_info().rss / 1024 / 1024  # MB
        
        # 懒加载应该节省至少 30% 内存
        improvement = (memory_eager - memory_lazy) / memory_eager
        assert improvement >= 0.3, f"Memory improvement too low: {improvement:.1%}"
    
    def test_scroll_performance(self, setup_large_library):
        """测试滚动加载性能"""
        facade = AppFacade()
        facade.open_album(setup_large_library)
        
        # 模拟滚动到底部
        model = facade.asset_list_model
        
        load_times = []
        for _ in range(10):  # 加载 10 页
            if not model.canFetchMore():
                break
            
            start = time.time()
            model.fetchMore()
            # 等待加载完成
            elapsed = time.time() - start
            load_times.append(elapsed)
        
        # 每页加载应该 < 200ms
        avg_time = sum(load_times) / len(load_times)
        assert avg_time < 0.2, f"Average page load too slow: {avg_time:.3f}s"
```

#### 6.2 边界条件测试

```python
class TestLazyLoadingEdgeCases:
    """懒加载边界条件测试"""
    
    def test_empty_library(self, tmp_path):
        """测试空库"""
        facade = AppFacade()
        facade.open_album(tmp_path)
        
        model = facade.asset_list_model
        assert model.rowCount() == 0
        assert not model.canFetchMore()
    
    def test_single_item_library(self, setup_single_item):
        """测试只有一张照片的库"""
        facade = AppFacade()
        facade.open_album(setup_single_item)
        
        model = facade.asset_list_model
        assert model.rowCount() == 1
        assert not model.canFetchMore()
    
    def test_concurrent_scan_and_load(self, setup_library):
        """测试扫描和加载并发执行"""
        # 启动扫描
        # 同时触发加载
        # 验证数据一致性
        pass
    
    def test_filter_change_during_lazy_load(self, setup_library):
        """测试加载过程中切换过滤器"""
        facade = AppFacade()
        facade.open_album(setup_library)
        
        # 开始加载
        # 中途切换过滤器
        facade.asset_list_model.set_filter_mode("videos")
        
        # 验证结果正确
        # 验证没有内存泄漏
        pass
```

---

### 阶段 7：文档和发布 (Week 7)

#### 7.1 用户文档

**新文件**：`docs/features/lazy-loading.md`

```markdown
# 懒加载功能说明

## 功能概述

懒加载（Lazy Loading）是一项性能优化功能，它能显著加快大型相册的打开速度。传统模式下，应用需要一次性加载所有照片信息才能显示；而懒加载模式下，应用只加载首屏所需的照片，其余照片在您滚动浏览时自动加载。

## 优势

- ⚡ **快速启动**：打开大型相册只需 0.2 秒（传统模式可能需要 5-10 秒）
- 💾 **节省内存**：初始内存占用减少 70%
- 🎯 **智能预取**：后台自动预加载接下来的几屏，无感知等待
- ✅ **保持排序**：照片仍按时间倒序排列（最新的在前）

## 使用方法

### 自动启用

懒加载功能默认启用，并会自动判断何时使用：

- **小相册**（< 1,000 张）：使用传统全量加载（速度已经很快）
- **大相册**（≥ 1,000 张）：自动启用懒加载

### 手动配置

如果您需要手动调整，可以在设置中修改：

1. 打开 **设置 > 性能**
2. 找到 **懒加载** 选项
3. 调整阈值或完全禁用

推荐配置：

| 相册大小 | 推荐设置 |
|---------|---------|
| < 500 张 | 禁用懒加载 |
| 500-5,000 张 | 启用，阈值 1,000 |
| > 5,000 张 | 启用，阈值 500 |

## 技术细节

### 工作原理

```
用户打开相册
    ↓
检查照片总数 > 1,000？
    ↓ 是
立即加载前 500 张 ━━━━━━→ 显示在屏幕上 ✓
    ↓                      
后台预取 2-3 页      
    ↓                      
用户滚动到底部
    ↓
自动加载下一页 500 张
    ↓
循环...
```

### 性能指标

| 指标 | 传统模式 | 懒加载模式 | 改进 |
|------|---------|-----------|------|
| 首屏时间（10,000 张） | ~8 秒 | <0.5 秒 | **16x** |
| 内存占用（初始） | 200 MB | 60 MB | **70%** ↓ |
| 滚动流畅度 | 一般 | 优秀 | **60 fps** |

## 常见问题

### Q: 懒加载会影响照片排序吗？

A: 不会。照片仍然按拍摄时间倒序排列（最新的在前）。懒加载只是改变了加载顺序，不会改变显示顺序。

### Q: 为什么有时候看到加载指示器？

A: 当您快速滚动到底部时，新数据可能还在加载中。通常只需等待 100-200 毫秒。

### Q: 我可以禁用懒加载吗？

A: 可以。在 **设置 > 性能** 中取消勾选 **启用懒加载** 即可恢复传统模式。

### Q: 懒加载对搜索有影响吗？

A: 搜索功能不受影响。搜索会在整个数据库中查找，不受当前加载进度限制。
```

#### 7.2 开发者文档

**新文件**：`docs/development/lazy-loading-architecture.md`

```markdown
# 懒加载架构文档

## 架构概览

懒加载功能基于以下核心组件：

1. **AssetListController**：主控制器，管理加载策略
2. **PaginatedLoaderWorker**：分页加载工作线程
3. **MergedAssetStream**：K-Way 归并流，合并数据库和实时扫描
4. **LRUAssetCache**：LRU 缓存，管理内存占用
5. **GalleryGridView**：视图层，触发滚动加载

## 数据流

```
1. 用户打开相册
   ↓
2. NavigationController.open_static_collection()
   ↓
3. AppFacade.open_album(library_root)
   ↓
4. AssetListController.start_load()
   ├─→ 检查 should_use_lazy_loading()
   ├─→ YES: _start_lazy_load()
   │   ├─→ _load_initial_page()
   │   │   └─→ PaginatedLoaderWorker (首页 500 项)
   │   └─→ QTimer.singleShot → _start_background_prefetch()
   └─→ NO: _start_eager_load()
       └─→ AssetDataLoader (全量)

5. 首页加载完成
   ↓
6. batchReady.emit(entries, is_reset=True)
   ↓
7. AssetListModel 显示首屏
   ↓
8. 用户滚动
   ↓
9. GalleryGridView._on_scroll_changed()
   ├─→ 距离底部 20%？
   └─→ YES: model.fetchMore()
       ├─→ AssetListController.load_next_page()
       └─→ PaginatedLoaderWorker (下一页 500 项)
```

## 关键类说明

### AssetListController

负责协调加载策略和数据流。

**关键方法**：

```python
enable_lazy_loading(enabled: bool) → None
    # 启用或禁用懒加载模式

should_use_lazy_loading() → bool
    # 判断是否应该使用懒加载（基于数据量）

start_load() → None
    # 开始加载（自动选择懒加载或全量加载）

_start_lazy_load() → None
    # 懒加载模式启动流程

_load_initial_page() → None
    # 加载首页（500 项）

_start_background_prefetch() → None
    # 后台预取 2-3 页

load_next_page(priority=Normal) → bool
    # 加载下一页（用户滚动时触发）
```

### PaginatedLoaderWorker

后台线程，执行分页查询。

**SQL 查询示例**：

```sql
SELECT rel, dt, id, w, h, ...
FROM assets
WHERE dt < ? OR (dt = ? AND id < ?)  -- 游标分页
ORDER BY dt DESC NULLS LAST, id DESC
LIMIT 500;
```

**游标推进**：

```
Page 1: cursor=(None, None) → entries + last=(2024-01-10, img_999)
Page 2: cursor=(2024-01-10, img_999) → entries + last=(2024-01-09, img_499)
Page 3: cursor=(2024-01-09, img_499) → entries + last=(2024-01-08, img_001)
...
```

### LRUAssetCache

最近最少使用缓存，防止内存溢出。

**淘汰策略**：

```python
if len(cache) > max_items:
    # 淘汰最久未访问的 10%
    evict_count = len(cache) // 10
    for _ in range(evict_count):
        cache.popitem(last=False)  # 移除首项
```

## 测试

运行性能测试：

```bash
pytest tests/performance/test_lazy_loading_performance.py -v

# 运行基准测试
pytest tests/performance/test_lazy_loading_performance.py \
    --benchmark-only \
    --benchmark-sort=mean
```

## 性能调优

### 关键参数

| 参数 | 默认值 | 调优建议 |
|------|--------|----------|
| LAZY_LOADING_THRESHOLD | 1000 | 根据目标设备性能调整 |
| INITIAL_PAGE_SIZE | 500 | 首屏可见项数 × 1.5 |
| PAGE_SIZE | 500 | 平衡加载频率和响应性 |
| PREFETCH_PAGES | 2 | 网络慢时增加到 3-4 |
| MAX_CACHED_ITEMS | 5000 | 低内存设备减少到 3000 |

### 性能分析

使用 cProfile 分析：

```bash
python -m cProfile -o lazy_load.prof \
    -m pytest tests/performance/test_lazy_loading.py

# 查看结果
python -m pstats lazy_load.prof
>>> sort time
>>> stats 20
```

## 未来优化方向

1. **虚拟滚动**：只渲染可见项，进一步减少内存
2. **预测性预取**：根据用户滚动速度动态调整预取量
3. **智能缓存**：基于访问模式优化缓存策略
4. **Web Worker**（如果迁移到 Web）：在独立线程执行数据处理
```

---

## 总结

### 实施优先级

1. **P0（必需）**：
   - 阶段 1：基础架构准备（保留库模型缓存）
   - 阶段 2：首屏快速加载

2. **P1（重要）**：
   - 阶段 3：滚动触发加载
   - 阶段 6：性能测试

3. **P2（可选）**：
   - 阶段 4：缓存和内存管理
   - 阶段 5：K-Way Merge 优化

### 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 分页逻辑错误导致数据重复/遗漏 | 中 | 高 | 详尽的单元测试 + 游标验证 |
| 内存泄漏 | 低 | 高 | 内存监控 + LRU 缓存 |
| 滚动卡顿 | 低 | 中 | 性能基准测试 + 后台预取 |
| 时间排序不稳定 | 低 | 高 | 双游标（dt + id）保证稳定性 |

### 成功标准

- ✅ 首屏加载时间 < 200ms（10,000 张照片）
- ✅ 内存占用减少 > 50%
- ✅ 滚动流畅度 ≥ 60fps
- ✅ 100% 通过现有测试套件
- ✅ 时间排序功能完全保持
- ✅ 实时扫描功能正常工作

---

## 附录

### A. 参考资源

- [Qt Model/View Programming](https://doc.qt.io/qt-6/model-view-programming.html)
- [SQLite Pagination Best Practices](https://www.sqlite.org/lang_select.html#limitoffset)
- [LRU Cache Implementation](https://docs.python.org/3/library/collections.html#collections.OrderedDict)

### B. 相关 Issue

- Issue #XXX: 相册切换卡顿问题
- PR #XXX: 双模型架构优化

### C. 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-01 | 初始版本，包含完整实施计划 |
