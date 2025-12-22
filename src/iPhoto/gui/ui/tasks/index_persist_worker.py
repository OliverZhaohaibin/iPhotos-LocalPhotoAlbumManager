"""Helper to persist index entries to disk."""

from pathlib import Path
from typing import List, Dict

from PySide6.QtCore import QRunnable, QObject

from typing import List, Dict, Optional

from .... import app as backend
from ....utils.logging import get_logger
from .asset_loader_worker import adjust_rel_for_album

logger = get_logger()

class IndexPersistWorker(QRunnable):
    """Persist a list of asset entries to an album's local index.db."""

    def __init__(self, album_root: Path, entries: List[Dict[str, object]], album_rel_path: Optional[str] = None) -> None:
        super().__init__()
        self._album_root = album_root
        self._entries = entries
        self._album_rel_path = album_rel_path

    def run(self) -> None:
        if not self._entries:
            return

        try:
            # Adjust paths in background thread to avoid UI freeze
            adjusted_entries = []
            album_rel_path = self._album_rel_path

            for entry in self._entries:
                # Adjust 'rel' using the standard helper
                new_entry = adjust_rel_for_album(entry, album_rel_path)

                # Manually adjust 'live_partner_rel' if present
                live_rel = new_entry.get("live_partner_rel")
                if album_rel_path and isinstance(live_rel, str) and live_rel.startswith(album_rel_path + "/"):
                    new_entry["live_partner_rel"] = live_rel[len(album_rel_path) + 1:]

                # Clear 'parent_album_path'
                if "parent_album_path" in new_entry:
                    del new_entry["parent_album_path"]

                adjusted_entries.append(new_entry)

            # Persist to the standard index.db (global_index.db) format.
            # We align with the system default to ensure the View and Scanner use the same database.
            store = backend.IndexStore(self._album_root)
            store.append_rows(adjusted_entries)
            logger.info("Persisted %d entries to local index for %s", len(adjusted_entries), self._album_root)
        except Exception as e:
            logger.error("Failed to persist index for %s: %s", self._album_root, e)
