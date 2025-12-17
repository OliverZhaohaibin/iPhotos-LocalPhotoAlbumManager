"""Background worker for album maintenance tasks."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from .... import app as backend


class MaintenanceSignals(QObject):
    """Signals for the maintenance worker."""
    finished = Signal(Path)
    error = Signal(Path, str)


class MaintenanceWorker(QRunnable):
    """
    Background worker that runs `backend.maintain_album`.
    This performs live photo pairing and favorites synchronization without blocking the UI.
    """

    def __init__(self, root: Path, signals: MaintenanceSignals) -> None:
        super().__init__()
        self._root = root
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            # We skip autoscan here because maintenance is usually triggered after
            # we've already decided whether to scan or not in the main flow.
            # However, `backend.maintain_album` defaults autoscan=True.
            # If we want to strictly do pairing/sync, we should ensure the index exists first.
            # But maintain_album handles that.
            # We assume autoscan=False because if the index is empty, the facade
            # likely already triggered a background scan via LibraryManager.
            # We don't want two concurrent scans.
            backend.maintain_album(self._root, autoscan=False)
            self._signals.finished.emit(self._root)
        except Exception as e:
            self._signals.error.emit(self._root, str(e))
