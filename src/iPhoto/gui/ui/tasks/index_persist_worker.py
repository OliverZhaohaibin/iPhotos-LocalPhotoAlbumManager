"""Helper to persist index entries to disk."""

from pathlib import Path
from typing import List, Dict

from PySide6.QtCore import QRunnable, QObject

from .... import app as backend
from ....utils.logging import get_logger

logger = get_logger()

class IndexPersistWorker(QRunnable):
    """Persist a list of asset entries to an album's local index.db."""

    def __init__(self, album_root: Path, entries: List[Dict[str, object]]) -> None:
        super().__init__()
        self._album_root = album_root
        self._entries = entries

    def run(self) -> None:
        if not self._entries:
            return

        try:
            # Persist to the standard index.db (global_index.db) format.
            # We align with the system default to ensure the View and Scanner use the same database.
            store = backend.IndexStore(self._album_root)
            store.append_rows(self._entries)
            logger.info("Persisted %d entries to local index for %s", len(self._entries), self._album_root)
        except Exception as e:
            logger.error("Failed to persist index for %s: %s", self._album_root, e)
