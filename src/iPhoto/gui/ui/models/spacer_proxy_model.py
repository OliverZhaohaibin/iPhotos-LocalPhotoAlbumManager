"""Proxy model that injects spacer rows for the filmstrip view."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractProxyModel,
    QModelIndex,
    QObject,
    Qt,
    QSize,
)

from .roles import Roles


class SpacerProxyModel(QAbstractProxyModel):
    """Wrap an asset model and expose leading/trailing spacer rows."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._spacer_size = QSize(0, 0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_spacer_width(self, width: int) -> None:
        """Update spacer width and notify views when it changes."""

        width = max(0, width)
        if self._spacer_size.width() == width:
            return

        self._spacer_size.setWidth(width)

        # The leading and trailing spacer rows are the only items whose
        # geometry depends on this width. Instead of resetting the entire
        # model (which would force every view to throw away caches and
        # re-query all data), emit targeted ``dataChanged`` signals so
        # views simply refresh the two spacer delegates. This keeps
        # navigation responsive even for very large albums.
        source = self.sourceModel()
        if source is None:
            return

        source_rows = source.rowCount()
        if source_rows <= 0:
            return

        first_idx = self.index(0, 0)
        last_idx = self.index(source_rows + 1, 0)
        roles = [Qt.ItemDataRole.SizeHintRole]
        self.dataChanged.emit(first_idx, first_idx, roles)
        self.dataChanged.emit(last_idx, last_idx, roles)

    # ------------------------------------------------------------------
    # QAbstractProxyModel overrides
    # ------------------------------------------------------------------
    def setSourceModel(self, source_model) -> None:  # type: ignore[override]
        if source_model is self:
            raise ValueError(
                "Circular reference detected: SpacerProxyModel cannot be its own source."
            )

        # Detect indirect cycles if the source is another proxy that points back to us.
        # This isn't exhaustive (doesn't walk the full chain) but catches the most
        # common mistake of `proxy.setSourceModel(proxy_that_wraps_proxy)`.
        candidate = source_model
        while hasattr(candidate, "sourceModel"):
            candidate = candidate.sourceModel()
            if candidate is self:
                raise ValueError(
                    "Circular reference detected: "
                    "SpacerProxyModel source chain leads back to self."
                )

        previous = self.sourceModel()
        if previous is not None:
            try:
                previous.modelReset.disconnect(self._handle_source_reset)
                previous.rowsInserted.disconnect(self._handle_source_reset)
                previous.rowsRemoved.disconnect(self._handle_source_reset)
                previous.dataChanged.disconnect(self._handle_source_data_changed)
            except (RuntimeError, TypeError):  # pragma: no cover - Qt disconnect noise
                pass

        super().setSourceModel(source_model)

        if source_model is not None:
            source_model.modelReset.connect(self._handle_source_reset)
            source_model.rowsInserted.connect(self._handle_source_reset)
            source_model.rowsRemoved.connect(self._handle_source_reset)
            source_model.dataChanged.connect(self._handle_source_data_changed)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        source = self.sourceModel()
        if source is None:
            return 0
        count = source.rowCount(parent)
        return count + 2 if count > 0 else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        source = self.sourceModel()
        return source.columnCount(parent) if source is not None else 0

    def mapToSource(self, proxy_index: QModelIndex) -> QModelIndex:  # noqa: N802
        source = self.sourceModel()
        if source is None or not proxy_index.isValid():
            return QModelIndex()

        # Runtime safety: if source somehow became self (or a wrapper leading to self),
        # prevent infinite recursion and crash. This can happen if the model graph
        # is mutated dynamically in ways `setSourceModel` couldn't catch initially.
        # We explicitly check for identity equality.
        if source is self:
            return QModelIndex()

        # Assuming standard list models where column matches (0)
        row = proxy_index.row()
        count = source.rowCount()
        if not (1 <= row <= count):
            return QModelIndex()
        return source.index(row - 1, proxy_index.column())

    def mapFromSource(self, source_index: QModelIndex) -> QModelIndex:  # noqa: N802
        if not source_index.isValid():
            return QModelIndex()
        return self.index(source_index.row() + 1, source_index.column())

    def index(
        self, row: int, column: int, parent: QModelIndex = QModelIndex()
    ) -> QModelIndex:
        if parent.isValid():
            return QModelIndex()
        return self.createIndex(row, column)

    def parent(self, _index: QModelIndex) -> QModelIndex:  # noqa: N802
        return QModelIndex()

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None

        row = index.row()
        last_row = self.rowCount() - 1
        if row in {0, last_row} and last_row >= 0:
            if role == Roles.IS_SPACER:
                return True
            if role in (Qt.ItemDataRole.SizeHintRole, Qt.SizeHintRole):
                return QSize(self._spacer_size.width(), self._spacer_size.height())
            if role == Qt.ItemDataRole.DisplayRole:
                return None
            return None

        source = self.sourceModel()
        if source is None:
            return None

        # Prevent recursion loop where delegate checks for spacer role on standard items,
        # which maps to source, which might somehow trigger proxy index creation again?
        # Actually, the deadloop is likely simply:
        # 1. delegate.sizeHint calls index.data(IS_SPACER)
        # 2. index.data calls mapToSource
        # 3. mapToSource calls source.index
        # 4. If source is somehow wrapping us back, or if mapToSource logic is flawed?
        #
        # The traceback shows `SpacerProxyModel.index` being called inside `AssetDelegate.sizeHint`.
        # `sizeHint` takes `index` as argument. It calls `index.data`.
        # If `index` belongs to `SpacerProxyModel`, `data` is called.
        # Inside `data`, we call `mapToSource`.
        # `mapToSource` calls `source.index`.
        # If `source` is NOT the `SpacerProxyModel` itself (checked in `setSourceModel`), then it should be fine.
        #
        # However, the traceback implies `index` (the method) is called.
        # `mapFromSource` calls `index`.
        #
        # Let's look at `AssetDelegate.sizeHint`:
        # `if bool(index.data(Roles.IS_SPACER)):`
        #
        # If `index.data` calls something that eventually calls `sizeHint` again?
        # No, `sizeHint` is a delegate method called by the View.
        #
        # Wait, the traceback shows `SpacerProxyModel.index` calling `AssetDelegate.sizeHint`??
        # No, the traceback shows:
        #   File ".../asset_delegate.py", line 48, in sizeHint
        #     if bool(index.data(Roles.IS_SPACER)):
        #   File ".../spacer_proxy_model.py", line 132, in index
        #     if parent.isValid():
        #
        # Line 132 in `spacer_proxy_model.py` is inside `index()` method.
        # Why would `index.data` call `SpacerProxyModel.index`?
        # `data` calls `mapToSource`, which calls `source.index`.
        # `data` does NOT call `self.index`.
        #
        # Unless... `source` IS `self`. Or `source` wraps `self`.
        # `setSourceModel` has checks, but maybe they are insufficient?
        #
        # OR:
        # `data` implementation:
        # `source_index = self.mapToSource(index)`
        #
        # `mapToSource`:
        # `return source.index(row - 1, proxy_index.column())`
        #
        # If `source` is `self`, then `self.index` is called.
        # `setSourceModel` checks `if source_model is self`.
        #
        # Is it possible that `index.data` triggers a signal that causes the view to call `index()`?
        # No, `data()` should be const-like.
        #
        # Wait, the traceback alternates between `sizeHint` and `index`.
        # `sizeHint` calls `data`.
        # `data` calls... `index`?
        #
        # Maybe `index.data(Roles.IS_SPACER)` returns `None` (falling through to `source.data`)
        # and `source.data` somehow triggers `sizeHint`?
        #
        # Let's look at `index()` implementation in `SpacerProxyModel`.
        # `if parent.isValid(): return QModelIndex()`
        # `return self.createIndex(row, column)`
        #
        # It's a very simple method. How can `sizeHint` call it?
        # `sizeHint` doesn't call `index()`.
        #
        # Maybe the traceback is misleading or I am misreading it?
        # "File ... asset_delegate.py ... sizeHint ... if bool(index.data(Roles.IS_SPACER))"
        # "File ... spacer_proxy_model.py ... index ... if parent.isValid()"
        #
        # This implies `index.data` calls `index`?
        # `data` -> `mapToSource` -> `source.index`.
        # If `source` is `self` (SpacerProxyModel), then `self.index` is called.
        #
        # This confirms a cycle in the model structure. `SpacerProxyModel` is wrapping itself, or a model chain leads back to it.
        # The `setSourceModel` check prevents direct self-wrapping.
        # But maybe `AssetModel` wraps `AssetListModel`, and `SpacerProxyModel` wraps `AssetModel`?
        # If someone did `model.setSourceModel(model)`, that would be caught.
        #
        # If the traceback shows `SpacerProxyModel.index` being called from `AssetDelegate.sizeHint`, it means `sizeHint` invoked something that led to `index`.
        # The only call in `sizeHint` at line 48 is `index.data(Roles.IS_SPACER)`.
        # So `index.data` MUST be leading to `SpacerProxyModel.index`.
        # Since `data` calls `source.index` (via `mapToSource`), `source` MUST be `SpacerProxyModel`.
        #
        # How did `source` become `self`?
        # Maybe `setSourceModel` check is bypassed or `source` changes?
        #
        # Let's strengthen the cycle detection in `setSourceModel`.
        # Also, inside `mapToSource`, we can add a runtime check.

        source_index = self.mapToSource(index)
        if not source_index.isValid():
            return None
        return source.data(source_index, role)

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:  # noqa: N802
        if not index.isValid():
            return Qt.NoItemFlags
        if bool(self.data(index, Roles.IS_SPACER)):
            return Qt.NoItemFlags
        source_index = self.mapToSource(index)
        source = self.sourceModel()
        if source is None or not source_index.isValid():
            return Qt.NoItemFlags
        return source.flags(source_index)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _handle_source_reset(self, *args, **_kwargs) -> None:  # pragma: no cover - Qt signal glue
        self.beginResetModel()
        self.endResetModel()

    def _handle_source_data_changed(
        self,
        top_left: QModelIndex,
        bottom_right: QModelIndex,
        roles: list[int] | None = None,
    ) -> None:
        """Forward data changes from the source model to the proxy."""

        if not top_left.isValid() or not bottom_right.isValid():
            return

        proxy_top_left = self.mapFromSource(top_left)
        proxy_bottom_right = self.mapFromSource(bottom_right)

        if not proxy_top_left.isValid() or not proxy_bottom_right.isValid():
            return

        # ``dataChanged`` signal signature requires roles to be a list or empty.
        # Passing None directly can cause issues with some Qt bindings/versions.
        safe_roles = roles if roles is not None else []
        self.dataChanged.emit(proxy_top_left, proxy_bottom_right, safe_roles)
