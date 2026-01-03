"""List model combining ``index.jsonl`` and ``links.json`` data."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Tuple

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QSize,
    Qt,
    Signal,
    Slot,
    QTimer,
)
from PySide6.QtGui import QPixmap

from ...tasks.thumbnail_loader import ThumbnailLoader
from ...tasks.asset_loader_worker import normalize_featured
from ..asset_cache_manager import AssetCacheManager
from ..asset_data_loader import AssetDataLoader
from ..asset_state_manager import AssetListStateManager
from ..asset_row_adapter import AssetRowAdapter
from ..roles import Roles, role_names
from .....models.album import Album
from .....errors import IPhotoError
from .....utils.pathutils import (
    normalise_for_compare,
    is_descendant_path,
    normalise_rel_value,
)

from .orchestrator import AssetDataOrchestrator
from .refresh_handler import IncrementalUpdateHandler
from .filter_engine import ModelFilterHandler

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from ....facade import AppFacade


logger = logging.getLogger(__name__)


class AssetListModel(QAbstractListModel):
    """Expose album assets to Qt views."""

    # ``Path`` is used explicitly so that static compilers such as Nuitka can
    # prove that the connected slots accept the same signature.
    loadProgress = Signal(Path, int, int)
    loadFinished = Signal(Path, bool)

    def __init__(self, facade: "AppFacade", parent=None) -> None:  # type: ignore[override]
        super().__init__(parent)
        self._facade = facade
        self._album_root: Optional[Path] = None
        self._thumb_size = QSize(512, 512)

        # Try to acquire library root early if available
        library_root = None
        if self._facade.library_manager:
            library_root = self._facade.library_manager.root()

        self._cache_manager = AssetCacheManager(self._thumb_size, self, library_root=library_root)
        self._cache_manager.thumbnailReady.connect(self._on_thumb_ready)

        # State & Helpers
        self._state_manager = AssetListStateManager(self, self._cache_manager)
        self._cache_manager.set_recently_removed_limit(256)
        self._row_adapter = AssetRowAdapter(self._thumb_size, self._cache_manager)
        self._filter_handler = ModelFilterHandler()

        # Data Loading & Orchestration
        self._data_loader = AssetDataLoader(self)
        self._orchestrator = AssetDataOrchestrator(
            self._data_loader,
            self._filter_handler,
            self._state_manager,
            parent=self
        )
        self._orchestrator.rowsReadyForInsertion.connect(self._on_rows_ready_for_insertion)
        self._orchestrator.firstChunkReady.connect(self._on_first_chunk_ready)
        self._orchestrator.loadProgress.connect(self.loadProgress)
        self._orchestrator.loadFinished.connect(self._on_load_finished)
        self._orchestrator.loadError.connect(self._on_load_error)

        # Incremental Updates
        self._incremental_handler = IncrementalUpdateHandler(
            get_current_rows=lambda: self._state_manager.rows,
            get_featured=self._get_featured_list,
            get_filter_params=self._filter_handler.get_filter_params,
            parent=self
        )
        self._incremental_handler.removeRowsRequested.connect(self._on_remove_rows_requested)
        self._incremental_handler.insertRowsRequested.connect(self._on_insert_rows_requested)
        self._incremental_handler.rowDataChanged.connect(self._on_row_data_changed)
        self._incremental_handler.modelResetRequested.connect(self._on_model_reset_requested)
        self._incremental_handler.refreshError.connect(self._on_incremental_error)

        self._deferred_incremental_refresh: Optional[Path] = None

        self._facade.linksUpdated.connect(self.handle_links_updated)
        self._facade.assetUpdated.connect(self.handle_asset_updated)
        self._facade.scanChunkReady.connect(self._on_scan_chunk_ready)

    def set_library_root(self, root: Path) -> None:
        """Update the centralized library root for thumbnail generation and index access."""
        self._cache_manager.set_library_root(root)
        self._data_loader.set_library_root(root)

    def album_root(self) -> Optional[Path]:
        """Return the path of the currently open album, if any."""
        return self._album_root

    def metadata_for_absolute_path(self, path: Path) -> Optional[Dict[str, object]]:
        """Return the cached metadata row for *path* if it belongs to the model."""

        rows = self._state_manager.rows
        if not rows:
            return None

        album_root = self._album_root
        try:
            normalized_path = path.resolve()
        except OSError:
            normalized_path = path

        if album_root is not None:
            try:
                normalized_root = album_root.resolve()
            except OSError:
                normalized_root = album_root
            try:
                rel_key = normalized_path.relative_to(normalized_root).as_posix()
            except ValueError:
                rel_key = None
            else:
                row_index = self._state_manager.row_lookup.get(rel_key)
                if row_index is not None and 0 <= row_index < len(rows):
                    return rows[row_index]

        normalized_str = str(normalized_path)
        row_index = self._state_manager.get_index_by_abs(normalized_str)
        if row_index is not None and 0 <= row_index < len(rows):
            return rows[row_index]

        cached = self._cache_manager.recently_removed(normalized_str)
        if cached is not None:
            return cached
        return None

    def remove_rows(self, indexes: list[QModelIndex]) -> None:
        """Remove assets referenced by *indexes*, tolerating proxy selections."""
        self._state_manager.remove_rows(indexes)

    def update_rows_for_move(
        self,
        rels: list[str],
        destination_root: Path,
        *,
        is_source_main_view: bool = False,
    ) -> None:
        """Apply optimistic UI updates when a move operation is queued."""
        if not self._album_root:
            return

        changed_rows = self._state_manager.update_rows_for_move(
            rels,
            destination_root,
            self._album_root,
            is_source_main_view=is_source_main_view,
        )

        for row in changed_rows:
            model_index = self.index(row, 0)
            self.dataChanged.emit(
                model_index,
                model_index,
                [Roles.REL, Roles.ABS, Qt.DecorationRole],
            )

    def finalise_move_results(self, moves: List[Tuple[Path, Path]]) -> None:
        """Reconcile optimistic move updates with the worker results."""
        updated_rows = self._state_manager.finalise_move_results(moves, self._album_root)

        for row in updated_rows:
            model_index = self.index(row, 0)
            self.dataChanged.emit(
                model_index,
                model_index,
                [Roles.REL, Roles.ABS, Qt.DecorationRole],
            )

    def rollback_pending_moves(self) -> None:
        """Restore original metadata for moves that failed or were cancelled."""
        restored_rows = self._state_manager.rollback_pending_moves(self._album_root)

        for row in restored_rows:
            model_index = self.index(row, 0)
            self.dataChanged.emit(
                model_index,
                model_index,
                [Roles.REL, Roles.ABS, Qt.DecorationRole],
            )

    def has_pending_move_placeholders(self) -> bool:
        """Return ``True`` when optimistic move updates are awaiting results."""
        return self._state_manager.has_pending_move_placeholders()

    def populate_from_cache(self) -> bool:
        """Synchronously load cached index data when the file is small."""
        return False

    # ------------------------------------------------------------------
    # Qt model implementation
    # ------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        if parent is not None and parent.isValid():
            return 0
        return self._state_manager.row_count()

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        rows = self._state_manager.rows
        if not index.isValid() or not (0 <= index.row() < len(rows)):
            return None
        return self._row_adapter.data(rows[index.row()], role)

    def roleNames(self) -> Dict[int, bytes]:  # type: ignore[override]
        return role_names(super().roleNames())

    def setData(
        self, index: QModelIndex, value: Any, role: int = Qt.EditRole
    ) -> bool:  # type: ignore[override]
        rows = self._state_manager.rows
        if not index.isValid() or not (0 <= index.row() < len(rows)):
            return False
        if role != Roles.IS_CURRENT:
            return super().setData(index, value, role)

        normalized = bool(value)
        row = rows[index.row()]
        if bool(row.get("is_current", False)) == normalized:
            return True
        row["is_current"] = normalized
        self.dataChanged.emit(index, index, [Roles.IS_CURRENT])
        return True

    def thumbnail_loader(self) -> ThumbnailLoader:
        return self._cache_manager.thumbnail_loader()

    def get_internal_row(self, row_index: int) -> Optional[Dict[str, object]]:
        """Return the raw dictionary for *row_index* to bypass the Qt role API."""
        rows = self._state_manager.rows
        if not (0 <= row_index < len(rows)):
            return None
        return rows[row_index]

    def invalidate_thumbnail(self, rel: str) -> Optional[QModelIndex]:
        """Remove cached thumbnails and notify views for *rel*."""
        if not rel:
            return None
        self._cache_manager.remove_thumbnail(rel)
        loader = self._cache_manager.thumbnail_loader()
        loader.invalidate(rel)
        row_index = self._state_manager.row_lookup.get(rel)
        rows = self._state_manager.rows
        if row_index is None or not (0 <= row_index < len(rows)):
            return None
        model_index = self.index(row_index, 0)
        self.dataChanged.emit(model_index, model_index, [Qt.DecorationRole])
        return model_index

    # ------------------------------------------------------------------
    # Facade callbacks
    # ------------------------------------------------------------------
    def prepare_for_album(self, root: Path) -> None:
        """Reset internal state so *root* becomes the active album."""
        self._orchestrator.cancel_load()

        self._state_manager.clear_reload_pending()
        self._album_root = root
        self._cache_manager.reset_for_album(root)
        self._set_deferred_incremental_refresh(None)

        self.beginResetModel()
        self._state_manager.clear_rows()
        self.endResetModel()
        self._cache_manager.clear_recently_removed()
        self._state_manager.set_virtual_reload_suppressed(False)
        self._state_manager.set_virtual_move_requires_revisit(False)

    def update_featured_status(self, rel: str, is_featured: bool) -> None:
        """Update the cached ``featured`` flag for the asset identified by *rel*."""
        rel_key = str(rel)
        row_index = self._state_manager.row_lookup.get(rel_key)
        rows = self._state_manager.rows
        if row_index is None or not (0 <= row_index < len(rows)):
            return

        row = rows[row_index]
        current = bool(row.get("featured", False))
        normalized = bool(is_featured)
        if current == normalized:
            return

        row["featured"] = normalized
        model_index = self.index(row_index, 0)
        self.dataChanged.emit(model_index, model_index, [Roles.FEATURED])

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    def set_filter_mode(self, mode: Optional[str]) -> None:
        """Apply a new filter mode and trigger a reload if necessary."""
        changed = self._filter_handler.set_mode(mode)
        if not changed:
            return

        # Clear data immediately to avoid ghosting
        self.beginResetModel()
        self._state_manager.clear_rows()
        self.endResetModel()

        self.start_load()

    def active_filter_mode(self) -> Optional[str]:
        return self._filter_handler.get_mode()

    # ------------------------------------------------------------------
    # Data loading helpers
    # ------------------------------------------------------------------
    def start_load(self) -> None:
        if not self._album_root:
            return

        self._cache_manager.clear_recently_removed()

        manifest = self._facade.current_album.manifest if self._facade.current_album else {}
        featured = manifest.get("featured", []) or []

        try:
            self._orchestrator.start_load(
                self._album_root,
                featured,
                filter_params=self._filter_handler.get_filter_params(),
                library_manager=self._facade.library_manager
            )
        except RuntimeError:
            self._state_manager.mark_reload_pending()
            return

        self._state_manager.clear_reload_pending()

    def _get_featured_list(self) -> List[str]:
        """Helper to get featured list for incremental updates."""
        manifest = self._facade.current_album.manifest if self._facade.current_album else {}
        return manifest.get("featured", []) or []

    def _on_first_chunk_ready(self, chunk: List[Dict[str, object]], suggested_reset: bool) -> None:
        """Handle the first chunk of a load, possibly resetting the model."""
        if suggested_reset and self._state_manager.row_count() == 0:
            # Clean reset
            self.beginResetModel()
            self._state_manager.clear_rows()
            self._state_manager.append_chunk(chunk)
            self.endResetModel()
            self.prioritize_rows(0, len(chunk) - 1)
        else:
            # We have data (e.g. from live buffer), append instead
            self._on_rows_ready_for_insertion(-1, chunk)

    def _on_rows_ready_for_insertion(self, start_row: int, rows: List[Dict[str, object]]) -> None:
        """Insert prepared rows into the model."""
        if start_row < 0:
            start_row = self._state_manager.row_count()

        end_row = start_row + len(rows) - 1

        self.beginInsertRows(QModelIndex(), start_row, end_row)
        self._state_manager.append_chunk(rows)
        self.endInsertRows()

        self._state_manager.on_external_row_inserted(start_row, len(rows))

    def _on_scan_chunk_ready(self, root: Path, chunk: List[Dict[str, object]]) -> None:
        """Integrate fresh rows from the scanner into the live view."""
        if not self._album_root or not chunk:
            return

        entries = AssetDataOrchestrator.process_scan_chunk(
            root,
            chunk,
            self._album_root,
            self._state_manager,
            featured=self._get_featured_list(),
            filter_mode=self._filter_handler.get_mode(),
        )

        if entries:
            self._on_rows_ready_for_insertion(-1, entries)

    def _on_load_finished(self, root: Path, success: bool) -> None:
        """Handle load completion."""
        # Handle deferred refresh if needed
        if (
            success
            and self._album_root
            and self._deferred_incremental_refresh
            and normalise_for_compare(self._album_root)
            == self._deferred_incremental_refresh
        ):
            logger.debug(
                "AssetListModel: applying deferred incremental refresh for %s after loader completion.",
                self._album_root,
            )
            pending_root = self._album_root
            self._set_deferred_incremental_refresh(None)
            self._refresh_rows_from_index(pending_root)

        should_restart = self._state_manager.consume_pending_reload(self._album_root, root)
        if should_restart:
            QTimer.singleShot(0, self.start_load)

    def _on_load_error(self, root: Path, message: str) -> None:
        """Handle load error."""
        if self._album_root and root == self._album_root:
             self._facade.errorRaised.emit(message)

        # Ensure we signal completion so spinners stop
        self.loadFinished.emit(root, False)

        should_restart = self._state_manager.consume_pending_reload(self._album_root, root)
        if should_restart:
            QTimer.singleShot(0, self.start_load)

    # ------------------------------------------------------------------
    # Incremental Updates (Delegated)
    # ------------------------------------------------------------------
    def _on_remove_rows_requested(self, index: int, count: int) -> None:
        """Handle removal request from incremental handler."""
        rows = self._state_manager.rows
        if not (0 <= index < len(rows)):
            return

        end_index = index + count - 1
        if end_index >= len(rows):
            end_index = len(rows) - 1
            count = end_index - index + 1

        self.beginRemoveRows(QModelIndex(), index, end_index)

        # Process removals
        removed_items = rows[index : index + count]
        del rows[index : index + count]

        self.endRemoveRows()

        for row_snapshot in removed_items:
            rel_key = normalise_rel_value(row_snapshot.get("rel"))
            abs_key = row_snapshot.get("abs")

            # Update pending pointers for each removal
            self._state_manager.on_external_row_removed(index, rel_key)

            if rel_key:
                self._cache_manager.remove_thumbnail(rel_key)
                self._cache_manager.remove_placeholder(rel_key)
            if abs_key:
                self._cache_manager.remove_recently_removed(str(abs_key))

        # IMPORTANT: Rebuild lookup to keep indices in sync!
        self._state_manager.rebuild_lookup()

    def _on_insert_rows_requested(self, index: int, new_rows: List[Dict[str, object]]) -> None:
        """Handle insertion request from incremental handler."""
        rows = self._state_manager.rows
        position = max(0, min(index, len(rows)))

        count = len(new_rows)
        if count == 0:
            return

        self.beginInsertRows(QModelIndex(), position, position + count - 1)
        # Use slice assignment/insertion
        rows[position:position] = new_rows
        self.endInsertRows()

        self._state_manager.on_external_row_inserted(position, count)

        # Cleanup caches for inserted items
        for row_data in new_rows:
            rel_key = normalise_rel_value(row_data.get("rel"))
            if rel_key:
                self._cache_manager.remove_thumbnail(rel_key)
                self._cache_manager.remove_placeholder(rel_key)
            abs_value = row_data.get("abs")
            if abs_value:
                self._cache_manager.remove_recently_removed(str(abs_value))

        # IMPORTANT: Rebuild lookup to keep indices in sync!
        self._state_manager.rebuild_lookup()

    def _on_model_reset_requested(self, new_rows: List[Dict[str, object]]) -> None:
        """Handle full reset request from incremental handler."""
        self.beginResetModel()
        self._state_manager.set_rows(new_rows)
        self.endResetModel()
        self._cache_manager.reset_caches_for_new_rows(new_rows)
        self._state_manager.clear_visible_rows()

    def _on_row_data_changed(self, index: int, row_data: Dict[str, object]) -> None:
        """Handle row data update from incremental handler."""
        rows = self._state_manager.rows
        rel_key = normalise_rel_value(row_data.get("rel"))

        # Lookup index if -1
        if index == -1:
            if not rel_key:
                return
            idx = self._state_manager.row_lookup.get(rel_key)
            if idx is None:
                return
            index = idx

        if not (0 <= index < len(rows)):
            return

        original = rows[index]

        # Update row via state manager to ensure lookups (abs/rel) are synced correctly
        # This will also update the row in the list
        self._state_manager.update_row_at_index(index, row_data)

        model_index = self.index(index, 0)
        affected_roles = [
            Roles.REL, Roles.ABS, Roles.SIZE, Roles.DT,
            Roles.IS_IMAGE, Roles.IS_VIDEO, Roles.IS_LIVE,
            Qt.DecorationRole,
        ]
        self.dataChanged.emit(model_index, model_index, affected_roles)

        if self._should_invalidate_thumbnail(original, row_data):
            if rel_key:
                self.invalidate_thumbnail(rel_key)

    def _on_incremental_error(self, root: Path, message: str) -> None:
        """Handle incremental refresh error."""
        logger.error("AssetListModel: incremental refresh error for %s: %s", root, message)

    def _should_invalidate_thumbnail(
        self, old_row: Dict[str, object], new_row: Dict[str, object]
    ) -> bool:
        """Return True if the thumbnail must be regenerated based on row changes."""
        visual_keys = {"ts", "bytes", "abs", "w", "h", "still_image_time"}
        for key in visual_keys:
            if old_row.get(key) != new_row.get(key):
                return True
        return False

    # ------------------------------------------------------------------
    # Thumbnail helpers
    # ------------------------------------------------------------------
    def prioritize_rows(self, first: int, last: int) -> None:
        """Request high-priority thumbnails for the inclusive range *first*→*last*."""
        rows = self._state_manager.rows
        if not rows:
            self._state_manager.clear_visible_rows()
            return

        if first > last:
            first, last = last, first

        first = max(first, 0)
        last = min(last, len(rows) - 1)
        if first > last:
            self._state_manager.clear_visible_rows()
            return

        requested = set(range(first, last + 1))
        if not requested:
            self._state_manager.clear_visible_rows()
            return

        uncached = {
            row
            for row in requested
            if self._cache_manager.thumbnail_for(str(rows[row]["rel"])) is None
        }
        if not uncached:
            self._state_manager.set_visible_rows(requested)
            return
        if uncached.issubset(self._state_manager.visible_rows):
            self._state_manager.set_visible_rows(requested)
            return

        self._state_manager.set_visible_rows(requested)
        for row in range(first, last + 1):
            if row not in uncached:
                continue
            row_data = rows[row]
            self._cache_manager.resolve_thumbnail(
                row_data, ThumbnailLoader.Priority.VISIBLE
            )

    def _on_thumb_ready(self, root: Path, rel: str, pixmap: QPixmap) -> None:
        if not self._album_root or root != self._album_root:
            return
        index = self._state_manager.row_lookup.get(rel)
        if index is None:
            return
        model_index = self.index(index, 0)
        self.dataChanged.emit(model_index, model_index, [Qt.DecorationRole])

    @Slot(Path)
    def handle_asset_updated(self, path: Path) -> None:
        """Refresh the thumbnail and view when an asset is modified."""
        metadata = self.metadata_for_absolute_path(path)
        if metadata is None:
            return

        rel = metadata.get("rel")
        if not rel:
            return

        self.invalidate_thumbnail(str(rel))

    @Slot(Path)
    def handle_links_updated(self, root: Path) -> None:
        """React to :mod:`links.json` refreshes triggered by the backend."""
        if not self._album_root:
            return

        album_root = normalise_for_compare(self._album_root)
        updated_root = normalise_for_compare(Path(root))

        if not self._links_update_targets_current_view(album_root, updated_root):
            return

        if self._state_manager.suppress_virtual_reload():
            if self._state_manager.virtual_move_requires_revisit():
                return
            self._state_manager.set_virtual_reload_suppressed(False)
            if self._state_manager.rows:
                self._refresh_rows_from_index(self._album_root)
            return

        descendant_root = updated_root if updated_root != album_root else None

        if self._state_manager.rows:
            self._refresh_rows_from_index(self._album_root, descendant_root=descendant_root)

        if not self._state_manager.rows or self._orchestrator.is_loading():
            self._set_deferred_incremental_refresh(self._album_root)
            return

        self._set_deferred_incremental_refresh(None)
        self._refresh_rows_from_index(self._album_root, descendant_root=descendant_root)

    def _refresh_rows_from_index(
        self, root: Path, descendant_root: Optional[Path] = None
    ) -> None:
        """Synchronise the model with the latest index snapshot for *root*."""
        self._incremental_handler.refresh_from_index(root, descendant_root)

    def _set_deferred_incremental_refresh(self, root: Optional[Path]) -> None:
        """Remember that an incremental refresh should run once loading settles."""
        if root is None:
            self._deferred_incremental_refresh = None
            return
        self._deferred_incremental_refresh = normalise_for_compare(root)

    def _links_update_targets_current_view(
        self, album_root: Path, updated_root: Path
    ) -> bool:
        """Return ``True`` when ``links.json`` updates should refresh the model."""
        if album_root == updated_root:
            return True
        return is_descendant_path(updated_root, album_root)
