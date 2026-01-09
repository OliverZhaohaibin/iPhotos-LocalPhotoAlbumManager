from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from iPhoto.gui.ui.media.playlist_controller import PlaylistController
from iPhoto.gui.ui.models.asset_model import Roles


class _DummyModel(QAbstractListModel):
    def __init__(self, rows: list[dict], album_root: Path):
        super().__init__()
        self._rows = rows
        self._album_root = album_root

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return 1

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        try:
            row = self._rows[index.row()]
        except IndexError:
            return None
        return row.get(role)

    def index(self, row: int, column: int = 0, parent: QModelIndex | None = None) -> QModelIndex:  # type: ignore[override]
        return super().index(row, column, parent)

    def source_model(self):
        return self

    def album_root(self) -> Path:
        return self._album_root

    def reorder(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


def test_set_current_by_path_restores_selection_after_reorder(tmp_path: Path) -> None:
    album_root = tmp_path
    path_a = album_root / "a.jpg"
    path_b = album_root / "b.jpg"
    rows = [
        {Roles.ABS: str(path_a), Roles.REL: "a.jpg", Roles.IS_LIVE: False},
        {Roles.ABS: str(path_b), Roles.REL: "b.jpg", Roles.IS_LIVE: False},
    ]
    model = _DummyModel(rows, album_root)
    playlist = PlaylistController()
    playlist.bind_model(model)

    assert playlist.set_current(0) == path_a
    assert playlist.current_source() == path_a

    model.reorder([rows[1], rows[0]])
    # The selection may now point at the moved row; ensure the helper restores it.
    assert playlist.set_current_by_path(path_a)
    assert playlist.current_source() == path_a
