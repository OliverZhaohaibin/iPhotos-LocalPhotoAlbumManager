from __future__ import annotations
import copy
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Tuple, Set, Any

from PySide6.QtCore import QObject, QRunnable, Signal, QThread

from ....cache.index_store import IndexStore
from ....config import WORK_DIR_NAME
from ....utils.pathutils import ensure_work_dir
from .asset_loader_worker import (
    compute_album_path,
    adjust_rel_for_album,
    normalize_featured,
    build_asset_entry,
    _cached_path_exists
)

class PageLoaderSignals(QObject):
    """Signals for the PageLoaderWorker."""
    pageReady = Signal(Path, list, int)  # root, entries, total_count
    error = Signal(Path, str)

class PageLoaderWorker(QRunnable):
    """Background worker to load a single page of assets using cursor pagination."""

    def __init__(
        self,
        root: Path,
        featured: Iterable[str],
        signals: PageLoaderSignals,
        cursor: Optional[Tuple[str, str]] = None, # (dt, id)
        limit: int = 100,
        filter_params: Optional[Dict[str, object]] = None,
        library_root: Optional[Path] = None,
        fetch_total: bool = False
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._root = root
        self._featured = normalize_featured(featured)
        self._signals = signals
        self._cursor = cursor
        self._limit = limit
        self._filter_params = filter_params
        self._library_root = library_root
        self._fetch_total = fetch_total
        self._dir_cache: Dict[Path, Optional[Set[str]]] = {}

    def run(self) -> None:
        try:
            ensure_work_dir(self._root, WORK_DIR_NAME)
            effective_index_root, album_path = compute_album_path(self._root, self._library_root)
            store = IndexStore(effective_index_root)

            params = copy.deepcopy(self._filter_params) if self._filter_params else {}

            cursor_dt, cursor_id = self._cursor if self._cursor else (None, None)

            # Fetch the page
            raw_rows = store.get_assets_page(
                cursor_dt=cursor_dt,
                cursor_id=cursor_id,
                limit=self._limit,
                album_path=album_path,
                include_subalbums=True, # Requirement 3B
                filter_hidden=True, # Usually we hide hidden assets (motion components)
                filter_params=params
            )

            total_count = -1
            if self._fetch_total:
                try:
                    total_count = store.count(
                        filter_hidden=True,
                        filter_params=params,
                        album_path=album_path,
                        include_subalbums=True
                    )
                except Exception:
                    pass

            entries = []
            def _path_exists(path: Path) -> bool:
                return _cached_path_exists(path, self._dir_cache)

            for row in raw_rows:
                 adjusted_row = adjust_rel_for_album(row, album_path)
                 entry = build_asset_entry(
                     self._root,
                     adjusted_row,
                     self._featured,
                     store,
                     path_exists=_path_exists
                 )
                 if entry:
                     entries.append(entry)

            self._signals.pageReady.emit(self._root, entries, total_count)

        except Exception as e:
            self._signals.error.emit(self._root, str(e))
